"""Run the pinned stage-8 harness from the chosen checkout without changing either worker."""
import argparse
import sys
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__)
for name in ('checkout','source','lock','out'):
    p.add_argument(name,type=Path)
p.add_argument('case');p.add_argument('mode',choices=['F1','I3'])
p.add_argument('repeat',type=int);p.add_argument('--detail',action='store_true')
args=p.parse_args()
sys.path.insert(0,str(args.checkout.resolve()))
from scripts.stage8.experiment import one
one(args.source.resolve(),args.lock.resolve(),args.out.resolve(),args.case,args.mode,args.repeat,args.detail,
    {'observe':True,'stream':True} if args.detail else None)
