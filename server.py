from __future__ import annotations
import argparse,csv,io,ipaddress,json,os,re,socket,sqlite3,urllib.request,urllib.error
from urllib.parse import urlparse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).parent; DB=ROOT/'analytics.sqlite3'; STATIC=ROOT/'static'; SOURCE=ROOT/'global_ecommerce_sales.csv'
AI={'state':'not-tested','message':'AI not tested'}
REL=['customers.customer_id = orders.customer_id','orders.order_id = order_items.order_id','products.product_id = order_items.product_id','customers.customer_id = events.customer_id']
class AIError(RuntimeError):pass
def q(s):return '"'+s.replace('"','""')+'"'
def clean(s):
 s=re.sub(r'[^\w]+','_',Path(str(s or '')).stem,flags=re.UNICODE).strip('_').lower() or 'uploaded_data'; return ('data_'+s if s[0].isdigit() else s)[:50]
def unique_columns(fieldnames):
 used=set();result=[]
 for index,raw in enumerate(fieldnames,1):
  base=re.sub(r'[^\w]+','_',str(raw or ''),flags=re.UNICODE).strip('_').lower() or f'column_{index}'
  if base[0].isdigit():base='field_'+base
  base=base[:50];name=base;suffix=2
  while name in used:
   tail=f'_{suffix}';name=base[:50-len(tail)]+tail;suffix+=1
  used.add(name);result.append(name)
 return result
def env():
 p=ROOT/'.env'
 if p.exists():
  for x in p.read_text(encoding='utf8').splitlines():
   if x.strip() and not x.lstrip().startswith('#') and '=' in x:
    k,v=x.split('=',1);os.environ[k.strip()]=v.strip().strip('"\'')
def import_csv(c,text,filename,table=None):
 r=csv.DictReader(io.StringIO(text.lstrip('\ufeff'))); raw=list(r)
 if not raw or not r.fieldnames:raise ValueError('CSV has no data rows')
 names=unique_columns(r.fieldnames)
 rows=[[row.get(old,'') for old in r.fieldnames] for row in raw]; types=[]
 for i in range(len(names)):
  try:
   [float(x[i]) for x in rows if str(x[i]).strip()];types.append('REAL')
  except ValueError:types.append('TEXT')
 table=table or clean(filename);c.execute(f'DROP TABLE IF EXISTS {q(table)}');c.execute(f'CREATE TABLE {q(table)} ({",".join(q(n)+" "+t for n,t in zip(names,types))})')
 vals=[[float(v) if types[i]=='REAL' and str(v).strip() else v for i,v in enumerate(row)] for row in rows]
 c.executemany(f'INSERT INTO {q(table)} VALUES ({",".join("?" for _ in names)})',vals);c.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',(f'source:{table}',filename));c.commit();return table,len(rows)
def validate_api_url(url,allow_private=False):
 parsed=urlparse(url)
 if parsed.scheme not in {'http','https'} or not parsed.hostname:raise ValueError('API URL must use http:// or https://')
 if not allow_private:
  try:
   addresses={x[4][0] for x in socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80))}
  except socket.gaierror as e:raise ValueError(f'Cannot resolve API host: {e}')
  if any(ipaddress.ip_address(x).is_private or ipaddress.ip_address(x).is_loopback or ipaddress.ip_address(x).is_link_local for x in addresses):raise ValueError('Private-network API blocked; enable private network access if this endpoint is trusted')
 return parsed
