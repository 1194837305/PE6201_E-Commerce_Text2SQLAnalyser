from __future__ import annotations
import argparse,csv,io,ipaddress,json,os,re,socket,sqlite3,urllib.request,urllib.error,contextvars,tempfile,random
from datetime import date,timedelta
from urllib.parse import parse_qsl,urlencode,urljoin,urlparse,urlunparse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from sqlglot import exp, parse
from sqlglot.errors import ParseError

ROOT=Path(__file__).parent; DB=ROOT/'analytics.sqlite3'; STATIC=ROOT/'static'; SOURCE=ROOT/'global_ecommerce_sales.csv'
AI={'state':'not-tested','message':'AI not tested'}
USAGE_SINK=contextvars.ContextVar('usage_sink',default=None)
REL_CACHE={}
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
   if names[i].endswith('id'):raise ValueError('Identifiers must retain leading zeros')
   [float(x[i]) for x in rows if str(x[i]).strip()];types.append('REAL')
  except ValueError:types.append('TEXT')
 table=table or clean(filename);c.execute(f'DROP TABLE IF EXISTS {q(table)}');c.execute(f'CREATE TABLE {q(table)} ({",".join(q(n)+" "+t for n,t in zip(names,types))})')
 vals=[[float(v) if types[i]=='REAL' and str(v).strip() else v for i,v in enumerate(row)] for row in rows]
 c.executemany(f'INSERT INTO {q(table)} VALUES ({",".join("?" for _ in names)})',vals);c.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',(f'source:{table}',filename));c.commit();REL_CACHE.clear();return table,len(rows)
def validate_api_url(url,allow_private=False):
 parsed=urlparse(url)
 if parsed.scheme not in {'http','https'} or not parsed.hostname:raise ValueError('API URL must use http:// or https://')
 if not allow_private:
  try:
   addresses={x[4][0] for x in socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80))}
  except socket.gaierror as e:raise ValueError(f'Cannot resolve API host: {e}')
  if any(ipaddress.ip_address(x).is_private or ipaddress.ip_address(x).is_loopback or ipaddress.ip_address(x).is_link_local for x in addresses):raise ValueError('Private-network API blocked; enable private network access if this endpoint is trusted')
 return parsed
def api_to_csv(url,token='',data_path='',allow_private=False,pagination='none',page_param='page',size_param='limit',page_size=100,max_pages=20):
 validate_api_url(url,allow_private);page_size=max(1,min(int(page_size),5000));max_pages=max(1,min(int(max_pages),100))
 headers={'Accept':'application/json, text/csv;q=0.9','User-Agent':'InsightSQL/1.0'}
 if token:headers['Authorization']='Bearer '+token
 class SafeRedirect(urllib.request.HTTPRedirectHandler):
  def redirect_request(self,req,fp,code,msg,response_headers,newurl):
   validate_api_url(newurl,allow_private);return super().redirect_request(req,fp,code,msg,response_headers,newurl)
 opener=urllib.request.build_opener(SafeRedirect);rows=[];total_bytes=0;current=url
 def set_query(source,updates):
  parsed=urlparse(source);query=dict(parse_qsl(parsed.query,keep_blank_values=True));query.update({k:str(v) for k,v in updates.items()});return urlunparse(parsed._replace(query=urlencode(query)))
 def extract(data):
  value=data
  if data_path:
   for part in data_path.split('.'):
    if not isinstance(value,dict) or part not in value:raise ValueError(f'JSON path not found: {data_path}')
    value=value[part]
  elif isinstance(value,dict):value=next((value[k] for k in ('data','results','items','records') if isinstance(value.get(k),list)),value)
  if isinstance(value,dict):value=[value]
  if not isinstance(value,list) or not all(isinstance(x,dict) for x in value):raise ValueError('JSON must be an object array, or contain data/results/items/records array')
  return value
 for index in range(max_pages):
  if pagination=='page':current=set_query(url,{page_param:index+1,size_param:page_size})
  elif pagination=='offset':current=set_query(url,{page_param:index*page_size,size_param:page_size})
  validate_api_url(current,allow_private)
  try:
   with opener.open(urllib.request.Request(current,headers=headers),timeout=30) as response:raw=response.read(20_000_001-total_bytes);content_type=response.headers.get_content_type()
  except urllib.error.HTTPError as e:raise ValueError(f'API returned HTTP {e.code} on page {index+1}')
  except (urllib.error.URLError,OSError) as e:raise ValueError(f'API connection failed on page {index+1}: {e}')
  total_bytes+=len(raw)
  if total_bytes>20_000_000:raise ValueError('Combined API response exceeds 20 MB')
  text=raw.decode('utf-8-sig')
  if content_type in {'text/csv','application/csv'} or (not text.lstrip().startswith(('[','{')) and ',' in text.splitlines()[0]):
   if pagination!='none':raise ValueError('Pagination is supported for JSON APIs; use none for CSV responses')
   return text
  try:data=json.loads(text)
  except json.JSONDecodeError:raise ValueError('API response is neither valid CSV nor JSON')
  batch=extract(data);rows.extend(batch)
  if pagination=='none' or not batch:break
  if pagination=='next':
   nxt=data.get('next') or data.get('next_url') if isinstance(data,dict) else None
   if not nxt and isinstance(data,dict) and isinstance(data.get('links'),dict):nxt=data['links'].get('next')
   if not nxt and isinstance(data,dict) and isinstance(data.get('paging'),dict):nxt=data['paging'].get('next')
   if not nxt:break
   current=urljoin(current,str(nxt))
 if not rows:raise ValueError('API returned no rows')
 fields=list(dict.fromkeys(k for row in rows for k in row))
 out=io.StringIO();writer=csv.DictWriter(out,fieldnames=fields);writer.writeheader()
 for row in rows:writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})
 return out.getvalue()
