"""Freeze one source-level repair and the independently published 5/6-worker scaling control."""
from pathlib import Path
import difflib,hashlib,json
def freeze(public,out):
    out.mkdir(exist_ok=True,parents=True);pairs=[]
    for name in ('stack','ticket'):
        if name=='stack':
            p=public/'benchmarks/pthread/stack_longest-1.i';old=p.read_bytes()
            needle=b'if (!(pop(arr)!=(-2)))\n        error();'
            assert old.count(needle)==1
            new=old.replace(needle,needle+b'\n      flag = !stack_empty();')
            labels=[str(p.relative_to(public)), 'manual availability update under the held mutex']
            kind='actual attempted repair: stale availability flag after last successful pop'
            suffix='.i'
        else:
            ps=[public/f'benchmarks/weaver/parallel-ticket-{i}.wvr.c' for i in (5,6)]
            old,new=[p.read_bytes() for p in ps]
            labels=[p.relative_to(public).as_posix() for p in ps]
            kind='published family size change; property already holds; excluded from repair rates'
            for v in (old,new):assert v.count(b'assume_abort_if_not(b);')==1 and v.count(b'  reach_error();')==1
            suffix='.c'
        for n,data in [('old',old),('new',new)]:(out/(name+'-'+n+suffix)).write_bytes(data)
        diff=''.join(difflib.unified_diff(old.decode().splitlines(True),new.decode().splitlines(True),name+'-old'+suffix,name+'-new'+suffix))
        (out/(name+'.diff')).write_bytes(diff.encode())
        pairs.append(dict(name=name,kind=kind,source=labels,old_sha256=hashlib.sha256(old).hexdigest(),new_sha256=hashlib.sha256(new).hexdigest(),patch_sha256=hashlib.sha256(diff.encode()).hexdigest()))
    (out/'extra-pairs.json').write_bytes((json.dumps(pairs,sort_keys=True,indent=2)+'\n').encode())
if __name__=='__main__':
    import sys
    freeze(*map(Path,sys.argv[1:]))
