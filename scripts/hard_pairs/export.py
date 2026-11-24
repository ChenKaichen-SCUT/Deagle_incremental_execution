"""Export completed records only; retain full inputs and native artefacts of confirmation runs."""
import hashlib
import json
import os
import tarfile
import sys
from pathlib import Path
d=Path.cwd()
all_files='--all' in sys.argv
basename='all-attempts' if all_files else 'evidence'
with tarfile.open(basename+'.tmp','w:gz',compresslevel=4) as t:
    for p in sorted(d.glob('*/*/receipt.json')):
        a=json.loads(p.read_bytes());base=p.parent/a['attempt']
        t.add(p,arcname=p.relative_to(d))
        for f in sorted(base.iterdir()):
            if not f.is_file(): continue
            if all_files or a['phase'].startswith(('formal','local')) or f.name in ('result.json','stdout','stderr','s8-search.tsv','s8-native.tsv','s8-sat.tsv','native-state.tsv','boundary.tsv'):
                t.add(f,arcname=f.relative_to(d))
    for pattern in ('order-*.host','order-*.log','order-*.complete','*.json','*.txt'):
        for p in sorted(d.glob(pattern)):
            if p.is_file():t.add(p,arcname=p.name)
os.replace(basename+'.tmp',basename+'.tar.gz')
h=hashlib.sha256()
with open(basename+'.tar.gz','rb') as f:
    for b in iter(lambda:f.read(4194304),b''):h.update(b)
(d/('all-attempts.sha256' if all_files else 'export.sha256')).write_text(h.hexdigest()+'\n')
