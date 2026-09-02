"""Export deterministic normalized demo tables generated from the bundled sales CSV."""
import csv
from pathlib import Path
from server import connect,schema
OUT=Path(__file__).parent/'data'/'simulated'
def main():
 OUT.mkdir(parents=True,exist_ok=True);c=connect();s=schema(c)
 try:
  for table in ['customers','products','orders','order_items','events']:
   cols=[x['name'] for x in s[table]]
   with (OUT/f'{table}.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.writer(f);w.writerow(cols);w.writerows(c.execute(f'SELECT * FROM {table}'))
   print('exported',table)
 finally:c.close()
if __name__=='__main__':main()
