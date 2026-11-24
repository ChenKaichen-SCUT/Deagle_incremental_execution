"""Independent scalar interleaving checks on the published Fibonacci workers and LDV publication."""
import json
import math
import re
from prepare import DS,E,dump


def fib_bound(n):
    a,b=0,1
    for _ in range(2*n+2):a,b=b,a+b
    return a


def enumerate_fib(n):
    maximum=[1,1];prefixes=complete=0;equal_witness=None
    bound=fib_bound(n)
    def dfs(p,q,i,j,word):
        nonlocal prefixes,complete,equal_witness
        prefixes+=1
        if i>maximum[0]:maximum[0]=i
        if j>maximum[1]:maximum[1]=j
        assert i<=bound and j<=bound and i<=2147483647 and j<=2147483647
        if equal_witness is None and (i==bound or j==bound):
            equal_witness=dict(schedule_bits=format(word,'0'+str(p+q)+'b'),i=i,j=j)
        if p==n and q==n:complete+=1
        if p<n:dfs(p+1,q,i+j,j,word<<1)
        if q<n:dfs(p,q+1,i,j+i,(word<<1)|1)
    dfs(0,0,1,1,0)
    assert complete==math.comb(2*n,n) and maximum==[bound,bound] and equal_witness
    return dict(n=n,complete_orders=complete,prefixes=prefixes,maximum=maximum,reference=bound,strict_violation=equal_witness)


def main():
    proofs={}
    for n in (10,11,12):
        result=enumerate_fib(n)
        for cid in [f'fib-snapshot-{n}']+(['fib-strict-12'] if n==12 else []):
            op='<' if cid=='fib-strict-12' else '<='
            source=[(DS/cid/k/'program.i').read_text() for k in ('old','new')]
            for i,s in enumerate(source):
                assert f'for (p = 0; p < {n}; p++)' in s and f'for (q = 0; q < {n}; q++)' in s and f'for (x = 0; x < {2*n+2}; x++)' in s
                assert s.count(f'i {op} correct && j {op} correct')==1
                assert s.count('pthread_create(&id')==2
                for v,add in [('i','i + j'),('j','j + i')]:
                    assert re.search(r'__VERIFIER_atomic_begin\(\);\s*'+v+r' = '+re.escape(add)+r';\s*__VERIFIER_atomic_end\(\);',s)
                assert ('_Bool assert_cond' in s)==bool(i)
            proofs[cid]=dict(**result,operator=op,witness_encoding='0=t1 updates i; 1=t2 updates j. main can sample after this prefix.',
                scope='Arithmetic and SC interleavings of source atomic updates. Each value is nondecreasing, so two distinct sampling instants also respect a componentwise bound. Does not certify C11 race freedom of P0.')
    dump(E/'fib-functional.json',proofs)
    old=(DS/'ldv-publication/old/program.i').read_text();new=(DS/'ldv-publication/new/program.i').read_text()
    assert old.replace('      pdev = 2;\n      __VERIFIER_atomic_end();\n      __VERIFIER_atomic_begin();','      pdev = 2;')==new
    dump(E/'ldv-functional.json',dict(on_successful_spawn=dict(P0_orders=['W6 W2 R2','W2 W6 R6','W2 R2 W6'],P1_orders=['W6 [W2 R2]','[W2 R2] W6']),
         after_join='worker completed before W5/R5',no_spawn='W1/R1 then W3/R3 progress unchanged',
         repair='Only the two adjacent main-thread atomic sections are merged; writer still executes and original assertions are preserved.'))
if __name__=='__main__':main()
