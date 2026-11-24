"""Repeat exploratory diagnoses in strictly private output paths after the native observer audit."""
from prepare import ROOT,E,job,dump,schedule
import json

def main():
    cases=json.loads((E/'inventory.json').read_bytes())
    formal={r['sample'] for r in json.loads((ROOT/'formal.json').read_bytes())}
    jobs=[]
    for k,c in cases.items():
        if k in formal:continue
        sec,mem,bound=60,3,c['bound']
        if k.startswith('fib-safe'):sec,mem=220,4
        if k in ('25_stack_longest-1','25_stack_longest-2','26_stack_cas_longer-1','26_stack_cas_longer-2'):
            sec,mem=180,9
        if k.startswith('arithmetic'):sec,mem,bound=180,5,8
        if k=='netbsd':sec,mem=660,7
        jobs.append(job(c,'isolated',sec,mem,bound))
    jobs.sort(key=lambda r:(r['sample']!='netbsd',-r['timeout_s']))
    dump(ROOT/'isolated.json',jobs)
    schedule([('isolated',8)])
if __name__=='__main__':main()
