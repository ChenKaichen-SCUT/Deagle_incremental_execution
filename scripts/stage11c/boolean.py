"""Replay native 1-UIP and minimization with explicit binary resolution and Boolean input units."""
import array,bisect,collections,sys
from theory import Refused,need,ls
def norm(c):
    v=tuple(sorted(set(c)));need(all((x^1) not in v for x in v),'tautological_resolvent');return v
def resolve(left,right,positive):
    need((positive^1) in left and positive in right,'resolution_pivot_or_polarity')
    return norm([x for x in left if x!=(positive^1)]+[x for x in right if x!=positive])
class Formula:
    def __init__(self,path):
        v=array.array('I');v.frombytes(path.read_bytes())
        if sys.byteorder!='little':v.byteswap()
        self.clauses=[];self.goals=[];self.n=0;i=0
        while i<len(v):
            tag=v[i];i+=1
            if tag==0xfffffff1:self.n+=1;i+=3
            elif tag==0xfffffff4:i+=2
            elif tag==0xfffffff2:pass
            elif tag in (0xfffffff0,0xfffffff3):
                n=v[i];i+=1;c=tuple(v[i:i+n]);i+=n
                if tag==0xfffffff0:self.clauses.append(tuple(sorted(set(c))))
                else:self.goals.append(c)
            else:raise Refused('unknown_stream_record')
        need(len(self.goals)==1,'multi_query_requires_independent_full')
        self.exact={c:i for i,c in enumerate(self.clauses)}
        self.occ=collections.defaultdict(list)
        for i,c in enumerate(self.clauses):
            for x in c:self.occ[x].append(i)
        self.units={};todo=collections.deque()
        def put(x,c):
            if x in self.units:return
            need(x^1 not in self.units,'root_boolean_contradiction_requires_cold')
            self.units[x]=c;todo.append(x)
        for i,c in enumerate(self.clauses):
            if len(c)==1:put(c[0],i)
        while todo:
            x=todo.popleft()
            for i in self.occ[x^1]:
                c=self.clauses[i]
                if any(p in self.units for p in c):continue
                free=[p for p in c if (p^1) not in self.units]
                need(free,'root_boolean_contradiction_requires_cold')
                if len(free)==1:put(free[0],i)
class Proof:
    def __init__(self,formula,theories,learn):
        self.f=formula;self.theories=theories;self.learn=learn;self.nodes=[];self.memo={};self.done={};self.fail={}
    def node(self,k,c,parents=(),data=None):
        c=norm(c);key=(k,c,tuple(parents),data)
        if key in self.memo:return self.memo[key]
        i=len(self.nodes);self.memo[key]=i;self.nodes.append([k,list(c),list(parents),data]);return i
    def res(self,i,j,p):
        return self.node('resolve',resolve(self.nodes[i][1],self.nodes[j][1],p),(i,j),p)
    def original(self,i):return self.node('input',self.f.clauses[i],data=i)
    def unit(self,p):
        k=('unit',p)
        if k in self.memo:return self.memo[k]
        need(p in self.f.units,'missing_root_or_decision_premise')
        j=self.original(self.f.units[p])
        for lit in self.nodes[j][1][:]:
            if lit!=p:j=self.res(j,self.unit(lit^1),lit^1)
        self.memo[k]=j;return j
    def boolean_leaf(self,c):
        n=norm(c)
        if n in self.f.exact:return self.original(self.f.exact[n])
        need(n,'missing_empty_input')
        for i in min((self.f.occ[x] for x in n),key=len):
            orig=self.f.clauses[i];extra=set(orig)-set(n)
            if set(n)<=set(orig) and all((x^1) in self.f.units for x in extra):
                j=self.original(i)
                for x in sorted(extra):j=self.res(j,self.unit(x^1),x^1)
                return j
        raise Refused('original_missing_or_preprocessing_reason_unproved')
    def parent(self,tag,c,limit):
        if tag=='b':return self.boolean_leaf(c)
        if tag.startswith('t'):
            i=int(tag[1:]);need(i in self.theories and norm(c)==norm(self.theories[i]['old_clause']),'missing_native_theory_parent')
            return self.node('theory',c,data=i)
        if tag.startswith('l'):
            i=int(tag[1:]);need(i<limit,'noncausal_learning_reference');d=self.uip(i)
            need(norm(c)==tuple(self.nodes[d][1]),'altered_ancestor_clause');return d
        raise Refused('retired_or_unknown_clause_reason')
    def uip(self,i):
        if i in self.done:return self.done[i]
        if i in self.fail:raise Refused(self.fail[i])
        try:
            l=self.learn[i];chain=l['A'];need(chain and 'L' in l and 'Q' in l,'missing_UIP_observations')
            p,tag,c=chain[0];need(p==-2,'bad_initial_conflict');j=self.parent(tag,c,i)
            for p,tag,c in chain[1:]:j=self.res(j,self.parent(tag,c,i),p)
            # The native analysis omits literals false at decision level zero.
            q=norm(l['Q']);cur=self.nodes[j][1][:]
            need(set(q)<=set(cur),'first_UIP_body_changed')
            for x in cur:
                if x not in q:j=self.res(j,self.unit(x^1),x^1)
            need(tuple(self.nodes[j][1])==q,'wrong_unminimized_clause')
            final=norm(l['L']);need(set(final)<=set(q),'unexpected_minimization')
            budget=0
            while True:
                extras=[x for x in self.nodes[j][1] if x not in final]
                if not extras:break
                # Expand real reasons for minimized literals, ending in the retained cut or in proven roots.
                x=extras[0];t=x^1
                if t in self.f.units:d=self.unit(t)
                else:
                    need(t in l['D'],'missing_minimization_reason');tag,c=l['D'][t]
                    d=self.parent(tag,c,i)
                j=self.res(j,d,t);budget+=1;need(budget<512,'minimization_budget')
            if tuple(self.nodes[j][1])!=final:
                need(set(self.nodes[j][1])<=set(final),'wrong_minimized_clause')
                j=self.node('weaken',final,(j,))
            self.done[i]=j;return j
        except (Refused,RecursionError) as ex:
            self.fail[i]=str(ex) or 'proof_depth_budget';raise Refused(self.fail[i])
    def cone(self,id):
        found=set();todo=[id]
        while todo:
            q=todo.pop()
            if q not in found:found.add(q);todo.extend(self.nodes[q][2])
        return sorted(found)
def replay_dag(nodes,formula,theories):
    for j,(kind,clause,parents,extra) in enumerate(nodes):
        a=tuple(clause);need(a==norm(a) and all(0<=p<j for p in parents),'invalid_DAG')
        if kind=='input':ok=not parents and a==formula.clauses[extra]
        elif kind=='theory':ok=not parents and extra in theories and a==norm(theories[extra])
        elif kind=='resolve':ok=len(parents)==2 and a==resolve(nodes[parents[0]][1],nodes[parents[1]][1],extra)
        elif kind=='weaken':ok=len(parents)==1 and set(nodes[parents[0]][1])<=set(a)
        else:ok=False
        need(ok,'invalid_CDCL_node_'+kind)
