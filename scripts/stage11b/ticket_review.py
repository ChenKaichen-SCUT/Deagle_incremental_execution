"""Review a static ordering identity for the five unchanged, loop-free ticket workers only."""
import hashlib,json,re,sys,tarfile
from collections import Counter
from pathlib import Path
from bindings import capture_identity,digest
def record(capture,versions,out):
    specs=json.loads((versions/'extra-pairs.json').read_bytes())
    pair=next(r for r in specs if r['name']=='ticket')
    both=[];reports={}
    with tarfile.open(capture) as tar:
        for side,n in [('old',5),('new',6)]:
            raw=(versions/('ticket-'+side+'.c')).read_bytes();src=raw.decode()
            source=hashlib.sha256(raw).hexdigest();assert source==pair[side+'_sha256']
            def load(k):return tar.extractfile(side+'/'+k).read()
            m=json.loads(load('full_model.json'));g=json.loads(load('goto.json'));vis=json.loads(load('visits.json'))
            table=json.loads(load('native-bindings.json'));receipt=json.loads(load('receipt.json'))
            symbols=sorted(re.findall(r'pthread_create\(&t(\d+), 0, thread(\d+), 0\);',src))
            assert symbols==[(str(i),str(i)) for i in range(1,n+1)]
            assert [(b['parent'],b['child'],b['function']) for b in m['thread_births']]==[(0,i,'main') for i in range(1,n+1)]
            ctx={};names={};pool=m['ireps']
            def term(i):
                if i is None:return None
                p=pool[i]
                return [p['id'],{k:term(v) for k,v in sorted(p.get('named',{}).items()) if k not in ('#source_location','#end_location')},[term(v) for v in p.get('sub',[])]]
            for i in range(1,6):
                fn='thread'+str(i)
                body=re.search(r'void\* '+fn+r'\(void\* _argptr\) \{[^}]+\}',src).group()
                instructions=[x for x in g['instructions'] if x['function']==fn]
                start=min(x['pc'] for x in instructions);coords={x['pc']:x for x in instructions}
                occurrence=Counter()
                for st in m['steps']:
                    key=st.get('oc_name')
                    if not key or st['function']!=fn:continue
                    assert st['thread']==i and vis[st['visit']-1]['thread']==i
                    ins=coords[st['pc']]
                    assert ins['file']=='program.c' and st['kind'] in ('read','write')
                    site=(i,fn,st['pc']-start,ins['line'],ins['column'],ins['kind'],st['kind'],st['object'],table['addresses'][key])
                    occurrence[site]+=1
                    identity=digest(['ticket/structural-site',site,occurrence[site],body,term(pool[st['lhs']]['named']['type']),g['layout']])
                    assert identity not in ctx
                    ctx[identity]={'site':site,'guard':term(st['guard']),'source_thread_body_sha256':hashlib.sha256(body.encode()).hexdigest()}
                    names[key]=identity
            assert len(ctx)==50
            refs={k:load(k) for k in ('s8-input.bin','s8-graph.tsv','native-bindings.json','goto.json','visits.json','full_model.json')}
            p=g['ireps'];wd={p[v]['id'] for z in p for key,v in z.get('named',{}).items() if key=='working_directory'}
            assert len(wd)==1
            reports[source]=dict(roles=names,hashes={k:capture_identity(k,b,next(iter(wd))) for k,b in refs.items()},argv=receipt['argv'])
            both.append(ctx)
    assert set(both[0])==set(both[1])
    guards=sum(both[0][k]['guard']!=both[1][k]['guard'] for k in both[0])
    out.write_bytes((json.dumps(dict(versions=reports,stable_static_worker_sites=50,changed_guard_terms=guards,
        basis='same full thread function, spawn target and ordinal, source line/column, function-relative instruction, type, address, occurrence and layout; static quotient only'),sort_keys=True,indent=2)+'\n').encode())
if __name__=='__main__':record(*map(Path,sys.argv[1:]))