def normalize(c):
 rows=[{k.lower():v for k,v in dict(x).items()} for x in c.execute('SELECT * FROM sales ORDER BY order_date,order_id')];cs={};ps={};out={x:[] for x in ['customers','products','orders','order_items']}
 for i,r in enumerate(rows,1):
  ck=(r['customer_name'],r['customer_segment'],r['country'],r['region']);pk=(r['product_name'],r['product_category'])
  if ck not in cs:cs[ck]=f'C{len(cs)+1:05d}';out['customers'].append((cs[ck],*ck))
  if pk not in ps:ps[pk]=f'P{len(ps)+1:05d}';out['products'].append((ps[pk],*pk,r['unit_price']))
  oid=str(r['order_id']);out['orders'].append((oid,r['order_date'],cs[ck],r['payment_method'],r['shipping_cost']));out['order_items'].append((f'I{i:06d}',oid,ps[pk],r['quantity'],r['unit_price'],r['discount_percent'],r['total_sales'],r['profit']))
 ddl={'customers':'customer_id TEXT PRIMARY KEY,customer_name TEXT,customer_segment TEXT,country TEXT,region TEXT','products':'product_id TEXT PRIMARY KEY,product_name TEXT,product_category TEXT,standard_unit_price REAL','orders':'order_id TEXT PRIMARY KEY,order_date TEXT,customer_id TEXT,payment_method TEXT,shipping_cost REAL','order_items':'order_item_id TEXT PRIMARY KEY,order_id TEXT,product_id TEXT,quantity REAL,unit_price REAL,discount_percent REAL,total_sales REAL,profit REAL'}
 for t,d in ddl.items():c.execute(f'DROP TABLE IF EXISTS {t}');c.execute(f'CREATE TABLE {t} ({d})');c.executemany(f'INSERT INTO {t} VALUES ({",".join("?" for _ in out[t][0])})',out[t])
 c.commit()
def simulate_events(c):
 """Independent, deterministic demo activity; never inferred from purchases."""
 customers=[r[0] for r in c.execute('SELECT customer_id FROM customers ORDER BY customer_id')]
 bounds=c.execute('SELECT MIN(order_date),MAX(order_date) FROM orders').fetchone()
 start=date.fromisoformat(bounds[0]);days=(date.fromisoformat(bounds[1])-start).days+1
 rng=random.Random(6201)
 c.execute('CREATE TABLE user_events(event_id TEXT PRIMARY KEY,user_id TEXT,event_time TEXT,event_type TEXT)')
 rows=[];kinds=('app_open','page_view','search','add_to_cart')
 for user_id in customers:
  for _ in range(8):
   day=start+timedelta(days=rng.randrange(days))
   rows.append((f'E{len(rows)+1:06d}',user_id,f'{day.isoformat()} {rng.randrange(24):02d}:{rng.randrange(60):02d}:00',rng.choice(kinds)))
 c.executemany('INSERT INTO user_events VALUES (?,?,?,?)',rows)
 c.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',('source:user_events','SIMULATED independent activity events'))
 c.commit()
