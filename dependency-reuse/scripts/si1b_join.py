"""Direct signed join over two sealed native catalogs. No old map, CNF matching, or solver input."""
import argparse
from array import array
from collections import Counter, defaultdict, deque
import gzip
import hashlib
import json
from pathlib import Path
import resource
import time

from si1b_catalog import Model, Registry, Wire, check, sha

def local_shape(m,i):
    # Coalesce independent no-cache leaf visits only when ALL local role payloads agree.
    return (m.template[i],m.result[i],tuple(sorted((k,tuple(sorted(v))) for k,v in m.roles[i].items())),
            tuple(sorted((k,tuple(sorted(v))) for k,v in m.children[i].items())))
def compact_refs(m,refs):
    choices={}
    for i in sorted(refs):choices.setdefault(local_shape(m,i),i)
    return list(choices.values())
def descendants(m,refs):
    todo=list(refs);seen=set();lits=set()
    while todo:
        i=todo.pop()
        if i in seen:continue
        seen.add(i);lits.update(m.result[i])
        for vals in m.roles[i].values():lits.update(vals)
        for children in m.children[i].values():todo.extend(children)
    return lits

def cache_metrics(m):
    # Each (native template, local owner) incurs one logical expansion, irrespective of multiple paths.
    users=defaultdict(int);nexts=defaultdict(set);indeg=Counter()
    for own,i in m.r["A"]:users[i]|=1<<own
    for parent,edge,domain,child in m.r["C"]:
        if edge==0xffffffff:continue
        if child not in nexts[parent]:nexts[parent].add(child);indeg[child]+=1
    q=deque(i for i in m.template if not indeg[i]);count=0
    while q:
        p=q.popleft();count+=1
        for c in nexts[p]:
            users[c]|=users[p];indeg[c]-=1
            if not indeg[c]:q.append(c)
    check(count==len(m.template),"cyclic cache template evidence")
    missing=set();unanchored=set();hits=dict(m.r["h"]);before=after=physical=0
    for i,lits in m.result.items():
        size=len(lits)+sum(len(v) for v in m.roles[i].values())
        n=users[i].bit_count()
        before+=size*bool(n);after+=size*n;physical+=size
        if i not in hits:continue
        recorded={l//2 for l in lits if l>=2}
        for vals in m.roles[i].values():recorded.update(l//2 for l in vals if l>=2)
        for a,w in m.w.allocated[i]:
            missing.update(v for v in range(a,a+w) if v not in recorded)
        if i in m.bad_child:unanchored.update(recorded)
    # A cache hit may expose a nested role from a different owner. Count that physical value once.
    children=defaultdict(set)
    for parent,edge,domain,child in m.r["C"]:children[parent].add(child)
    def reachable(seeds,certified):
        seen=set();todo=list(seeds)
        while todo:
            i=todo.pop()
            if i in seen or certified and not m.template[i][1]:continue
            seen.add(i)
            if certified:
                for refs in m.children[i].values():
                    if len(refs)==1 or len(compact_refs(m,refs))==1:todo.extend(refs)
            else:todo.extend(children[i])
        return seen
    cached=reachable(hits,False)
    grounded=reachable((i for refs in m.roots.values() for i in refs if len(refs)==1 or len(compact_refs(m,refs))==1),True)
    m.cache_descendants=set()
    for i in cached:
        values={l//2 for l in m.result[i] if l>=2}
        for role in m.roles[i].values():values.update(l//2 for l in role if l>=2)
        allocated={v for first,width in m.w.allocated[i] for v in range(first,first+width)}
        m.cache_descendants.update(values|allocated)
        missing.update(allocated-values)
        if i not in grounded:unanchored.update(values|allocated)
    m.cache_missing=missing;m.cache_orphan=unanchored
    return dict(templates=len(m.template),explicit_role_positions=sum(map(len,m.roles.values())),
                physical_value_entries=physical,logical_first_owner_entries=before,logical_all_owner_entries=after,
                additional_owner_role_bindings=after-before,unique_owner_template_associations=sum(x.bit_count() for x in users.values()),
                shared_child_references=len(m.r["C"]),unique_native_owner_roots=len(m.r["A"]),
                cache_hits=sum(hits.values()),reused_templates=len(hits),reused_uncaptured_allocations=len(missing),
                uncertified_cached_path_values=len(unanchored),cache_descendant_atoms=len(m.cache_descendants))

class Join:
    def __init__(self,a,b):
        check(a.reg is b.reg and a.w.abi==b.w.abi and a.w.seal["elf"]==b.w.seal["elf"],"configuration mismatch")
        self.a,self.b=a,b;self.k=a.k
        self.n=a.w.n;self.count=self.n+b.w.n
        self.parent=array("I",range(self.count));self.size=array("I",[1])*self.count
        self.issues=defaultdict(set);self.edges={};self.reasons=Counter();self.counts=Counter()
        self.seen_templates=set();self.mu={};self.denied={};self.bad_by_side=[{},{}]
    def root(self,v):
        while self.parent[v]!=v:
            self.parent[v]=self.parent[self.parent[v]];v=self.parent[v]
        return v
    def union(self,x,y):
        a,b=self.root(x),self.root(y)
        if a==b:return
        if self.size[a]<self.size[b]:a,b=b,a
        self.parent[b]=a;self.size[a]+=self.size[b]
    def nodes(self,va,vb):
        return {l//2 for l in va if l>=2}|{self.n+l//2 for l in vb if l>=2}
    def taint(self,reason,nodes):
        if not nodes:return
        first=next(iter(nodes))
        for p in nodes:
            self.union(first,p);self.issues[p].add(reason)
    def propose(self,key,old,new):
        if len(old)>1 or len(new)>1:
            self.taint("SAME_KEY_MULTIBIND",self.nodes(old,new))
        if not old or not new:return
        if any(l<0 for l in old|new) and any(l>=2 for l in old|new):
            self.taint("CONSTANT_VARIABLE_CHANGE",self.nodes(old,new))
        for x in old:
            if x<2:continue
            for y in new:
                if y<2:continue
                v=x//2;p=y^(x&1)
                self.union(v,self.n+p//2)
                self.edges.setdefault((v,p),key)
                self.counts["shared_signed_proposals"]+=1
    def paired_refs(self,witness,aa,bb,todo):
        aa=compact_refs(self.a,aa);bb=compact_refs(self.b,bb)
        if len(aa)>1 or len(bb)>1:
            self.taint("SAME_KEY_MULTIBIND",self.nodes(descendants(self.a,aa),descendants(self.b,bb)));return
        if aa and bb:todo.append((witness,aa[0],bb[0]))
    def run(self):
        started=time.monotonic_ns()
        a,b=self.a,self.b
        self.cache=[cache_metrics(m) for m in (a,b)]
        for side,m in enumerate((a,b)):
            off=self.n if side else 0
            for v,why in m.block.items():self.issues[off+v].update(why)
            for children in m.children.values():
                for refs in children.values():
                    if len(refs)>1 and len(compact_refs(m,refs))>1:
                        self.taint("SAME_KEY_MULTIBIND",{off+x//2 for x in descendants(m,refs) if x>=2})
            for vals in m.bind.values():
                if len(vals)>1:self.taint("SAME_KEY_MULTIBIND",{off+x//2 for x in vals if x>=2})
            for i,items in m.roles.items():
                for vals in items.values():
                    if len(vals)>1:self.taint("SAME_KEY_MULTIBIND",{off+x//2 for x in vals if x>=2})
        for key in sorted(a.bind.keys() & b.bind.keys()):self.propose(key,a.bind[key],b.bind[key])
        todo=[]
        for key in sorted(a.roots.keys()|b.roots.keys()):
            self.paired_refs(key,a.roots.get(key,()),b.roots.get(key,()),todo)
        while todo:
            witness,i,j=todo.pop()
            if (i,j) in self.seen_templates:continue
            self.seen_templates.add((i,j))
            if a.template[i]!=b.template[j] or not a.template[i][1]:continue
            left,right=a.result[i],b.result[j]
            if len(left)!=len(right):continue
            for bit,(l,r) in enumerate(zip(left,right)):
                self.propose(self.k("returned",witness,bit,len(left)),{l},{r})
            for role in sorted(a.roles[i].keys() & b.roles[j].keys()):
                self.propose(self.k("lowering-role",witness,role),a.roles[i][role],b.roles[j][role])
            for edge in sorted(a.children[i].keys()|b.children[j].keys()):
                self.paired_refs(self.k("operand",witness,edge),a.children[i].get(edge,()),
                                 b.children[j].get(edge,()),todo)
        old=defaultdict(set);new=defaultdict(set);signs=defaultdict(set)
        for v,peer in self.edges:
            target=peer//2;sign=peer&1;old[v].add(target);new[target].add(v);signs[v,target].add(sign)
            l=a.interface.get(v,set());r=b.interface.get(target,set())
            if l or r:
                if not all(k for _,k,_ in l|r) or {(role,k,f^sign) for role,k,f in l}!=r:
                    self.issues[v].add("THEORY_ORDINARY_CONFLICT")
        for v,vs in old.items():
            if len(vs)>1:self.issues[v].add("ONE_TO_MANY")
        for v,vs in new.items():
            if len(vs)>1:self.issues[self.n+v].add("MANY_TO_ONE")
        for (x,y),s in signs.items():
            if len(s)>1:self.issues[x].add("POLARITY_CONFLICT")
        clusters=defaultdict(set)
        for v,reasons in self.issues.items():clusters[self.root(v)].update(reasons)
        for v,peer in self.edges:
            if self.root(v) not in clusters:self.mu[v]=peer
        check(len({p//2 for p in self.mu.values()})==len(self.mu),"non-injective signed map")
        for side,m in enumerate((a,b)):
            off=self.n if side else 0
            for v in range(1,m.w.n):
                why=clusters.get(self.root(off+v))
                if why:self.bad_by_side[side][v]=tuple(sorted(why))
        self.counts.update(accepted=len(self.mu),unique_signed_proposals=len(self.edges),
                           visited_template_pairs=len(self.seen_templates),rejected_components=len(clusters))
        self.elapsed=time.monotonic_ns()-started
        return self

def dispositions(joined,side):
    m=(joined.a,joined.b)[side]
    supported=set(joined.mu if not side else (v//2 for v in joined.mu.values()))
    named={l//2 for vals in m.bind.values() for l in vals if l>=2}
    local={l//2 for vals in m.result.values() for l in vals if l>=2}
    local.update(l//2 for roles in m.roles.values() for group in roles.values() for l in group if l>=2)
    cache_atoms=set()
    for i,_ in m.r["h"]:
        for first,width in m.w.allocated[i]:cache_atoms.update(range(first,first+width))
        cache_atoms.update(x//2 for x in m.result[i] if x>=2)
        for vals in m.roles[i].values():cache_atoms.update(x//2 for x in vals if x>=2)
    malformed=m.cache_missing|m.cache_orphan
    for v in range(1,m.w.n):
        reasons=joined.bad_by_side[side].get(v,())
        if v in supported:state="bound";why="COMMON_CERTIFIED_PORT"
        elif reasons:
            ambiguous=any(x in reasons for x in ("SAME_KEY_MULTIBIND","ONE_TO_MANY","MANY_TO_ONE","POLARITY_CONFLICT"))
            state="ambiguous" if ambiguous else "unsupported";why="|".join(reasons)
        else:
            state="unsupported"
            if v in malformed:why="CACHED_INTERNAL_ORIGIN_MISSING"
            elif v in named:why="NO_SHARED_CERTIFIED_PORT"
            elif v in local:why="UNCERTIFIED_OWNER_RECIPE_OR_PEER"
            else:why="UNSUPPORTED_ORIGIN"
        yield v,state,why,int(v in cache_atoms),int(v in malformed),int(v in m.cache_descendants)

def write_gzip(path,text):
    with path.open("wb") as out,gzip.GzipFile(fileobj=out,filename="",mode="wb",mtime=0) as f:
        f.write(text.encode())
def pipeline(folders,source_path,out,sides=(0,1)):
    start=time.monotonic_ns();source=json.loads((source_path/"source-catalog.json").read_bytes());reg=Registry()
    models=[]
    for folder,side in zip(folders,sides):
        w=Wire(folder,source_path)
        check(sha(source_path/f"P{side}.tokens")==w.seal["tokens"],"token file integrity")
        models.append(Model(w,reg,source,side))
    joined=Join(*models).run()
    if out:
        out.mkdir(parents=True,exist_ok=True)
        data=["old_variable\tpositive_image\twitness_key\n"]
        data.extend("%d\t%d\t%d\n"%(v,p,joined.edges[v,p]) for v,p in sorted(joined.mu.items()))
        write_gzip(out/"direct-map.tsv.gz","".join(data))
        write_gzip(out/"typed-keys.json.gz",json.dumps(reg.rows,ensure_ascii=False,separators=(",",":"))+"\n")
        for side,m in enumerate(models):
            lines=["variable\tstate\treason\tcached_direct_atom\tmissing_cache_role\tcached_descendant_atom\n"]
            lines.extend("%d\t%s\t%s\t%d\t%d\t%d\n"%item for item in dispositions(joined,side))
            write_gzip(out/f"P{side}-atoms.tsv.gz","".join(lines))
            write_gzip(out/f"P{side}-ir.json.gz",json.dumps(dict(declarations=m.decls,sites=m.sites,
                    contexts=m.contexts,event=m.events,source_sites=m.site_rows),ensure_ascii=False,separators=(",",":"))+"\n")
        timing=dict(read_validate_ns=[m.w.read_ns for m in models],source_ir_finalize_ns=[m.source_ns for m in models],
                    port_template_read_index_ns=[m.catalog_ns for m in models],join_conflict_ns=joined.elapsed,
                    process_to_outputs_ns=time.monotonic_ns()-start,process_peak_RSS_KiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        (out/"join.json").write_text(json.dumps(dict(timing=timing,join=joined.counts,cache=joined.cache,
               sources=[m.reasons for m in models],digest=sha(out/"direct-map.tsv.gz")),indent=2)+"\n")
    return joined

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("p0","p1","source","out"):p.add_argument(key,type=Path)
    a=p.parse_args();pipeline([a.p0,a.p1],a.source,a.out)
