"""Reproduce the official table join without downloading the full SV-Benchmarks monorepo."""
import argparse
import gzip
import shutil
from pathlib import Path
import json
from collect import SITE,hashb,main,get
from fetch_tasks import run as fetch
from config import ROOT

def replay(cache,dest):
    baseline=ROOT/'reports/evidence/svcomp26'
    ref=json.loads((baseline/'official-provenance.json').read_bytes())
    cache.mkdir(parents=True,exist_ok=True);raw=dest/'official';raw.mkdir(parents=True,exist_ok=True)
    for name,spec in ref['sources'].items():
        src=baseline/'official'/name;assert hashb(src.read_bytes())==spec['sha256']
        if src.resolve()!=(raw/name).resolve():shutil.copyfile(src,raw/name)
    # Replay the four run set names from their pinned receipts even when the live event index changes.
    ix=''.join('<a href="'+v['scored']+'.table.html"></a>\n' for v in ref['run_sets'].values())
    (cache/'official-index.html').write_bytes(ix.encode())
    (cache/'tag.json').write_bytes((raw/'svcomp26-tag.json').read_bytes())
    (cache/'table.html').write_bytes(gzip.decompress((raw/'reach-table.html.gz').read_bytes()))
    archive=baseline/'official/deagle-logfiles.zip'
    if (raw/archive.name).resolve()!=archive.resolve():shutil.copyfile(archive,raw/archive.name)
    fetch(cache,dest);main(cache,dest)
    for name in ('candidates.csv','all-records.csv','unconfirmed.csv','original-files.json','panel.json'):
        assert hashb((dest/name).read_bytes())==hashb((baseline/name).read_bytes()),name
    print('All official row, original file and panel identities match.')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('cache',type=Path);p.add_argument('destination',type=Path);a=p.parse_args();replay(a.cache.resolve(),a.destination.resolve())