def connect():
 c=sqlite3.connect(DB,timeout=20);c.row_factory=sqlite3.Row;c.execute('PRAGMA journal_mode=WAL');c.execute('CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT)')
 return c
def load_demo():
 c=connect()
 try:
  if schema(c):raise ValueError('Clear the workspace before loading the demo; existing tables would be replaced')
  for table in ['events','order_items','orders','products','customers','sales']:c.execute(f'DROP TABLE IF EXISTS {table}')
  import_csv(c,SOURCE.read_text(encoding='utf-8-sig'),SOURCE.name,'sales');normalize(c);simulate_events(c);return 6
 finally:c.close()
def schema(c):
 ts=[x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'meta' ORDER BY name")];return {t:[{'name':x[1],'type':x[2] or 'TEXT','pk':bool(x[5])} for x in c.execute(f'PRAGMA table_info({q(t)})')] for t in ts}
def unique_table(c,base):
 if base=='meta':raise ValueError('Table name meta is reserved')
 existing=set(schema(c));candidate=base;index=2
 while candidate in existing:
  tail=f'_{index}';candidate=base[:50-len(tail)]+tail;index+=1
 return candidate
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
 body=json.dumps({'model':os.getenv('OPENROUTER_MODEL','openai/gpt-4o-mini'),'messages':[{'role':'user','content':prompt}],'temperature':0,'max_tokens':tokens,'usage':{'include':True}}).encode();req=urllib.request.Request('https://openrouter.ai/api/v1/chat/completions',data=body,headers={'Authorization':f'Bearer {key}','Content-Type':'application/json','HTTP-Referer':'http://localhost:8000','X-Title':'InsightSQL BI'})
 try:
  with urllib.request.urlopen(req,timeout=45) as r:data=json.loads(r.read())
  sink=USAGE_SINK.get()
  if sink is not None:sink.append(data.get('usage') or {})
  return data['choices'][0]['message']['content']
 except urllib.error.HTTPError as e:raise AIError(f'OpenRouter HTTP {e.code}: '+e.read().decode(errors='ignore')[:250])
 except Exception as e:raise AIError(f'Cannot connect to OpenRouter: {e}')
def obj(x):
 m=re.search(r'\{.*\}',re.sub(r'^```(?:json)?|```$','',x.strip()),re.S)
 if not m:raise AIError('AI did not return JSON')
 try:return json.loads(m.group())
 except json.JSONDecodeError:raise AIError('AI returned invalid JSON')
def relationship_evidence(c,s):
 """Candidate keys from current data; never a baked-in demo join graph."""
 evidence=[];ids=[(t,x['name']) for t,cols in s.items() for x in cols if x['name'].lower().endswith('id')]
 for i,(a,ac) in enumerate(ids):
  for b,bc in ids[i+1:]:
   if a==b:continue
   av={r[0] for r in c.execute(f'SELECT DISTINCT {q(ac)} FROM {q(a)} WHERE {q(ac)} IS NOT NULL LIMIT 2001')};bv={r[0] for r in c.execute(f'SELECT DISTINCT {q(bc)} FROM {q(b)} WHERE {q(bc)} IS NOT NULL LIMIT 2001')}
   if not av or not bv or len(av)>2000 or len(bv)>2000:continue
   overlap=len(av&bv)/min(len(av),len(bv))
   if overlap<.8:continue
   an=c.execute(f'SELECT COUNT(*),COUNT(DISTINCT {q(ac)}) FROM {q(a)}').fetchone();bn=c.execute(f'SELECT COUNT(*),COUNT(DISTINCT {q(bc)}) FROM {q(b)}').fetchone()
   au=an[0]==an[1];bu=bn[0]==bn[1]
   if not (au or bu):continue
   evidence.append({'left':f'{a}.{ac}','right':f'{b}.{bc}','overlap':round(overlap,3),'left_unique':au,'right_unique':bu,'left_rows':an[0],'right_rows':bn[0]})
 return sorted(evidence,key=lambda x:(x['left'].split('.')[1]!=x['right'].split('.')[1],-x['overlap']))[:35]
def discover_relationships(c,s):
 evidence=relationship_evidence(c,s)
 # Re-evaluate when a table schema or observed key distribution changes.
 signature=json.dumps({'schema':s,'evidence':evidence},sort_keys=True,ensure_ascii=False)
 if signature in REL_CACHE:return (*REL_CACHE[signature],evidence)
 prompt='''You are a database schema analyst. Describe each CURRENT field's likely role and meaning from its name/type, without inventing business definitions. For candidate keys, select only pairs semantically plausible from table/field names AND statistically supported by overlap/uniqueness. Shared values alone are insufficient. Return strict JSON {"relations":[{"left":"table.column","right":"table.column"}],"fields":{"table.column":"brief inferred description and role"}}. Use only listed fields and candidates; an empty list/object is valid when uncertain.\nSCHEMA\n'''+json.dumps(s,ensure_ascii=False)+'\nCANDIDATES\n'+json.dumps(evidence,ensure_ascii=False)
 analysis=obj(call(prompt,1200));selected=analysis.get('relations',[])
 valid={(x['left'],x['right']) for x in evidence};valid|={(b,a) for a,b in valid}
 relations=[]
 for item in selected if isinstance(selected,list) else []:
  pair=(str(item.get('left','')),str(item.get('right',''))) if isinstance(item,dict) else ('','')
  if pair in valid and pair not in relations:relations.append(pair)
 fields=analysis.get('fields',{});actual={f'{t}.{col["name"]}' for t,cols in s.items() for col in cols}
 fields={k:str(v)[:120] for k,v in fields.items() if k in actual} if isinstance(fields,dict) else {}
 REL_CACHE.clear();REL_CACHE[signature]=(relations,fields)
 return relations,fields,evidence
def validate(sql,allowed,relations=None):
 sql=str(sql).strip().strip('`').rstrip(';')
 if len(sql)>20000:raise AIError('SQL is too long')
 try:statements=parse(sql,read='sqlite')
 except ParseError as e:raise AIError(f'SQL parse failed: {e}')
 if len(statements)!=1 or not isinstance(statements[0],exp.Query):raise AIError('Only one read-only SELECT/CTE is allowed')
 tree=statements[0]
 if any(isinstance(n,(exp.Insert,exp.Update,exp.Delete,exp.Create,exp.Drop,exp.Command)) for n in tree.walk()):raise AIError('Only read-only SQL is allowed')
 for between in tree.find_all(exp.Between):
  field=between.this
  upper=between.args.get('high')
  if isinstance(field,exp.Column) and (field.name.endswith('_time') or field.name.endswith('_at') or 'timestamp' in field.name) and isinstance(upper,exp.Literal) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(upper.this)):
   raise AIError('Date-only BETWEEN upper bound excludes most events on the final day; use >= start AND < next-period start')
 ctes={n.alias_or_name.lower() for n in tree.find_all(exp.CTE)}
 physical={n.name for n in tree.find_all(exp.Table) if n.name.lower() not in ctes}
 if not physical or not physical<=set(allowed):raise AIError('SQL references an unavailable table')
 if len(physical)==1 and tree.find(exp.Join):raise AIError('Self-joins require review')
 if len(physical)>1:
  if not isinstance(tree,exp.Select) or tree.find(exp.CTE) or tree.find(exp.Subquery):raise AIError('Complex multi-table query needs review; use direct JOINs')
  origin=tree.args.get('from_')
  if not origin or not isinstance(origin.this,exp.Table):raise AIError('Multi-table query needs direct FROM')
  aliases={origin.this.alias_or_name:origin.this.name};joined={origin.this.name}
  approved={frozenset((a,b)) for a,b in (relations or [])}
  for join in tree.args.get('joins') or []:
   if not isinstance(join.this,exp.Table):raise AIError('JOIN must reference a table directly')
   right=join.this.name;aliases[join.this.alias_or_name]=right
   pairs=[];on=join.args.get('on')
   if on:
    stack=[on]
    while stack:
     n=stack.pop()
     if isinstance(n,exp.And):stack.extend([n.left,n.right])
     elif isinstance(n,exp.EQ) and isinstance(n.left,exp.Column) and isinstance(n.right,exp.Column):pairs.append((n.left,n.right))
     else:raise AIError('JOIN predicates must use discovered key equalities')
   for col in join.args.get('using') or []:
    pairs.extend((exp.column(col.name,table=alias),exp.column(col.name,table=join.this.alias_or_name)) for alias,table in aliases.items() if table in joined)
   verified=False
   for a,b in pairs:
    at=aliases.get(a.table);bt=aliases.get(b.table)
    if frozenset((f'{at}.{a.name}',f'{bt}.{b.name}')) not in approved:raise AIError('JOIN key was not supported by schema discovery')
    if right in {at,bt} and ({at,bt}&joined):verified=True
   if not verified:raise AIError('Cartesian or unsupported JOIN blocked')
   joined.add(right)
  if joined!=physical:raise AIError('Every table needs a supported JOIN')
 return sql
