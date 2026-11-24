from pathlib import Path
import json
from collections import Counter
d=Path.cwd()
for p in sorted(d.glob('order-*.log')):
    print(p.name, p.read_text(errors='replace')[-1250:], 'done',(d/(p.name[:-4]+'.complete')).exists())
for p in d.glob('*-queue.json'):
    a=json.loads(p.read_bytes());print(p.name,a['peak_concurrent'],a['elapsed_s'],a['results'])
for p in sorted(d.glob('*/*/receipt.json')):
    a=json.loads(p.read_bytes())
    print(a['out'],a['result'],round(a['phases'].get('search',{}).get('wall_s',0),3),a['counters'] and a['counters']['queries'])
