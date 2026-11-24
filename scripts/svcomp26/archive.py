"""Content-addressed, lossless raw evidence using the frozen study codec."""
import argparse
import sys
from pathlib import Path
from config import ROOT
sys.path.insert(0,str(ROOT))
from scripts.stage8 import archive as codec
codec.ROOTS=('P0','P0-target','datarace','rounds','oracles','functional','packets','pairs','preflight','diagnostic')
codec.LOGS=('p0.log','supp.log','native.log','compare.log','stage.log','deagle-help.txt','machine.json')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['pack','unpack']);p.add_argument('source',type=Path);p.add_argument('destination',type=Path);a=p.parse_args()
    if a.action=='pack':codec.pack(a.source,a.destination)
    else:codec.unpack(a.source,a.destination,full=True)
