"""Replay the stage-5 published batch proof with the 11C signed step checker."""
import collections,json,sys,hashlib,subprocess
from pathlib import Path
from types import SimpleNamespace
from theory import verify,need
from audit import save
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.theory.certificate import check
def main(root,out):
    base=root/'reports/evidence/stage-05/batch_total'
    read=lambda name:json.loads((base/name).read_bytes())
    ctx=read('old-context.json');native=read('old-bindings.json');cache=read('lemma-cache.json')
    names={};g=SimpleNamespace(po=set(),apo=set(),rf={},guards={})
    g.nodes={k:(v['role'],v['solver_address'],v['type'],v['event_guard'],v['address_l1']) for k,v in ctx['events'].items()}
    for row,raw in zip(ctx['edges'],native['edges']):
        a,b=row['from'],row['to'];names[raw['from']]=a;names[raw['to']]=b
        if row['kind']=='rf':g.rf[a,b]=raw['x']
        else:getattr(g,row['kind']).add((a,b))
    g.guards={names[r['event']]:r['x'] for r in native['guards']}
    parent={k:{k} for k in g.nodes}
    for a,b in g.apo:
        merged=parent[a]|parent[b]
        for v in merged:parent[v]=merged
    g.group={k:tuple(sorted(v)) for k,v in parent.items()}
    g.premises=lambda q:{x^1 for x in q}
    g.enabled=lambda k,truth:g.guards.get(k)==-1 or g.guards.get(k) in truth
    rows=[]
    for item in cache['lemmas']:
        need(check(ctx,item['clause'],item['certificate']),'legacy invalid')
        raw=[]
        for l in item['clause']:
            atom=l['atom'];x=g.rf[atom['write'],atom['read']] if atom['kind']=='rf' else g.guards[atom['event']]
            raw.append(x^int(l['negative']))
        proof=[]
        for n in item['certificate']:
            a,b=n['edge'];r=n['rule'];p=n['uses'];more=[]
            if r=='static':rule='po' if (a,b) in g.po else 'apo'
            elif r=='atomic_block':rule='block'
            elif r=='transitive':rule='path'
            elif r=='rf':rule='rf'
            elif r=='from_read':rule='fr';w=proof[p[0]][1];more=[w,a,b,-1]
            elif r=='coherence':rule='co';v=proof[p[0]][2];more=[b,v,a,-1]
            else:raise ValueError(r)
            proof.append([rule,a,b,p,more])
        support=verify(g,raw,proof)
        rows.append(dict(sha256=item['clause_sha256'],raw_signed=raw,steps=len(proof),support=len(support),old_checker=True,stage11c_checker=True))
    run=subprocess.run([sys.executable,'-B',str(root/'scripts/stage5/check_evidence.py')],capture_output=True,text=True,check=True)
    save(out.parent,out.name,dict(certificates=rows,published_replay=run.stdout.strip()))
if __name__=='__main__':main(ROOT,Path(sys.argv[1]))
