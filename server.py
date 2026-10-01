from __future__ import annotations
import argparse,csv,io,ipaddress,json,os,re,socket,sqlite3,ssl,urllib.request,urllib.error,contextvars,tempfile,random
from datetime import date,timedelta
from urllib.parse import parse_qsl,urlencode,urljoin,urlparse,urlunparse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from sqlglot import exp, parse
from sqlglot.errors import ParseError
import certifi

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
 ddl={'customers':'customer_id TEXT PRIMARY KEY,customer_name TEXT,customer_segment TEXT,country TEXT,region TEXT','products':'product_id TEXT PRIMARY KEY,product_name TEXT,product_category TEXT,standard_unit_price REAL','orders':'order_id TEXT PRIMARY KEY,order_date TEXT,customer_id TEXT REFERENCES customers(customer_id),payment_method TEXT,shipping_cost REAL','order_items':'order_item_id TEXT PRIMARY KEY,order_id TEXT REFERENCES orders(order_id),product_id TEXT REFERENCES products(product_id),quantity REAL,unit_price REAL,discount_percent REAL,total_sales REAL,profit REAL'}
 for t,d in ddl.items():c.execute(f'DROP TABLE IF EXISTS {t}');c.execute(f'CREATE TABLE {t} ({d})');c.executemany(f'INSERT INTO {t} VALUES ({",".join("?" for _ in out[t][0])})',out[t])
 c.commit()
def simulate_events(c):
 """Independent, deterministic demo activity; never inferred from purchases."""
 customers=[r[0] for r in c.execute('SELECT customer_id FROM customers ORDER BY customer_id')]
 bounds=c.execute('SELECT MIN(order_date),MAX(order_date) FROM orders').fetchone()
 start=date.fromisoformat(bounds[0]);days=(date.fromisoformat(bounds[1])-start).days+1
 rng=random.Random(6201)
 c.execute('CREATE TABLE user_events(event_id TEXT PRIMARY KEY,user_id TEXT REFERENCES customers(customer_id),event_time TEXT,event_type TEXT)')
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
  ssl_context=ssl.create_default_context(cafile=certifi.where())
  with urllib.request.urlopen(req,timeout=45,context=ssl_context) as r:data=json.loads(r.read())
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
def declared_relationships(c,s):
 """Read authoritative foreign-key metadata instead of asking a model to rediscover it."""
 actual={f'{t}.{col["name"]}' for t,cols in s.items() for col in cols};relations=[]
 for child in s:
  for row in c.execute(f'PRAGMA foreign_key_list({q(child)})'):
   parent,child_col,parent_col=row[2],row[3],row[4]
   pair=(f'{child}.{child_col}',f'{parent}.{parent_col}')
   if pair[0] in actual and pair[1] in actual and pair not in relations:relations.append(pair)
 return relations
def discover_relationships(c,s):
 evidence=relationship_evidence(c,s)
 declared=declared_relationships(c,s)
 automatic=[(item['left'],item['right']) for item in evidence if item['left'].split('.')[1]==item['right'].split('.')[1] and item['overlap']==1 and (item['left_unique'] or item['right_unique'])]
 # Re-evaluate when a table schema or observed key distribution changes.
 signature=json.dumps({'schema':s,'declared':declared,'automatic':automatic,'evidence':evidence},sort_keys=True,ensure_ascii=False)
 if signature in REL_CACHE:return (*REL_CACHE[signature],evidence)
 prompt='''You are a database schema analyst. Describe each CURRENT field's likely role and meaning from its name/type, without inventing business definitions. DECLARED FOREIGN KEYS and exact-name, full-overlap relationships are authoritative and already approved; do not repeat or reject them. For remaining statistical candidates, select only pairs semantically plausible from table/field names AND supported by overlap/uniqueness. Shared values alone are insufficient. Return strict JSON {"relations":[{"left":"table.column","right":"table.column"}],"fields":{"table.column":"brief inferred description and role"}}. Use only listed fields and statistical candidates; an empty list/object is valid when uncertain.\nSCHEMA\n'''+json.dumps(s,ensure_ascii=False)+'\nDECLARED FOREIGN KEYS\n'+json.dumps(declared,ensure_ascii=False)+'\nAUTOMATIC EXACT-NAME RELATIONSHIPS\n'+json.dumps(automatic,ensure_ascii=False)+'\nSTATISTICAL CANDIDATES\n'+json.dumps(evidence,ensure_ascii=False)
 analysis=obj(call(prompt,1200));selected=analysis.get('relations',[])
 valid={(x['left'],x['right']) for x in evidence};valid|={(b,a) for a,b in valid}
 relations=list(dict.fromkeys(declared+automatic))
 for item in selected if isinstance(selected,list) else []:
  pair=(str(item.get('left','')),str(item.get('right',''))) if isinstance(item,dict) else ('','')
  if pair in valid and pair not in relations:relations.append(pair)
 fields=analysis.get('fields',{});actual={f'{t}.{col["name"]}' for t,cols in s.items() for col in cols}
 fields={k:str(v)[:120] for k,v in fields.items() if k in actual} if isinstance(fields,dict) else {}
 REL_CACHE.clear();REL_CACHE[signature]=(relations,fields)
 return relations,fields,evidence
