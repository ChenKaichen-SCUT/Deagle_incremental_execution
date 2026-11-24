"""Exhaust finite rule edits and compare with an independent simultaneous least fixed point."""
import argparse,itertools,json,random,subprocess,hashlib
from pathlib import Path
def spec(n,po,apo,guards,rf,co):
    # Event 0,1,3 are writes when present; event 2 reads their common address.
    on=lambda i:(3,i,0)
    groups=[{i} for i in range(n)]
    for x,y in apo:
        g=next(a for a in groups if x in a);h=next(a for a in groups if y in a)
        if g!=h:g.update(h);groups.remove(h)
    base={(16,x,y) for x,y in po+apo}|{on(i) for i in guards}
    rules=[]
    def rule(k,h,*body):rules.append((k,h,body))
    for x,y in po+apo:rule(3,(1,x,y),(16,x,y))
    for x,y in po:
        base.add((17,x,y))
        if x in guards:base.add((14,x,0))
        rule(14,(2,x,y),(17,x,y),(14,x,0),on(x),on(y))
    # Basic memberships and directed identity changes select the applicable grounded rules.
    for i,j in itertools.product(range(n),repeat=2):
        rule(4,(2,i,j),(1,i,j),on(i),on(j))
        for k,label in [(6,6),(9,7),(10,8)]:rule(label,(2,i,j),(k,i,j))
        rule(11,(15,0,0),(2,i,i))
    for w in {0,1,3}&set(range(n)):
        if n<=2:continue
        base.add((5,w,2))
        if w in rf:base.add((4,w,2))
        rule(5,(6,w,2),(5,w,2),(4,w,2),on(w),on(2))
        for u in ({0,1,3}&set(range(n)))-{w}:
            base.add((11,u,w));base.add((8,u,w))
            if (u,w) in co:base.add((7,u,w))
            rule(9,(9,u,w),(6,w,2),(2,u,2),on(u),(11,u,w))
            rule(10,(10,2,u),(6,w,2),(2,w,u),on(u),(11,u,w))
            rule(12,(9,u,w),(8,u,w),(7,u,w),on(u),on(w))
    for a,b in itertools.permutations(groups,2):
        for i,x,j,y in itertools.product(a,a,b,b):
            rule(13,(2,x,y),(2,i,j),on(x),on(y))
    return base,set(rules)
def reference(b,rules):
    facts=set(b)
    while True:
        new={h for _,h,body in rules if all(p in facts for p in body)}
        rel=[(p,x,y) for p,x,y in facts if p in (1,2)]
        new.update((p,x,z) for p,x,y in rel for q,v,z in rel if p==q and y==v)
        if new<=facts:break
        facts.update(new)
    fired=sum(all(a in facts for a in body) for _,_,body in rules)
    return facts,fired+sum(1 for p,x,y in rel for q,v,z in rel if p==q and y==v)
def validate(exe,out):
    rng=random.Random(1102);cases=[]
    for mask in range(32):
        on=set(range(5));args=(5,[(0,1),(1,2),(3,4)],[],on,{0},set())
        for name,p,a,g,rf,co in [('base',args[1],[],on,{0},set()),
                ('replace RF',args[1],[],on,{1},set()),('merge',args[1],[(1,2)],on,{1},set()),
                ('split and remove',[(0,1),(3,4)],[],on,{1},set()),('guard off',args[1],[],on-{mask%5},{0},set()),
                ('selected CO',args[1],[],on,{0},{(1,0)}),('event removed',[(0,1)],[],{0,1,2},{0},set())]:
            n=3 if name=='event removed' else 5
            extra=[(x,y) for x,y in itertools.permutations(range(n),2) if rng.randrange(12)==0]
            cases.append((name,*spec(n,p+extra,a,g,rf,co)))
    # Cyclic self-support, alternative proof from K, and addition with only old prerequisites.
    a,b,c,d=[(16,i,0) for i in range(4)]
    rs={(20,b,(a,)),(21,c,(b,)),(22,b,(c,)),(23,c,(d,))}
    cases.extend([('rooted cycle',{a,d},rs),('alternative only',{d},rs),('unrooted cycle',set(),rs),
                  ('empty body',set(),rs|{(24,d,())})])
    lines=[];expect=[]
    def fmt(a):return ' '.join(map(str,a))
    for name,base,rules in cases:
        lines.extend('B '+fmt(a) for a in sorted(base))
        lines.extend('R '+str(k)+' '+fmt(h)+' '+str(len(body))+' '+' '.join(map(fmt,body)) for k,h,body in sorted(rules))
        lines.append('RUN');expect.append(reference(base,rules))
    raw=('\n'.join(lines)+'\n').encode();native=subprocess.run([exe],input=raw,stdout=subprocess.PIPE,check=True).stdout
    stream=iter(native.decode().splitlines());rows=[]
    for (name,_,_),(cold,count) in zip(cases,expect):
        item=next(stream).split();tag=item.pop(0);n,fired,o,k,affected,recovered,checked=map(int,item)
        result={tuple(map(int,next(stream).split())) for _ in range(n)}
        if tag!='C' or result!=cold or fired!=count:raise AssertionError((name,result^cold,fired,count))
        rows.append(dict(case=name,facts=n,fired=fired,O=o,K_derived=k,affected=affected,recovered=recovered,checks=checked))
    assert next(stream,None) is None
    import gzip
    out.mkdir(parents=True,exist_ok=True)
    for name,data in [('input',raw),('stdout',native)]:(out/(name+'.txt.gz')).write_bytes(gzip.compress(data,mtime=0))
    (out/'finite.json').write_text(json.dumps(dict(reference='Python simultaneous all-ground saturation',input_sha256=hashlib.sha256(raw).hexdigest(),rows=rows),indent=2))
if __name__=='__main__':
    import sys
    validate(Path(sys.argv[1]).resolve(),Path(sys.argv[2]))