def api_to_csv(url,token='',data_path='',allow_private=False):
 validate_api_url(url,allow_private)
 headers={'Accept':'application/json, text/csv;q=0.9','User-Agent':'InsightSQL/1.0'}
 if token:headers['Authorization']='Bearer '+token
 class SafeRedirect(urllib.request.HTTPRedirectHandler):
  def redirect_request(self,req,fp,code,msg,response_headers,newurl):
   validate_api_url(newurl,allow_private);return super().redirect_request(req,fp,code,msg,response_headers,newurl)
 try:
  with urllib.request.build_opener(SafeRedirect).open(urllib.request.Request(url,headers=headers),timeout=30) as response:
   raw=response.read(20_000_001);content_type=response.headers.get_content_type()
 except urllib.error.HTTPError as e:raise ValueError(f'API returned HTTP {e.code}')
 except (urllib.error.URLError,OSError) as e:raise ValueError(f'API connection failed: {e}')
 if len(raw)>20_000_000:raise ValueError('API response exceeds 20 MB')
 text=raw.decode('utf-8-sig')
 if content_type in {'text/csv','application/csv'} or (not text.lstrip().startswith(('[','{')) and ',' in text.splitlines()[0]):return text
 try:data=json.loads(text)
 except json.JSONDecodeError:raise ValueError('API response is neither valid CSV nor JSON')
 if data_path:
  for part in data_path.split('.'):
   if not isinstance(data,dict) or part not in data:raise ValueError(f'JSON path not found: {data_path}')
   data=data[part]
 elif isinstance(data,dict):
  data=next((data[k] for k in ('data','results','items','records') if isinstance(data.get(k),list)),data)
 if isinstance(data,dict):data=[data]
 if not isinstance(data,list) or not data or not all(isinstance(x,dict) for x in data):raise ValueError('JSON must be an object array, or contain data/results/items/records array')
 fields=list(dict.fromkeys(k for row in data for k in row))
 out=io.StringIO();writer=csv.DictWriter(out,fieldnames=fields);writer.writeheader()
 for row in data:writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})
 return out.getvalue()
def normalize(c):
 rows=[{k.lower():v for k,v in dict(x).items()} for x in c.execute('SELECT * FROM sales ORDER BY order_date,order_id')];cs={};ps={};out={x:[] for x in ['customers','products','orders','order_items','events']};channels=['Organic Search','Paid Social','Email','Direct']
 for i,r in enumerate(rows,1):
  ck=(r['customer_name'],r['customer_segment'],r['country'],r['region']);pk=(r['product_name'],r['product_category'])
  if ck not in cs:cs[ck]=f'C{len(cs)+1:05d}';out['customers'].append((cs[ck],*ck))
  if pk not in ps:ps[pk]=f'P{len(ps)+1:05d}';out['products'].append((ps[pk],*pk,r['unit_price']))
  oid=str(r['order_id']);out['orders'].append((oid,r['order_date'],cs[ck],r['payment_method'],r['shipping_cost']));out['order_items'].append((f'I{i:06d}',oid,ps[pk],r['quantity'],r['unit_price'],r['discount_percent'],r['total_sales'],r['profit']))
  out['events'] += [(f'E{i:06d}A',r['order_date'],cs[ck],'page_view',channels[i%4]),(f'E{i:06d}B',r['order_date'],cs[ck],'purchase',channels[i%4])]
 ddl={'customers':'customer_id TEXT PRIMARY KEY,customer_name TEXT,customer_segment TEXT,country TEXT,region TEXT','products':'product_id TEXT PRIMARY KEY,product_name TEXT,product_category TEXT,standard_unit_price REAL','orders':'order_id TEXT PRIMARY KEY,order_date TEXT,customer_id TEXT,payment_method TEXT,shipping_cost REAL','order_items':'order_item_id TEXT PRIMARY KEY,order_id TEXT,product_id TEXT,quantity REAL,unit_price REAL,discount_percent REAL,total_sales REAL,profit REAL','events':'event_id TEXT PRIMARY KEY,event_date TEXT,customer_id TEXT,event_type TEXT,source TEXT'}
 for t,d in ddl.items():c.execute(f'DROP TABLE IF EXISTS {t}');c.execute(f'CREATE TABLE {t} ({d})');c.executemany(f'INSERT INTO {t} VALUES ({",".join("?" for _ in out[t][0])})',out[t])
 c.commit()
def connect():
 c=sqlite3.connect(DB,timeout=20);c.row_factory=sqlite3.Row;c.execute('PRAGMA journal_mode=WAL');c.execute('CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT)')
 return c
def load_demo():
 c=connect()
 try:
  for table in ['events','order_items','orders','products','customers','sales']:c.execute(f'DROP TABLE IF EXISTS {table}')
  import_csv(c,SOURCE.read_text(encoding='utf-8-sig'),SOURCE.name,'sales');normalize(c);return 6
 finally:c.close()
