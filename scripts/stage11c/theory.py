"""Independent, source-scoped checker for witnessed positive OC steps and their contrapositive."""
import collections,functools,hashlib,json
from pathlib import Path
class Refused(ValueError):pass
def need(value,reason):
    if not value:raise Refused(reason)
def h(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def ls(field):return tuple(map(int,field.split(','))) if field else ()
def parse(path):
    names={};events={};learn={};counts={};version=None
    with path.open() as f:
        for line in f:
            typ,*p=line.rstrip('\n').split('\t')
            if typ=='N':names[int(p[0])]=p[1];continue
            if typ=='Z':counts=dict(zip(('cycles','snapshots','preventive_attempts','preventive_snapshots','all_learnts','removals','GC'),map(int,p)));continue
            if typ=='X':continue
            i=int(p[0])
            if typ=='E':
                events[i]=dict(id=i,origin=p[1],a=int(p[2]),b=int(p[3]),cause=p[4],trigger=[int(p[5]),int(p[6])],clause=ls(p[7]),G=[],R=[],I=[])
            elif typ in ('G','I'):events[i][typ].append(tuple(map(int,p[1:])))
            elif typ=='R':events[i]['R'].append((int(p[1]),int(p[2]),ls(p[3])))
            elif typ in ('V','P'):events[i]['evaluation']=(typ,int(p[1]),ls(p[2]),[ls(a) for a in p[3:]])
            else:
                d=learn.setdefault(i,dict(A=[],D={}))
                if typ=='A':d['A'].append((int(p[1]),p[2],ls(p[3])))
                elif typ=='D':d['D'][int(p[1])]=(p[2],ls(p[3]))
                elif typ in ('L','Q'):d[typ]=ls(p[1])
                else:raise Refused('unknown_trace_record')
    return names,events,learn,counts

class Graph:
    def __init__(self,d):
        nat=json.loads((d/'native-bindings.json').read_bytes());m=json.loads((d/'full_model.json').read_bytes())
        self.uid=dict(line.split('\t') for line in (d/'events.tsv').read_text().splitlines())
        need(len(set(self.uid.values()))==len(self.uid) and set(self.uid)==set(nat['addresses']),'unverified_event_bijection')
        pool=m['ireps']
        @functools.lru_cache(None)
        def expr(i):
            if i is None:return None
            t=pool[i];return h([t['id'],[(k,expr(v)) for k,v in sorted(t.get('named',{}).items())],[expr(v) for v in t.get('sub',[])]])
        self.nodes={};self.guards={};self.rf={};self.po=set();self.apo=set();self.by_raw=collections.defaultdict(set)
        for s in m['steps']:
            name=s.get('oc_name')
            if not name:continue
            k=self.uid[name]
            self.nodes[k]=(s['kind'],nat['addresses'][name],expr(pool[s['lhs']].get('named',{}).get('type')) if s.get('lhs') is not None else None,expr(s.get('guard')),s.get('address_l1'))
        for g in nat['guards']:
            k=self.uid[g['event']];self.guards[k]=g['x']
            if g['x']>=0:self.by_raw[g['x']//2].add(('guard',k,g['x']&1))
        for e in nat['edges']:
            a,b=self.uid[e['from']],self.uid[e['to']]
            if e['kind']=='rf':
                x=e['x'];self.rf[a,b]=x;self.by_raw[x//2].add(('rf',a,b,x&1))
            else:
                need(e['kind'] in ('po','apo') and e['x']==-1,'unsupported_static_theory')
                (self.apo if e['kind']=='apo' else self.po).add((a,b))
        grp={a:{a} for a in self.nodes}
        for a,b in self.apo:
            u=grp[a]|grp[b]
            for x in u:grp[x]=u
        self.group={a:tuple(sorted(g)) for a,g in grp.items()}
        self.direction={g:tuple(sorted((a,b) for a,b in self.apo if a in g)) for g in set(self.group.values())}
        self.domains=collections.defaultdict(list)
        for k,(role,addr,*_) in self.nodes.items():
            if role in ('write','read'):self.domains[addr].append(k)
        self.aliases={k:frozenset(v) for k,v in self.by_raw.items()}
        self.signatures={}
    def signature(self,k):
        if k in self.signatures:return self.signatures[k]
        grp=self.group[k];addr=self.nodes[k][1]
        domain=sorted(self.domains[addr])
        choices=sorted((a,b) for a,b in self.rf if b in domain)
        self.signatures[k]=h([self.nodes[k],grp,self.direction[grp],domain,choices])
        return self.signatures[k]
    def premises(self,clause):
        return {x^1 for x in clause}
    def enabled(self,k,premises):
        g=self.guards.get(k,-2);return g==-1 or g in premises

def derive(graph,raw,names):
    need('evaluation' in raw,'uninstalled_or_unobserved_theory_reason')
    kind,level,goals,values=raw['evaluation']
    clause=raw['clause'];need(clause and len(set(clause))==len(clause) and all(x>=0 and (x^1) not in clause for x in clause),'invalid_signed_clause')
    need(kind!='V' or (level>0 and all(v==1 for _,v,_ in values)),'not_a_dynamic_falsified_conflict')
    need(raw['cause']!='CO','dynamic_CO_unbound')
    need(raw['origin'] in ('reverse_rf','self_cycle','atomic_order_cycle'),'unsupported_conflict_origin')
    def key(i):return graph.uid[names[i]]
    a,b=key(raw['a']),key(raw['b'])
    true=graph.premises(clause)
    lit_guards={key(n) for n,x in raw['G'] if graph.guards.get(key(n))==x and graph.enabled(key(n),true)}
    selected={(key(w),key(r)) for w,r,why in raw['R'] if len(why)==1 and why[0] in true and graph.rf.get((key(w),key(r)))==why[0]}
    reverse=raw['origin']=='reverse_rf'
    if reverse:need(graph.rf.get((b,a)) in true,'counterfactual_RF_not_in_signed_clause')
    # Each proof node establishes a directed event order. Candidate construction has
    # access only to the observed WS/FR recipe log at this occurrence and the active leaves.
    adj=collections.defaultdict(dict);table=[]
    def node(rule,x,y,parents=(),extra=()):
        table.append([rule,x,y,list(parents),list(extra)]);return len(table)-1
    def add(rule,x,y,parents=(),extra=()):
        if y in adj[x]:return
        q=node(rule,x,y,parents,extra);adj[x][y]=q
        if graph.group[x]!=graph.group[y]:
            for l in graph.group[x]:
                for r in graph.group[y]:
                    if r not in adj[l]:adj[l][r]=node('block',l,r,(q,))
    def path(x,y):
        queue=collections.deque([x]);pred={x:None}
        while queue:
            n=queue.popleft()
            for k,ix in adj[n].items():
                if k==y:
                    seq=[ix]
                    while n!=x:
                        n,q=pred[n];seq.append(q)
                    seq.reverse()
                    if len(seq)==1:return seq[0]
                    return node('path',x,y,seq)
                if k not in pred:pred[k]=(n,ix);queue.append(k)
        return None
    for x,y in sorted(graph.po):add('po',x,y)
    for x,y in sorted(graph.apo):add('apo',x,y)
    for w,r in sorted(selected):add('rf',w,r)
    def finish():
        if reverse:
            q=path(a,b)
            if q is None:return None
            r=node('rf',b,a);return node('path',a,a,(q,r))
        q=path(a,b)
        if q is None:return None
        if a==b:return q
        t=path(b,a)
        if t is None:return None
        return node('path',a,a,(q,t))
    final=finish()
    if final is None:
        for num,(which,wi,ri,vi) in enumerate(raw['I']):
            w,r,v=key(wi),key(ri),key(vi)
            if (w,r) not in selected or w==v or w not in lit_guards or v not in lit_guards:continue
            if graph.nodes[w][1]!=graph.nodes[v][1] or graph.nodes[w][0]!='write' or graph.nodes[v][0]!='write':continue
            x,y=(v,r) if which==1 else (w,v)
            q=path(x,y)
            if q is None:continue
            if which==1:add('co',v,w,(q,),(w,r,v,num))
            elif which==2:add('fr',r,v,(q,),(w,r,v,num))
        final=finish()
    need(final is not None,'no_rooted_native_path_at_captured_endpoint')
    out=[];index={}
    def take(i):
        if i not in index:
            rule,x,y,prev,e=table[i];p=[take(j) for j in prev]
            index[i]=len(out);out.append([rule,x,y,p,e])
        return index[i]
    take(final)
    return out

def verify(g,clause,proof):
    true=g.premises(clause);done=[];support=set()
    for rule,a,b,parents,e in proof:
        need(a in g.nodes and b in g.nodes and all(type(i)==int and 0<=i<len(done) for i in parents),'missing_theory_parent_or_event')
        pp=[done[i] for i in parents];support.update((a,b))
        if rule=='po':ok=not pp and (a,b) in g.po
        elif rule=='apo':ok=not pp and (a,b) in g.apo
        elif rule=='rf':ok=not pp and g.rf.get((a,b)) in true
        elif rule=='path':ok=bool(pp) and pp[0][0]==a and pp[-1][1]==b and all(s[1]==t[0] for s,t in zip(pp,pp[1:]))
        elif rule=='block':
            ok=len(pp)==1 and g.group[a]!=g.group[b] and g.group[a]==g.group[pp[0][0]] and g.group[b]==g.group[pp[0][1]]
        elif rule in ('co','fr'):
            need(len(e)==4 and len(pp)==1,'missing_WS_FR_parent');w,r,v,_=e;support.update((w,r,v))
            ok=(w!=v and g.rf.get((w,r)) in true and g.enabled(w,true) and g.enabled(v,true)
                and g.nodes[w][0]==g.nodes[v][0]=='write' and g.nodes[r][0]=='read'
                and g.nodes[w][1] is not None and g.nodes[w][1]==g.nodes[v][1]==g.nodes[r][1])
            ok=ok and ((pp[0]==(v,r) and (a,b)==(v,w)) if rule=='co' else (pp[0]==(w,v) and (a,b)==(r,v)))
        else:ok=False
        need(ok,'invalid_theory_step_'+rule);done.append((a,b))
    need(done and done[-1][0]==done[-1][1],'missing_final_contradiction')
    return support