def temporal_column(c,table,column):
 name=column['name'].lower();declared=(column.get('type') or '').upper()
 if re.search(r'(?:^|_)(?:date|time|timestamp|datetime)(?:$|_)|_at$',name):return True
 if any(token in declared for token in ('DATE','TIME')):return True
 samples=[str(x[0]).strip() for x in c.execute(f'SELECT {q(column["name"])} FROM {q(table)} WHERE {q(column["name"])} IS NOT NULL AND {q(column["name"])}<>\'\' LIMIT 20')]
 return bool(samples) and sum(bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?',value)) for value in samples)>=max(1,len(samples)*4//5)
def validate(sql,allowed,relations=None):
 sql=str(sql).strip().strip('`').rstrip(';')
 if len(sql)>20000:raise AIError('SQL is too long')
 try:statements=parse(sql,read='sqlite')
 except ParseError as e:raise AIError(f'SQL parse failed: {e}')
 if len(statements)!=1 or not isinstance(statements[0],exp.Query):raise AIError('Only one read-only SELECT/CTE is allowed')
 tree=statements[0]
 # Analytics ratios use real division; explicit outer CAST(... AS INTEGER)
 # remains available when a user requests a truncated integer.
 for division in tree.find_all(exp.Div):
  if not isinstance(division.this,exp.Cast):
   division.set('this',exp.Cast(this=division.this.copy(),to=exp.DataType.build('REAL')))
 if any(isinstance(n,(exp.Insert,exp.Update,exp.Delete,exp.Create,exp.Drop,exp.Command)) for n in tree.walk()):raise AIError('Only read-only SQL is allowed')
 ctes={n.alias_or_name.lower() for n in tree.find_all(exp.CTE)}
 physical={n.name for n in tree.find_all(exp.Table) if n.name.lower() not in ctes}
 if not physical or not physical<=set(allowed):raise AIError('SQL references an unavailable table')
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
    if frozenset((f'{at}.{a.name}',f'{bt}.{b.name}')) not in approved:raise AIError(f'JOIN key was not supported by schema discovery: {at}.{a.name} = {bt}.{b.name}')
    if right in {at,bt} and ({at,bt}&joined):verified=True
   if not verified:raise AIError('Cartesian or unsupported JOIN blocked')
   joined.add(right)
  if joined!=physical:raise AIError('Every table needs a supported JOIN')
 return tree.sql(dialect='sqlite')
def plan(question,repair=''):
 from metric_knowledge import retrieve
 metric_cards=retrieve(question,call,obj)
 if repair and 'Execution error:' in repair:
  s,_=context()
  c=connect()
  try:relations,_,_=discover_relationships(c,s)
  finally:c.close()
  fixed=obj(call('Repair this SQLite query using the exact error and schema. Preserve requested metrics and filters. Check each CTE output column against every consumer. Return JSON {"sql":"...","title":"Analysis","assumptions":[]}.\nQUESTION\n'+question+'\nSCHEMA\n'+json.dumps(s)+'\nRELATIONS\n'+json.dumps(relations)+'\nMETRICS\n'+json.dumps(metric_cards)+'\n'+repair,1800))
  fixed['sql']=validate(fixed.get('sql',''),set(s),relations)
  fixed.setdefault('title','Analysis');fixed.setdefault('assumptions',[])
  fixed['metric_context']=metric_cards
  return fixed
 s,v=context();values='\n'.join(f'- {k}: {json.dumps(x,ensure_ascii=False)}' for k,x in v.items())
 if not s:raise AIError('Workspace is empty. Import a CSV or load the demo dataset first.')
 c=connect()
 try:
  relations,field_notes,evidence=discover_relationships(c,s)
  date_ranges=[];temporal_profiles={}
  for t,cols in s.items():
   for col in cols:
    if temporal_column(c,t,col):
     low,high=c.execute(f'SELECT MIN({q(col["name"])}),MAX({q(col["name"])}) FROM {q(t)}').fetchone()
     if low is not None:
      date_ranges.append(f'- {t}.{col["name"]}: {low} to {high}')
      temporal_profiles[(t,col['name'])]=f'temporal, observed {low} to {high}'
 finally:c.close()
 profile_lines='\n'.join(f"- {t}({', '.join(x['name']+' '+x['type']+(' PRIMARY_KEY' if x['pk'] else '')+(' ['+temporal_profiles[(t,x['name'])]+']' if (t,x['name']) in temporal_profiles else '') for x in cs)})" for t,cs in s.items())
 scope_prompt='''Select the smallest sufficient set of tables for answering the question. Prefer one table when it already contains every required measure, filter, dimension and time field. Choose multiple tables only when necessary and only when the listed approved relationships connect them. Return strict JSON {"tables":["existing_table"]}. Return an empty list if no table set can answer.\nTABLES\n'''+profile_lines+'\nAPPROVED RELATIONSHIPS\n'+json.dumps(relations,ensure_ascii=False)+'\nACTUAL CATEGORICAL VALUES\n'+values+'\nQUESTION\n'+question
 try:scope=obj(call(scope_prompt,300)).get('tables',[])
 except AIError:scope=[]
 selected=[t for t in scope if isinstance(t,str) and t in s] if isinstance(scope,list) else []
 if not selected:selected=list(s)
 selected_set=set(selected)
 tables='\n'.join(line for line in profile_lines.splitlines() if line[2:].split('(',1)[0] in selected_set)
 scoped_values='\n'.join(line for line in values.splitlines() if line[2:].split('.',1)[0] in selected_set)
 scoped_relations=[(a,b) for a,b in relations if a.split('.',1)[0] in selected_set and b.split('.',1)[0] in selected_set]
 prompt=f'''You are an e-commerce data analyst and SQLite expert. Generate one accurate read-only query, or refuse when the available schema cannot answer the question. This is an unfamiliar database: do not assume its metric definitions or join keys. Machine-checked temporal annotations and declared/discovered relationships below are authoritative.
TABLES AND MACHINE-CHECKED COLUMN PROFILES\n{tables}\nINFERRED FIELD DESCRIPTIONS (hints, not verified metric definitions)\n{json.dumps({k:v for k,v in field_notes.items() if k.split('.',1)[0] in selected_set},ensure_ascii=False)}\nRELATIONSHIPS DISCOVERED FROM CURRENT DATA (use only these for multi-table joins)\n{chr(10).join('- '+a+' = '+b for a,b in scoped_relations) or '(none supported)'}\nACTUAL CATEGORICAL VALUES\n{scoped_values}\nOBSERVED DATE RANGES\n{chr(10).join(line for line in date_ranges if line[2:].split('.',1)[0] in selected_set)}
Resolve translated or approximate user terms against ACTUAL values, without inventing absent values. Use the smallest sufficient set of tables: when one table already contains every required filter, dimension and measure, do not add a JOIN. Generate valid SQL for the configured SQLite dialect and verify dialect-specific functions before relying on them. Derive metrics from available column names and types; ALWAYS state the chosen measure, aggregation and grain in assumptions (e.g. total units vs sales amount). Active users at a time grain means COUNT(DISTINCT user identifier) among event rows in that grain; average daily active users for each larger period means computing distinct users for every calendar day, retaining that day's larger-period key, and averaging only the daily counts belonging to the same larger period. Require an activity/event time and user identifier for active-user metrics; never substitute event counts, orders, or order-derived proxies. For timestamp-like text, filter date periods with an inclusive start and exclusive next-period boundary. For sales or profit, use an explicit amount/profit column and explain the chosen field. If several plausible definitions exist, refuse or state the needed clarification. If the question asks which single item, category, country or segment is highest, lowest, most or least, return only the requested winner with a deterministic tie-break; use a larger result only when the user explicitly asks for a list or comparison. Limit grouped output to 50.
If a required concept has no table/column (for example ad spend, refunds, or inventory), return {{"cannot_answer":true,"reason":"brief missing-data reason"}} and do not invent a proxy. Never infer causal claims from correlations.
Return strict JSON only: {{"sql":"SQLite SELECT/WITH","chart":"auto|bar|line|grouped_bar|kpi|table","title":"user-language title","assumptions":[]}} or the cannot_answer object. {repair}\nQUESTION: {question}'''
 prompt+='\nRETRIEVED METRIC CONTRACTS (map roles to actual schema; refuse missing roles; state assumptions)\n'+json.dumps(metric_cards,ensure_ascii=False)
 p=obj(call(prompt))
 p['metric_context']=metric_cards
 if p.get('cannot_answer'):return {'cannot_answer':True,'reason':str(p.get('reason') or 'Required data is unavailable')[:300]}
 candidate=str(p.get('sql',''))
 try:
  candidate_tree=parse(candidate,read='sqlite')[0]
  complex_query=bool(candidate_tree.find(exp.CTE) or candidate_tree.find(exp.Subquery))
 except (ParseError,IndexError):complex_query=False
 if complex_query:
  if len(metric_cards)>1:
   split_prompt='''Generate independent SQLite SELECT queries, ONE per requested metric, all at exactly the same output dimensions. Never join raw observations to preaggregated metrics. Each query must be independently executable using the provided schema. Use identical dimension aliases in all queries and a unique metric alias for each measure. Return JSON {"dimensions":["alias"],"queries":["SELECT ...","SELECT ..."]}. For ratios/averages preserve the metric contract denominator, including zero days. Do not add metrics not requested.\nQUESTION\n'''+question+'\nSCHEMA\n'+tables+'\nCONTRACTS\n'+json.dumps(metric_cards)
   try:
    split_prompt+='\nFor nested aggregation, the inner SELECT must GROUP BY the base grain and the outer SELECT must aggregate those INNER metric values at the reporting grain. A distinct count at reporting grain divided by days is NOT an average of daily distinct counts. Use SUM(daily_count)/calendar_days for the average, with month retained from the daily subquery. Check this algebra before returning.'
    split=obj(call(split_prompt,2000));dimensions=split.get('dimensions',[]);queries=split.get('queries',[])
    if not isinstance(dimensions,list) or not all(isinstance(d,str) for d in dimensions) or not isinstance(queries,list) or not 2<=len(queries)<=4:raise AIError('Invalid metric decomposition')
    c=connect();outputs=[]
    try:
     c.execute('PRAGMA query_only=ON')
     for query in queries:
      for sub_attempt in range(3):
       try:
        query=validate(query,set(s),relations)
        cur=c.execute('SELECT * FROM ('+query+') LIMIT 0')
        break
       except (AIError,sqlite3.Error) as sub_error:
        if sub_attempt==2:raise
        query=obj(call('Fix only this independent SQLite metric query. Preserve its output aliases and business meaning. Outer queries can only access columns projected by their source. Return JSON {"sql":"..."}.\nSCHEMA\n'+tables+'\nCONTRACTS\n'+json.dumps(metric_cards)+'\nQUERY\n'+query+'\nERROR\n'+str(sub_error),1400))['sql']
      cols=[x[0] for x in cur.description]
      if not set(dimensions)<=set(cols):raise AIError('Metric dimensions mismatch')
      outputs.append((query,cols))
    finally:c.close()
    ctes=','.join(f'metric_{i} AS ({query})' for i,(query,_) in enumerate(outputs))
    if dimensions:
     keys=' UNION '.join('SELECT '+','.join(q(d) for d in dimensions)+f' FROM metric_{i}' for i in range(len(outputs)))
     ctes+=', metric_keys AS ('+keys+')'
     projections=['k.'+q(d) for d in dimensions];joins=[]
     for i,(_,cols) in enumerate(outputs):
      projections.extend(f'm{i}.'+q(col) for col in cols if col not in dimensions)
      joins.append(f'LEFT JOIN metric_{i} m{i} ON '+' AND '.join(f'm{i}.{q(d)} = k.{q(d)}' for d in dimensions))
     candidate='WITH '+ctes+' SELECT '+','.join(projections)+' FROM metric_keys k '+' '.join(joins)+' ORDER BY '+','.join('k.'+q(d) for d in dimensions)
    else:
     candidate='WITH '+ctes+' SELECT '+','.join(f'm{i}.'+q(col) for i,(_,cols) in enumerate(outputs) for col in cols)+' FROM '+' CROSS JOIN '.join(f'metric_{i} m{i}' for i in range(len(outputs)))
    p['sql']=candidate
    complex_query=False
   except (AIError,sqlite3.Error,TypeError,ValueError):pass
 if complex_query:
  review_prompt='''Review the proposed SQLite query against the user question and available schema. Check column scope across subqueries/CTEs, aggregation grain, distinct entities, time grain, filters, ordering, and whether every returned metric has the requested business meaning. Active users at a grain means distinct user identifiers with events in that grain. When monthly active users and average daily active users are returned per month, compute monthly distinct users separately; compute daily distinct users with the month retained; average daily counts within that same month; then combine the two month-level outputs by month. Never use one whole-period daily average for every subgroup. Return strict JSON {"sql":"corrected read-only SQLite query"}. Do not add unavailable fields or unsupported joins.\nQUESTION\n'''+question+'\nSCHEMA\n'+tables+'\nAPPROVED RELATIONSHIPS\n'+json.dumps(scoped_relations,ensure_ascii=False)+'\nPROPOSED SQL\n'+candidate
  review_prompt+='\nMETRIC CONTRACTS\n'+json.dumps(metric_cards,ensure_ascii=False)
  try:
   reviewed=obj(call(review_prompt,1400)).get('sql',candidate)
   c=connect()
   try:c.execute('PRAGMA query_only=ON');c.execute('EXPLAIN QUERY PLAN '+reviewed)
   finally:c.close()
   p['sql']=reviewed
  except (AIError,sqlite3.Error):p['sql']=candidate
 try:p['sql']=validate(p.get('sql',''),set(s),relations)
 except AIError as e:
  if not repair:return plan(question,f'''Previous SQL:\n{str(p.get('sql',''))[:4000]}\nValidation error: {e}. Re-plan from scratch. Use the smallest sufficient table set and only listed supported joins; do not repeat the rejected join.''')
  raise
 p['chart']=p.get('chart','auto');p['title']=str(p.get('title') or 'AI analysis')[:60];p['assumptions']=[str(x)[:220] for x in p.get('assumptions',[])[:2]] if isinstance(p.get('assumptions'),list) else [];p['available_relationships']=[a+' = '+b for a,b in relations];return p
def run(sql):
 c=connect()
 try:c.execute('PRAGMA query_only=ON');c.execute('EXPLAIN QUERY PLAN '+sql);cur=c.execute(f'SELECT * FROM ({sql}) LIMIT 500');return [x[0] for x in cur.description or []],[dict(x) for x in cur]
 except sqlite3.Error as e:raise AIError(f'SQL execution failed: {e}')
 finally:c.close()
def execution_repair(sql,error):
 message=f'''Previous SQL:\n{str(sql)[:4000]}\nExecution error: {error}. Re-plan from scratch and do not repeat the failed expression.'''
 if 'no such column' in str(error).lower():
  message+=' SQL scope rule: an outer query may reference only columns explicitly projected by its subquery or CTE. Expose every required dimension and identifier at the correct level, or compute each grain in a separate CTE and combine the aggregated outputs.'
 return message
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
    for attempt in range(3):
     try:cols,rows=run(p['sql']);break
     except AIError as e:
      if attempt==2:raise
      p=plan(question,execution_repair(p.get('sql',''),e))
      if p.get('cannot_answer'):
       self.sendj({'question':question,'plan':p,'columns':[],'rows':[],'chart_spec':None,'insights':[p['reason']],'ai':AI});return
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
    declared=declared_relationships(c,s);assert {('orders.customer_id','customers.customer_id'),('order_items.order_id','orders.order_id'),('order_items.product_id','products.product_id'),('user_events.user_id','customers.customer_id')}<=set(declared)
    assert temporal_column(c,'orders',next(x for x in s['orders'] if x['name']=='order_date'))
    assert temporal_column(c,'user_events',next(x for x in s['user_events'] if x['name']=='event_time'))
    assert c.execute('SELECT COUNT(DISTINCT e.user_id) FROM user_events e JOIN customers c ON e.user_id=c.customer_id').fetchone()[0]==c.execute('SELECT COUNT(*) FROM customers').fetchone()[0]
    assert c.execute("SELECT COUNT(DISTINCT user_id) FROM user_events WHERE substr(event_time,1,7)='2024-01'").fetchone()[0]>0
    joined_sql='SELECT COUNT(DISTINCT e.user_id) AS active_customers FROM user_events e JOIN customers c ON e.user_id=c.customer_id'
    assert validate(joined_sql,s,declared)
    customer_sales="SELECT SUM(oi.total_sales) FROM customers c JOIN orders o ON o.customer_id=c.customer_id JOIN order_items oi ON oi.order_id=o.order_id WHERE c.country='Japan'"
    assert validate(customer_sales,s,declared)
    activity_sql="WITH daily AS (SELECT substr(event_time,1,10) day,COUNT(DISTINCT user_id) dau FROM user_events GROUP BY 1), monthly AS (SELECT substr(event_time,1,7) month,COUNT(DISTINCT user_id) mau FROM user_events GROUP BY 1) SELECT m.month,m.mau,AVG(d.dau) FROM monthly m JOIN daily d ON substr(d.day,1,7)=m.month GROUP BY m.month,m.mau"
    assert validate(activity_sql,s,declared)
    normalized_time=validate("SELECT COUNT(*) FROM user_events WHERE event_time BETWEEN '2024-01-01' AND '2024-01-31'",s)
    assert 'BETWEEN' in normalized_time
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