def schema(c):
 ts=[x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'meta' ORDER BY name")];return {t:[{'name':x[1],'type':x[2] or 'TEXT'} for x in c.execute(f'PRAGMA table_info({q(t)})')] for t in ts}
def catalog(c,s):
 out={}
 for t,cols in s.items():
  for col in cols:
   n=col['name']
   if col['type'].upper()=='TEXT' and c.execute(f'SELECT COUNT(DISTINCT {q(n)}) FROM {q(t)}').fetchone()[0]<=80:
    v=[str(x[0]) for x in c.execute(f"SELECT DISTINCT {q(n)} FROM {q(t)} WHERE {q(n)}<>'' AND {q(n)} IS NOT NULL ORDER BY 1")];
    if v:out[f'{t}.{n}']=v
 return out
def context():
 c=connect()
 try:s=schema(c);return s,catalog(c,s)
 finally:c.close()
def call(prompt,tokens=1000):
 env();key=os.getenv('OPENROUTER_API_KEY','')
 if not key:raise AIError('OPENROUTER_API_KEY was not found in .env; restart after adding it')
 body=json.dumps({'model':os.getenv('OPENROUTER_MODEL','openai/gpt-4o-mini'),'messages':[{'role':'user','content':prompt}],'temperature':0,'max_tokens':tokens}).encode();req=urllib.request.Request('https://openrouter.ai/api/v1/chat/completions',data=body,headers={'Authorization':f'Bearer {key}','Content-Type':'application/json','HTTP-Referer':'http://localhost:8000','X-Title':'InsightSQL BI'})
 try:
  with urllib.request.urlopen(req,timeout=45) as r:return json.loads(r.read())['choices'][0]['message']['content']
 except urllib.error.HTTPError as e:raise AIError(f'OpenRouter HTTP {e.code}: '+e.read().decode(errors='ignore')[:250])
 except Exception as e:raise AIError(f'Cannot connect to OpenRouter: {e}')
def obj(x):
 m=re.search(r'\{.*\}',re.sub(r'^```(?:json)?|```$','',x.strip()),re.S)
 if not m:raise AIError('AI did not return JSON')
 try:return json.loads(m.group())
 except json.JSONDecodeError:raise AIError('AI returned invalid JSON')
def validate(sql,allowed):
 sql=sql.strip().strip('`').rstrip(';')
 if not re.match(r'^(SELECT|WITH)\b',sql,re.I) or ';' in sql or re.search(r'\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|PRAGMA|VACUUM)\b',sql,re.I):raise AIError('Only one read-only SELECT/CTE is allowed')
 ctes={x.lower() for x in re.findall(r'(?:WITH|,)\s*(\w+)\s+AS\s*\(',sql,re.I)};refs={x.lower() for x in re.findall(r'\b(?:FROM|JOIN)\s+["`\[]?(\w+)',sql,re.I)}-ctes
 if not refs or not refs<={x.lower() for x in allowed}:raise AIError('SQL references an unavailable table')
 return sql
def plan(question,repair=''):
 s,v=context();tables='\n'.join(f"- {t}({', '.join(x['name']+' '+x['type'] for x in cs)})" for t,cs in s.items());values='\n'.join(f'- {k}: {json.dumps(x,ensure_ascii=False)}' for k,x in v.items())
 if not s:raise AIError('Workspace is empty. Import a CSV or load the demo dataset first.')
 prompt=f'''You are a senior e-commerce BI analyst and SQLite expert. Generate one accurate read-only query.
TABLES\n{tables}\nRELATIONSHIPS\n{chr(10).join('- '+x for x in REL)}\nACTUAL CATEGORICAL VALUES\n{values}
Resolve multilingual, abbreviated, misspelled or loose user terms semantically against ACTUAL values (e.g. 日本 means stored country Japan). Never require stored English spelling and never invent absent values. Prefer normalized tables and documented joins for cross-domain questions. Revenue=SUM(order_items.total_sales); Profit=SUM(order_items.profit); daily DAU=count distinct events.customer_id per event_date; monthly DAU for a DAU-vs-MAU chart=AVG of daily distinct-user counts within that month (never SUM); MAU=count distinct events.customer_id per month. Dates are YYYY-MM-DD. Limit grouped output to 50.
Return strict JSON only: {{"sql":"SQLite SELECT/WITH","chart":"auto|bar|line|grouped_bar|kpi|table","title":"user-language title","assumptions":[]}}. {repair}\nQUESTION: {question}'''
 p=obj(call(prompt));p['sql']=validate(p.get('sql',''),set(s));p['chart']=p.get('chart','auto');p['title']=str(p.get('title') or 'AI analysis')[:60];p['assumptions']=p.get('assumptions',[])[:2];return p
def run(sql):
 c=connect()
 try:c.execute('EXPLAIN QUERY PLAN '+sql);cur=c.execute(f'SELECT * FROM ({sql}) LIMIT 500');return [x[0] for x in cur.description or []],[dict(x) for x in cur]
 except sqlite3.Error as e:raise AIError(f'SQL execution failed: {e}')
 finally:c.close()
def chart(cols,rows,requested,title):
 if not rows:return {'type':'table','title':title,'x':None,'series':[]}
 nums=[c for c in cols if any(isinstance(r.get(c),(int,float)) for r in rows)];dims=[c for c in cols if c not in nums]
 if len(rows)==1 and not dims and len(nums)<=4:k='kpi'
 elif not nums or not dims:k='table'
 elif requested in ['bar','line','grouped_bar']:k=requested
 elif len(nums)>1:k='grouped_bar'
 else:k='line' if re.search(r'\d{4}-\d{2}',str(rows[0].get(dims[0],''))) else 'bar'
 return {'type':k,'title':title,'x':dims[0] if dims else None,'series':nums[:4]}
def explain(question,rows):
 if not rows:return ['The query returned no data.','Try a broader date range or fewer filters.']
 p=f'''Use only this query result to answer in the user's language. Question: {question}\nResult: {json.dumps(rows[:40],ensure_ascii=False)}\nReturn strict JSON: {{"insights":["2-3 concise observations with figures"],"next_question":"one follow-up"}}. Do not invent causality.''';x=obj(call(p,500));a=[str(i) for i in x.get('insights',[])][:3];return a+(['Next: '+str(x['next_question'])] if x.get('next_question') else [])
def dashboard():
 env();c=connect()
 try:
  one=lambda x:c.execute(x).fetchone()[0] or 0;qry=lambda x:[dict(r) for r in c.execute(x)];ss=schema(c);has_sales='sales' in ss;ds=c.execute("SELECT value FROM meta WHERE key='source:sales'").fetchone()
  return {'dataset':ds[0] if has_sales and ds else ('No dataset loaded' if not ss else f'{len(ss)} table workspace'),'has_sales':has_sales,'rows':one('SELECT COUNT(*) FROM sales') if has_sales else sum(one(f'SELECT COUNT(*) FROM {q(t)}') for t in ss),'sales':round(one('SELECT SUM(total_sales) FROM sales'),2) if has_sales else 0,'profit':round(one('SELECT SUM(profit) FROM sales'),2) if has_sales else 0,'orders':one('SELECT COUNT(DISTINCT order_id) FROM sales') if has_sales else 0,'customers':one('SELECT COUNT(*) FROM customers') if 'customers' in ss else 0,'month':qry("SELECT substr(order_date,1,7) label,ROUND(SUM(total_sales),2) value FROM sales GROUP BY 1 ORDER BY 1") if has_sales else [],'category':qry('SELECT product_category label,ROUND(SUM(total_sales),2) value FROM sales GROUP BY 1 ORDER BY 2 DESC') if has_sales else [],'tables':[{'name':t,'rows':one(f'SELECT COUNT(*) FROM {q(t)}'),'columns':len(cs)} for t,cs in ss.items()],'relationships':REL if {'customers','products','orders','order_items','events'}<=set(ss) else [],'ai':{'configured':bool(os.getenv('OPENROUTER_API_KEY')),**AI}}
 finally:c.close()
def reset_demo():
 c=connect()
 try:
  tables=[x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'") if x[0] != 'meta']
  for table in tables:c.execute(f'DROP TABLE IF EXISTS {q(table)}')
  c.execute("DELETE FROM meta WHERE key LIKE 'source:%'");c.commit()
  return tables
 finally:c.close()
class Handler(BaseHTTPRequestHandler):
 def sendj(self,x,status=200):
  b=json.dumps(x,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
 def body(self):
  n=int(self.headers.get('Content-Length','0'))
  if n>20000000:raise ValueError('20 MB upload limit')
  return json.loads(self.rfile.read(n) or '{}')
 def do_GET(self):
  if self.path=='/api/dashboard':self.sendj(dashboard());return
  if self.path=='/api/schema':s,v=context();self.sendj({'tables':s,'relationships':REL,'value_fields':list(v)});return
  if self.path=='/api/ai/health':
   try:call('Reply exactly: OK',5);AI.update(state='ready',message='OpenRouter connected')
   except AIError as e:AI.update(state='error',message=str(e))
   self.sendj(AI);return
  p=STATIC/('index.html' if self.path in ['/','/index.html'] else self.path.lstrip('/'))
  if not p.is_file() or STATIC not in p.resolve().parents:self.send_error(404);return
  b=p.read_bytes();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
 def do_POST(self):
  try:
   d=self.body()
   if self.path=='/api/ask':
    question=str(d.get('question','')).strip()
    if not question:raise AIError('Enter an analysis question')
    p=plan(question)
    try:cols,rows=run(p['sql'])
    except AIError as e:p=plan(question,f'Previous SQL failed: {e}. Correct it.');cols,rows=run(p['sql'])
    self.sendj({'question':question,'plan':p,'columns':cols,'rows':rows,'chart_spec':chart(cols,rows,p['chart'],p['title']),'insights':explain(question,rows),'ai':AI});return
   if self.path=='/api/upload':
    filename=str(d.get('filename','uploaded.csv'));table_name=clean(filename)
    if table_name in {'sales','customers','products','orders','order_items','events','meta'}:raise ValueError(f'Table name {table_name} is reserved; rename the CSV file')
    c=connect()
    try:t,n=import_csv(c,str(d.get('csv','')),str(d.get('filename','uploaded.csv')))
    finally:c.close()
    self.sendj({'ok':True,'table':t,'rows':n});return
   if self.path=='/api/import-url':
    url=str(d.get('url','')).strip();table_name=clean(str(d.get('table','api_data')))
    if table_name in {'sales','customers','products','orders','order_items','events','meta'}:raise ValueError(f'Table name {table_name} is reserved')
    text=api_to_csv(url,str(d.get('token','')).strip(),str(d.get('data_path','')).strip(),bool(d.get('allow_private')));c=connect()
    try:t,n=import_csv(c,text,table_name+'.csv',table_name)
    finally:c.close()
    self.sendj({'ok':True,'table':t,'rows':n});return
   if self.path=='/api/reset':
    removed=reset_demo();self.sendj({'ok':True,'removed':removed,'message':'Workspace cleared'});return
   if self.path=='/api/demo':
    count=load_demo();self.sendj({'ok':True,'tables':count,'message':'Demo dataset loaded'});return
   self.sendj({'error':'Not found'},404)
  except (AIError,ValueError,json.JSONDecodeError) as e:self.sendj({'error':str(e)},400)
 def log_message(self,*_):pass
def check():
 load_demo();c=connect();s=schema(c);assert {'sales','customers','products','orders','order_items','events'}<=set(s);assert 'Japan' in catalog(c,s)['customers.country'];n=c.execute('SELECT COUNT(*) FROM orders JOIN customers USING(customer_id) JOIN order_items USING(order_id) JOIN products USING(product_id)').fetchone()[0];assert n==c.execute('SELECT COUNT(*) FROM sales').fetchone()[0];c.close();assert chart(['month','DAU','MAU'],[{'month':'2024-01','DAU':1,'MAU':2}],'auto','x')['type']=='grouped_bar';print(f'self-check passed: {len(s)} tables, {n} joined rows')
def main():
 p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');p.add_argument('--port',type=int,default=8000);a=p.parse_args()
 if a.check:check();return
 connect().close();print(f'InsightSQL BI running on http://localhost:{a.port}');ThreadingHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
if __name__=='__main__':main()