def plan(question,repair=''):
 s,v=context();tables='\n'.join(f"- {t}({', '.join(x['name']+' '+x['type'] for x in cs)})" for t,cs in s.items());values='\n'.join(f'- {k}: {json.dumps(x,ensure_ascii=False)}' for k,x in v.items())
 if not s:raise AIError('Workspace is empty. Import a CSV or load the demo dataset first.')
 c=connect()
 try:
  relations,field_notes,evidence=discover_relationships(c,s)
  date_ranges=[]
  for t,cols in s.items():
   for col in cols:
    if col['type'].upper()=='TEXT' and ('date' in col['name'].lower() or col['name'].lower().endswith('_at')):
     low,high=c.execute(f'SELECT MIN({q(col["name"])}),MAX({q(col["name"])}) FROM {q(t)}').fetchone()
     if low is not None:date_ranges.append(f'- {t}.{col["name"]}: {low} to {high}')
 finally:c.close()
 prompt=f'''You are an e-commerce data analyst and SQLite expert. Generate one accurate read-only query, or refuse when the available schema cannot answer the question. This is an unfamiliar database: do not assume its metric definitions or join keys.
TABLES\n{tables}\nINFERRED FIELD DESCRIPTIONS (hints, not verified metric definitions)\n{json.dumps(field_notes,ensure_ascii=False)}\nRELATIONSHIPS DISCOVERED FROM CURRENT DATA (use only these for multi-table joins)\n{chr(10).join('- '+a+' = '+b for a,b in relations) or '(none supported)'}\nACTUAL CATEGORICAL VALUES\n{values}\nOBSERVED DATE RANGES\n{chr(10).join(date_ranges)}
Resolve translated or approximate user terms against ACTUAL values, without inventing absent values. Derive metrics from available column names and types; ALWAYS state the chosen measure, aggregation and grain in assumptions (e.g. total units vs sales amount). For DAU and MAU, require an activity/event date and user identifier from an event table; do not substitute orders or order-derived activity proxies. For timestamp-like text, filter date periods with an inclusive start and exclusive next-period boundary; BETWEEN 'YYYY-MM-01' AND 'YYYY-MM-31' misses events on the last day. For sales or profit, use an explicit amount/profit column and explain the chosen field. If several plausible definitions exist, refuse or state the needed clarification. Limit grouped output to 50.
If a required concept has no table/column (for example ad spend, refunds, or inventory), return {{"cannot_answer":true,"reason":"brief missing-data reason"}} and do not invent a proxy. Never infer causal claims from correlations.
Return strict JSON only: {{"sql":"SQLite SELECT/WITH","chart":"auto|bar|line|grouped_bar|kpi|table","title":"user-language title","assumptions":[]}} or the cannot_answer object. {repair}\nQUESTION: {question}'''
 p=obj(call(prompt))
 if p.get('cannot_answer'):return {'cannot_answer':True,'reason':str(p.get('reason') or 'Required data is unavailable')[:300]}
 try:p['sql']=validate(p.get('sql',''),set(s),relations)
 except AIError as e:
  if not repair:return plan(question,f'Previous SQL failed validation: {e}. Use only listed supported joins, or refuse.')
  raise
 p['chart']=p.get('chart','auto');p['title']=str(p.get('title') or 'AI analysis')[:60];p['assumptions']=[str(x)[:220] for x in p.get('assumptions',[])[:2]] if isinstance(p.get('assumptions'),list) else [];p['available_relationships']=[a+' = '+b for a,b in relations];return p
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
def choose_chart(question,cols,rows,sql,title):
 fallback=chart(cols,rows,'auto',title)
 if fallback['type'] in {'table','kpi'}:return fallback
 info=[{'name':x,'numeric':all(r.get(x) is None or isinstance(r.get(x),(int,float)) for r in rows)} for x in cols]
 prompt='''Choose a truthful chart for the ACTUAL query result, considering the question, SQL aliases, dimensions, measures, and sample rows. Prefer line for ordered time series, grouped_bar for comparing multiple measures, bar for categories, table if charting would mislead. Return JSON only: {"type":"bar|line|grouped_bar|table","x":"existing column","series":["existing numeric column"]}. Never invent fields.\nQUESTION\n'''+question+'\nSQL\n'+sql+'\nCOLUMNS\n'+json.dumps(info,ensure_ascii=False)+'\nROWS\n'+json.dumps(rows[:8],ensure_ascii=False)
 try:choice=obj(call(prompt,350))
 except AIError:return fallback
 kind=choice.get('type');x=choice.get('x');series=choice.get('series')
 numeric={item['name'] for item in info if item['numeric']};dimensions=set(cols)-numeric
 if kind=='table':return {**fallback,'type':'table','x':None,'series':[]}
 if kind not in {'bar','line','grouped_bar'} or x not in dimensions or not isinstance(series,list) or not series or len(series)>4 or any(v not in numeric for v in series):return fallback
 return {'type':kind,'title':title,'x':x,'series':series}
