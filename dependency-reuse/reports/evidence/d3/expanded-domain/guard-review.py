"""Collect the changed GuardDecl ancestor and check old lemmas on both finite SC models."""
from pathlib import Path
from itertools import product,permutations
import hashlib,importlib.util,json,struct,sys

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def models(h,z):
    events,writes,reads,rep,internal,po,_,_=h.semantics(z)
    for order in permutations(events):
        pos={e:i for i,e in enumerate(order)}
        if not all(pos[u]<pos[v] for u,v in po):continue
        groups=[rep[e] for e in order]
        if any(max(i for i,q in enumerate(groups) if q==g)-groups.index(g)+1!=groups.count(g) for g in set(groups)):continue
        for v in product((False,True),repeat=8):
            val=lambda i:v[abs(i)-1]!=(i<0)
            if not all(any(map(val,c)) for c in z['clauses']):continue
            active={w for w in writes if not z['guards'].get(w,0) or val(z['guards'][w])}
            if any(w not in active or pos[w]>=pos[r] or any(pos[w]<pos[t]<pos[r] for t in active if t not in (w,r))
                   for k,w,r,f in z['edges'] if k=='rf' and val(f)):continue
            yield order,v

def facts(path):
    data=path.read_bytes();assert data[:6]==b'DEAGD3';s=[];pos=12
    for sz in (16,4,8,16,12,8,12,4,4,4,4,4,20):
        count=struct.unpack_from('<I',data,pos)[0];s.append((pos+4,count));pos+=4+sz*count
    n,l,e=s[0][0],s[1][0],s[2][0]
    theory={r[0]:r[1:] for r in (struct.unpack_from('<IIiii',data,s[-1][0]+20*i) for i in range(s[-1][1]))}
    def node(i):
        fl,fe=struct.unpack_from('<II',data,n+16*(i-1));tl,te,k,f=struct.unpack_from('<4I',data,n+16*i)
        return k,struct.unpack_from('<'+'i'*(tl-fl),data,l+4*fl),[struct.unpack_from('<I',data,e+8*j)[0] for j in range(fe,te)]
    for i in range(1,s[0][1]):
        k,conclusion,parents=node(i)
        if k!=14:continue
        visited={i};queue=parents.copy()
        while queue:
            at=queue.pop()
            if at in visited:continue
            visited.add(at)
            queue.extend(node(at)[2])
        yield i,conclusion,{j:theory[j] for j in sorted(visited) if j in theory}

def metrics(path):
    return {k:int(n) for k,n in (line.split() for line in path.read_text().splitlines())}

def main():
    code=Path(sys.argv[1]).resolve();micro=Path(sys.argv[2]).resolve();out=Path(sys.argv[3]).resolve()
    s=importlib.util.spec_from_file_location('harness',code/'dependency-reuse/tests/d3/check.py')
    h=importlib.util.module_from_spec(s);s.loader.exec_module(h)
    evidence={}
    for z,op in [(h.compete,15),(h.ws,14)]:
        d=micro/z['tag'];base=metrics(d/'same/metrics.tsv');alt=metrics(d/'guard/metrics.tsv')
        p1=h.altered(z,'guard')
        expected=['8',*[' '.join(map(str,e)) for e in z['edges']],
                  *[f'guard {w} {g}' for w,g in z['guards'].items()],*['B '+' '.join(map(str,c)) for c in z['clauses']],
                  'A '+' '.join(map(str,z['assumptions']))]
        assert expected==(d/'spec').read_text().splitlines()
        assert base['theory_reasons_survive']==1 and alt['theory_reasons_survive']==0
        def decl_status(file):
            return {tuple(map(int,p[1:5])):p[5] for p in (l.split() for l in file.read_text().splitlines()) if p[0]=='D'}
        old=decl_status(d/'same/decl');new=decl_status(d/'guard/decl')
        altered={k for k in old if old[k]!=new[k]}
        (changed,)=altered
        assert changed[0]==4 and (old[changed],new[changed])==('M','C')
        lemma,c,rules=next(facts(d/'D3/proof.bin'))
        assert changed in rules.values() and any(v[0]==op for v in rules.values())
        counts={};fails={};example=None
        for label,test in [('P0',z),('P1',p1)]:
            counts[label]=fails[label]=0
            for order,v in models(h,test):
                counts[label]+=1
                if not any(v[l//2-1] != bool(l&1) for l in c):
                    fails[label]+=1
                    if label=='P1' and example is None:example=dict(order=order,true_variables=[i+1 for i,b in enumerate(v) if b])
        assert counts['P0'] and counts['P1'] and not fails['P0']
        if z['tag']=='ws':assert fails['P1']>0
        evidence[z['tag']]=dict(spec_sha256=sha(d/'spec'),proof_sha256=sha(d/'D3/proof.bin'),p0_guard=z['guards'],p1_guard=p1['guards'],
            local_graph_changed_decl=changed,changed_decl_id=next(k for k,v in rules.items() if v==changed),use_rule='WS' if op==14 else 'FR',
            lemma_id=lemma,old_signed_clause=c,branch_assumptions=z['assumptions'],truth_table_scope='all permanent Boolean/SC models',
            checked_p0_surviving_reasons=base['theory_reasons_survive'],checked_p1_surviving_reasons=alt['theory_reasons_survive'],
            models_enumerated=counts,models_falsifying_old_reason=fails,p1_counterexample=example,
            p0_stats_sha256=sha(d/'same/metrics.tsv'),p1_stats_sha256=sha(d/'guard/metrics.tsv'))
    out.write_text(json.dumps(evidence,indent=2)+'\n')

if __name__=='__main__':main()

