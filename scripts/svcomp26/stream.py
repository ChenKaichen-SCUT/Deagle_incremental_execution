"""Inspect the frozen native stream without materializing millions of Python clauses."""
from collections import Counter
import mmap
from pathlib import Path
import sys
def inspect(path,eligible=None):
    nvar=0;clauses=0;graphs=0;goals=[];literals=0;stable=Counter()
    with path.open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data:
        a=memoryview(data).cast('I');i=0
        try:
            while i<len(a):
                tag=a[i];i+=1
                if tag==0xfffffff1:
                    if a[i]!=nvar:raise ValueError('non-contiguous variable allocation')
                    nvar+=1;i+=3
                elif tag==0xfffffff4:i+=2
                elif tag==0xfffffff2:graphs+=1
                elif tag in (0xfffffff0,0xfffffff3):
                    n=a[i];i+=1
                    if i+n>len(a):raise ValueError('incomplete input row')
                    if tag==0xfffffff0:
                        clauses+=1;literals+=n
                        if eligible and n>=2 and a[i]//2 in eligible and all(a[j]//2 in eligible for j in range(i+1,i+n)):
                            stable[tuple(sorted(a[i:i+n]))]+=1
                    else:goals.append(dict(variables=nvar,clauses=clauses,assumptions=list(a[i:i+n])))
                    i+=n
                else:raise ValueError('invalid input opcode')
            if i!=len(a) or graphs!=1 or not goals:raise ValueError('incomplete native encoding')
        finally:a.release()
    return dict(variables=nvar,clauses=clauses,literal_occurrences=literals,queries=goals),stable
def states(path):
    keys='time object pid vars originals learnts assignments level ok arena_bytes starts decisions conflicts propagations theory_propagations theory_conflicts graph_nodes peak_rss_kib'.split()
    raw=[list(map(int,s.split())) for s in path.read_text().splitlines()]
    if not raw or len(raw)%2 or any(len(r)!=len(keys) for r in raw):raise ValueError('incomplete native state boundaries')
    return [dict(zip(keys,r)) for r in raw]