def explain(question,rows):
 if not rows:return ['The query returned no data.']
 cols=list(rows[0]);nums=[x for x in cols if all(r.get(x) is None or isinstance(r.get(x),(int,float)) for r in rows) and any(isinstance(r.get(x),(int,float)) for r in rows)];dims=[x for x in cols if x not in nums]
 label=dims[0] if dims else None;zh=bool(re.search(r'[\u4e00-\u9fff]',question))
 fmt=lambda v:f'{v:,.2f}'.rstrip('0').rstrip('.')
 facts=[];metric_starts=[]
 if not nums:return [f'返回 {len(rows)} 行数据；请查看下方原始结果。' if zh else f'{len(rows)} rows returned; inspect the raw result below.']
 for metric in nums[:3]:
  metric_starts.append(len(facts))
  valid=[r for r in rows if isinstance(r.get(metric),(int,float))]
  hi=max(valid,key=lambda r:r[metric]);lo=min(valid,key=lambda r:r[metric])
  place=lambda r:f'（{label}={r[label]}）' if zh and label else (f' ({label}={r[label]})' if label else '')
  facts.append((f'返回结果中，{metric} 最高为 {fmt(hi[metric])}{place(hi)}。' if zh else f'Among returned rows, {metric} is highest at {fmt(hi[metric])}{place(hi)}.'))
  if len(valid)>1:facts.append((f'返回结果中，{metric} 最低为 {fmt(lo[metric])}{place(lo)}。' if zh else f'Among returned rows, {metric} is lowest at {fmt(lo[metric])}{place(lo)}.'))
  if label and len(valid)>1 and re.fullmatch(r'\d{4}(?:-\d{2}){0,2}',str(valid[0][label] or '')):
   first,last=valid[0],valid[-1]
   facts.append((f'{metric} 在 {first[label]} 为 {fmt(first[metric])}，在 {last[label]} 为 {fmt(last[metric])}。' if zh else f'{metric} was {fmt(first[metric])} in {first[label]} and {fmt(last[metric])} in {last[label]}.'))
 if len(facts)<=3:return facts
 prompt='''Select up to 3 numbered, relevant facts for the user's question. These facts were computed from executed SQL rows. Return JSON only: {"fact_ids":[0,1]}. Do not write or change any facts, numbers, ranking, units or causal claims.\nQUESTION\n'''+question+'\nFACTS\n'+json.dumps(dict(enumerate(facts)),ensure_ascii=False)
 try:chosen=obj(call(prompt,150)).get('fact_ids',[])
 except AIError:chosen=[]
 indices=[i for i in chosen if isinstance(i,int) and 0<=i<len(facts)] if isinstance(chosen,list) else []
 selected=list(dict.fromkeys((metric_starts if len(nums)>1 else [])+indices))
 return [facts[i] for i in selected][:3] or [facts[i] for i in metric_starts[:3]] or facts[:3]
