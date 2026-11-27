"""Reproduce the call-site descendant masks from the committed archive and signed streams."""
import argparse,gzip,json,shutil,sys,tempfile
from pathlib import Path
from audit import classify,sha

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for field in ('tree','d3_evidence','case'):p.add_argument(field)
    a=p.parse_args()
    sys.path.insert(0,str(Path(a.tree).resolve()/'dependency-reuse/scripts'))
    from recheck_d2 import restore
    ev=Path(a.d3_evidence).resolve();c=a.case;archive=ev/'pairs'/c
    here=Path(__file__).resolve().parent;source=here/c
    target=json.loads((here/'summary.json').read_text())['cases'][c]
    r=next(z for z in json.loads((archive/'runs.json').read_text()) if (z['mode'],z['repeat'])==('mixed',1))
    with tempfile.TemporaryDirectory() as temp:
        t=Path(temp);out=t/'out';out.mkdir()
        restore(ev,c,r,t/'proof.bin')
        for n in ('native-origins.tsv','native-learns.tsv','native-theory.tsv'):
            with gzip.open(source/(n+'.gz'),'rb') as f,(t/n).open('wb') as dst:shutil.copyfileobj(f,dst)
        result=classify(c,t/'proof.bin',archive,t,out)
        assert all(result[k]==target[k] for k in result),c
        for n in ('learned-origin-masks.tsv.gz','boundaries.tsv.gz','native-origins.tsv.gz'):
            assert sha(out/n,True)==sha(source/n,True),n
    print(c,'verified')
if __name__=='__main__':main()
