"""Restore a frozen case's original solver inputs and evidence by verified content digest."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.stage11b.raw_store import archive


def restore(raw,output,prefix):
    paths=json.loads((raw/'files.json').read_bytes())
    prefix=prefix.strip('/')
    if not prefix:raise ValueError('choose a case or an explicit indexed prefix')
    wanted={k:v for k,v in paths.items() if k==prefix or k.startswith(prefix+'/')}
    if not wanted:raise ValueError('no archived paths for '+prefix)
    base=output.resolve()
    with archive(raw) as z:
        for p,key in wanted.items():
            dest=(base/p).resolve()
            if not dest.is_relative_to(base):raise ValueError('unsafe archived path')
            blob=z.read(key)
            if hashlib.sha256(blob).hexdigest()!=key:raise ValueError('bad original '+p)
            if dest.exists() and dest.read_bytes()!=blob:raise ValueError('different existing file '+str(dest))
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(blob)
    return len(wanted)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('output',type=Path)
    g=p.add_mutually_exclusive_group(required=True);g.add_argument('--case');g.add_argument('--prefix')
    args=p.parse_args();raw=ROOT/'reports/evidence/stage-12/raw'
    prefixes=[args.prefix]
    if args.case:
        d=ROOT/'datasets/stage-12-hard-pairs'/args.case
        if d.resolve().parent!=(ROOT/'datasets/stage-12-hard-pairs').resolve():raise ValueError('invalid case')
        results=json.loads((d/'baseline.json').read_bytes())['results'];prefixes=['server/'+r['out'] for r in results.values()]
    for prefix in prefixes:print(prefix,restore(raw,args.output,prefix))