def dashboard():
 env();c=connect()
 try:
  one=lambda x:c.execute(x).fetchone()[0] or 0;qry=lambda x:[dict(r) for r in c.execute(x)];ss=schema(c);has_sales={'order_date','total_sales','profit','order_id','product_category'}<={x['name'] for x in ss.get('sales',[])};ds=c.execute("SELECT value FROM meta WHERE key='source:sales'").fetchone()
  return {'dataset':ds[0] if has_sales and ds else ('No dataset loaded' if not ss else f'{len(ss)} table workspace'),'has_sales':has_sales,'rows':one('SELECT COUNT(*) FROM sales') if has_sales else sum(one(f'SELECT COUNT(*) FROM {q(t)}') for t in ss),'sales':round(one('SELECT SUM(total_sales) FROM sales'),2) if has_sales else 0,'profit':round(one('SELECT SUM(profit) FROM sales'),2) if has_sales else 0,'orders':one('SELECT COUNT(DISTINCT order_id) FROM sales') if has_sales else 0,'customers':one('SELECT COUNT(*) FROM customers') if 'customers' in ss else 0,'month':qry("SELECT substr(order_date,1,7) label,ROUND(SUM(total_sales),2) value FROM sales GROUP BY 1 ORDER BY 1") if has_sales else [],'category':qry('SELECT product_category label,ROUND(SUM(total_sales),2) value FROM sales GROUP BY 1 ORDER BY 2 DESC') if has_sales else [],'tables':[{'name':t,'rows':one(f'SELECT COUNT(*) FROM {q(t)}'),'columns':len(cs)} for t,cs in ss.items()],'relationships':[], 'ai':{'configured':bool(os.getenv('OPENROUTER_API_KEY')),**AI}}
 finally:c.close()
def reset_demo():
 c=connect()
 try:
  tables=[x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'") if x[0] != 'meta']
  for table in tables:c.execute(f'DROP TABLE IF EXISTS {q(table)}')
  c.execute("DELETE FROM meta WHERE key LIKE 'source:%'");c.commit();REL_CACHE.clear()
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
  if self.path=='/api/schema':s,v=context();self.sendj({'tables':s,'relationships':[], 'value_fields':list(v)});return
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
    if p.get('cannot_answer'):
     self.sendj({'question':question,'plan':p,'columns':[],'rows':[],'chart_spec':None,'insights':[p['reason']],'ai':AI});return
    try:cols,rows=run(p['sql'])
    except AIError as e:
     p=plan(question,f'Previous SQL failed: {e}. Correct it or refuse.')
     if p.get('cannot_answer'):
      self.sendj({'question':question,'plan':p,'columns':[],'rows':[],'chart_spec':None,'insights':[p['reason']],'ai':AI});return
     cols,rows=run(p['sql'])
    self.sendj({'question':question,'plan':p,'columns':cols,'rows':rows,'chart_spec':choose_chart(question,cols,rows,p['sql'],p['title']),'insights':['Metric definition: '+x for x in p['assumptions']]+explain(question,rows),'ai':AI});return
   if self.path=='/api/upload':
    filename=str(d.get('filename','uploaded.csv'));table_name=clean(filename)
    c=connect()
    try:t,n=import_csv(c,str(d.get('csv','')),filename,unique_table(c,table_name))
    finally:c.close()
    self.sendj({'ok':True,'table':t,'rows':n});return
   if self.path=='/api/import-url':
    url=str(d.get('url','')).strip();table_name=clean(str(d.get('table','api_data')))
    text=api_to_csv(url,str(d.get('token','')).strip(),str(d.get('data_path','')).strip(),bool(d.get('allow_private')),str(d.get('pagination','none')),str(d.get('page_param','page')),str(d.get('size_param','limit')),d.get('page_size',100),d.get('max_pages',20));c=connect()
    try:t,n=import_csv(c,text,table_name+'.csv',unique_table(c,table_name))
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
 global DB,call
 original=DB;real_call=call
 with tempfile.TemporaryDirectory(prefix='pe6201_check_') as temp:
  DB=Path(temp)/'check.sqlite3'
  try:
   load_demo();c=connect()
   try:
    s=schema(c);assert {'sales','customers','products','orders','order_items','user_events'}<=set(s);assert 'Japan' in catalog(c,s)['customers.country'];n=c.execute('SELECT COUNT(*) FROM orders JOIN customers USING(customer_id) JOIN order_items USING(order_id) JOIN products USING(product_id)').fetchone()[0];assert n==c.execute('SELECT COUNT(*) FROM sales').fetchone()[0]
    evidence=relationship_evidence(c,s);assert any({x['left'],x['right']}=={'orders.order_id','order_items.order_id'} for x in evidence)
    assert any({x['left'],x['right']}=={'user_events.user_id','customers.customer_id'} for x in evidence)
    assert c.execute('SELECT COUNT(DISTINCT e.user_id) FROM user_events e JOIN customers c ON e.user_id=c.customer_id').fetchone()[0]==c.execute('SELECT COUNT(*) FROM customers').fetchone()[0]
    assert c.execute("SELECT COUNT(DISTINCT user_id) FROM user_events WHERE substr(event_time,1,7)='2024-01'").fetchone()[0]>0
    joined_sql='SELECT COUNT(DISTINCT e.user_id) AS active_customers FROM user_events e JOIN customers c ON e.user_id=c.customer_id'
    assert validate(joined_sql,s,[('user_events.user_id','customers.customer_id')])==joined_sql
    try:validate("SELECT COUNT(*) FROM user_events WHERE event_time BETWEEN '2024-01-01' AND '2024-01-31'",s);raise AssertionError('Unsafe timestamp bound accepted')
    except AIError:pass
   finally:c.close()
   def offline_model(prompt,tokens=1000):
    if prompt.startswith('You are a database schema analyst'):return json.dumps({'relations':[{'left':'order_items.order_id','right':'orders.order_id'}]})
    if prompt.startswith('Choose a truthful chart'):return json.dumps({'type':'bar','x':'order_date','series':['orders']})
    return json.dumps({'sql':'SELECT orders.order_date, COUNT(*) AS orders FROM orders JOIN order_items USING(order_id) GROUP BY orders.order_date LIMIT 5','title':'Orders by date','assumptions':[]})
   call=offline_model
   p=plan('Orders by date');cols,rows=run(p['sql']);assert rows and choose_chart('Orders by date',cols,rows,p['sql'],p['title'])['type']=='bar'
   facts=explain('Compare monthly sales',[{'month':'2025-05','sales':17621.8},{'month':'2025-06','sales':18068.09}]);assert '2025-06' in facts[0] and '18,068.09' in facts[0]
   c=connect()
   try:
    for filename in ('orders.csv','orders.csv'):
     import_csv(c,'customer_id,amount\n001,10\n002,20\n',filename,unique_table(c,clean(filename)))
    assert {'orders','orders_2','orders_3'}<=set(schema(c))
    assert c.execute('SELECT customer_id FROM orders_2 ORDER BY customer_id').fetchone()[0]=='001'
   finally:c.close()
   try:validate('SELECT * FROM orders JOIN order_items ON 1=1',s,[('order_items.order_id','orders.order_id')]);raise AssertionError('Cartesian JOIN accepted')
   except AIError:pass
   assert chart(['month','DAU','MAU'],[{'month':'2024-01','DAU':1,'MAU':2}],'auto','x')['type']=='grouped_bar';print(f'self-check passed: {len(s)} demo tables, {n} joined rows, multi-import/discovery/SQL/chart stages')
  finally:DB=original;call=real_call;REL_CACHE.clear()
def main():
 p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');p.add_argument('--port',type=int,default=8000);a=p.parse_args()
 if a.check:check();return
 connect().close();print(f'InsightSQL BI running on http://localhost:{a.port}');ThreadingHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
if __name__=='__main__':main()
