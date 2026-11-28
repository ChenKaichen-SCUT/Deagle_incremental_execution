"""Locate losses in the existing SI wire/connector, without proposing or admitting a correspondence."""
import argparse
from collections import Counter, defaultdict, deque
from functools import lru_cache
import gc
from pathlib import Path

from compact43 import DenseLibrary
from d43_project_support import check, digest
from si1a_census import getmaps, scan
from si1b_catalog import Model, Registry, Wire, U32, signed
from si1b_join import Join, compact_refs
from si1b_review_detail import actual_blocks, bindings, event_differences, wire_coordinates
from si1b_review_space import BASE, CASES, EVIDENCE, jsonlines, read, rows, save, table


class Causes:
    def __init__(self,m):
        self.m=m
        self.s=m.S
        self.e={e[0]:e for e in m.r["E"]}
        self.frame={i:e for i,_,e in m.r["T"]}
        self.owner={i:(self.s[phase],signed(ctx),kind,assign,self.s[lhs]) for i,phase,ctx,kind,assign,lhs in m.r["U"]}
        self.parent=defaultdict(list)
        for p,edge,_,child in m.r["C"]:
            self.parent[child].append((p,edge))
        self.owner_frames=defaultdict(list)
        for o,i in m.r["A"]:
            self.owner_frames[i].append(o)
        self.where={}
        for f,spans in m.w.allocated.items():
            for first,width in spans:
                for v in range(first,first+width):
                    self.where[v]=f
        self.physical=defaultdict(set)
        for i,vs in m.result.items():
            self.physical[i].update(l//2 for l in vs if l>=2)
        for i,rs in m.roles.items():
            for vs in rs.values():
                self.physical[i].update(l//2 for l in vs if l>=2)
        self.grounded=set()
        stack=[i for fs in m.roots.values() if len(compact_refs(m,fs))==1 for i in fs]
        while stack:
            i=stack.pop()
            if i in self.grounded or not m.template[i][1]:
                continue
            self.grounded.add(i)
            for cc in m.children[i].values():
                if len(compact_refs(m,cc))==1:
                    stack.extend(cc)
        self.native_events=defaultdict(list)
        for row in m.r["V"]:
            if row[1]:
                self.native_events[self.s[row[1]]].append(row)
        self.birth={(self.s[n],signed(c),self.s[r]) for n,c,r in m.r["b"]}
        self.x={i:(site,signed(spawn),signed(call),loops[::2]) for i,site,spawn,call,*loops in m.r["X"]}
        self.ir={parts[5]:(parts[0],parts[1],parts[4],parts[6]) for parts in m.r["I"]}
        self.ports=defaultdict(list)
        for w,r,raw,installed in m.r["H"]:
            l=m.w.lit(raw)
            if l>=2:self.ports[l//2].append(("RF",l,self.s[w],self.s[r],installed))
        for e,raw in m.r["G"]:
            l=m.w.lit(raw)
            if l>=2:self.ports[l//2].append(("Guard",l,self.s[e]))
        self.named=defaultdict(list)
        for name,t,*vs in m.r["B"]:
            for bit,r in enumerate(vs):
                l=m.w.lit(r)
                if l>=2 and t and not m.lane(t,bit):
                    self.named[l//2].append((self.s[name],m.layout.get(t),bit,l))
        self.ops={"not","and","or","xor","nor","nand","implies","=","notequal","if","+","-","*","/","mod","<","<=",">",
                  ">=","typecast","extractbit","extractbits","bitand","bitor","bitxor","index","shl","lshr","ashr","unary-","unary+","with"}

    @lru_cache(None)
    def expression(self,e):
        m=self.m
        i,op,t,n,v,attr,*kids=self.e[e]
        op,name=self.s[op],self.s[n]
        kind=m.reg.rows[m.shapes[t]][1]
        base={"id":i,"op":op,"type":kind}
        if m.expr[i]:
            return {**base,"reason":"certified"}
        if name:base["name"]=name
        if op in ("symbol","nondet_symbol"):
            base["producer_present"]=bool(m.symbols.get(name) or m.rf_names.get(name))
            base["reason"]="symbol_type_or_layout" if base["producer_present"] else "no_symbol_producer"
        elif op=="constant":
            base["reason"]="constant_nonscalar"
        elif op not in self.ops:
            base["reason"]="unsupported_operator"
        elif kind not in ("bool","signedbv","unsignedbv","c_bool"):
            base["reason"]="nonscalar_result"
        elif kids and not all(m.expr[c] for c in kids):
            base["reason"]="all_values_failed"
            base["children"]=[[c,bool(m.expr[c])] for c in kids]
            base["first_failed_child"]=self.expression(next(c for c in kids if not m.expr[c]))
        else:
            base["reason"]="empty_operand_list"
        return base

    @lru_cache(None)
    def context(self,ctx):
        m=self.m
        if ctx in m.contexts:
            return {"reason":"certified","context":ctx}
        if ctx not in self.x:
            return {"reason":"no_execution_record","context":ctx}
        site,spawn,caller,loops=self.x[ctx]
        detail={"context":ctx,"site":site,"source_site":m.site_rows.get(site)}
        if site not in m.sites:
            data=self.ir.get(site)
            detail["native_site_origin"]=data
            if data:
                file,line,token,origin=data
                detail["reason"]="site_token_missing" if self.s[file] in m.source and not token else (
                    "site_lowering_origin_missing" if not m.origins.get(origin) else "duplicate_or_unsourced_site")
            else:detail["reason"]="absent_site"
        elif any(x not in m.sites for x in loops):
            detail.update(reason="loop_site_missing",failed_loop=next(x for x in loops if x not in m.sites))
        elif spawn not in m.contexts or caller not in m.contexts:
            parent=spawn if spawn not in m.contexts else caller
            detail.update(reason="parent_execution_missing",parent=self.context(parent))
        else:detail["reason"]="duplicate_execution_key"
        return detail

    @lru_cache(None)
    def event(self,name):
        m=self.m
        if name in m.events:
            return {"event":name,"key":m.events[name],"reason":"certified"}
        states=[]
        for sym,_,ctx,role,obj,base,t,glob in self.native_events[name]:
            sym,role,obj,base=map(self.s.__getitem__,(sym,role,obj,base))
            ctx=signed(ctx)
            desc={"producer":sym,"role":role,"ctx":ctx,"base":base}
            if ctx!=-2 and sym and (sym,ctx,role) not in self.birth:
                desc["reason"]="SSA_birth_missing"
            elif not (ctx==-2 and glob or ctx in m.contexts):
                desc.update(reason="execution_missing",execution=self.context(ctx))
            elif obj and m.object_path(obj,base) is None:
                desc.update(reason="source_declaration_or_object_path_missing",base_declared=base in m.decls)
            elif not obj and role not in ("spawn","fence"):
                desc["reason"]="missing_object_designator"
            else:
                desc["reason"]="nonunique_event_key_or_alias"
            states.append(desc)
        return {"event":name,"reason":states[0]["reason"] if states else "no_event_producer","producers":states}

    def port_details(self,v):
        result=[]
        for role,lit,*parts in self.ports[v]:
            events=parts[:2] if role=="RF" else parts
            r=dict(role=role,signed_literal=lit,events=[self.event(name) for name in events])
            if role=="RF":r["installed_match"]=parts[2]
            result.append(r)
        return result

    @lru_cache(None)
    def route(self,frame):
        """Find one actual native owner chain, retaining failed roots and unnumbered edges as observations only."""
        todo=deque([(frame,())]);seen=set()
        while todo:
            f,path=todo.popleft()
            if f in seen:continue
            seen.add(f)
            if self.owner_frames[f]:
                choices=[]
                for o in self.owner_frames[f]:
                    phase,ctx,kind,assign,lhs=self.owner[o]
                    choices.append(dict(id=o,phase=phase,ctx=ctx,lhs=lhs,ctx_ok=bool(self.m.contexts.get(ctx)),
                                        lhs_ok=not lhs or lhs in self.m.symbols))
                return {"native_root":f,"root_expression":self.expression(self.frame[f]),"owners":choices,
                        "ancestor_edges":path}
            for p,e in self.parent[f]:
                todo.append((p,(*path,(p,e))))
        return {"native_root":None}


def historical_frames(out, models, causes, lost, used, categories, mu):
    """Attribute already lost atoms to existing local routes. Never use this diagnostic to form a map."""
    left,right=causes
    m=models[0]
    bad_roots=set()
    for frame,owners in left.owner_frames.items():
        if not m.template[frame][1] and any(m.contexts.get(ctx) and (not lhs or lhs in m.symbols)
                for _,ctx,_,_,lhs in (left.owner[o] for o in owners)):
            bad_roots.add(frame)
    # Native, uniquely numbered template edges. Ignore expression certification on this walk only to locate barriers.
    visited=set();todo=list(bad_roots)
    while todo:
        frame=todo.pop()
        if frame in visited:continue
        visited.add(frame)
        for cs in m.children[frame].values():
            if len(cs)==1 or len(compact_refs(m,cs))==1:todo.extend(cs)
    stats=Counter()
    for v in lost & used:
        if categories[v]!="auxiliary":continue
        y=mu[v];f=left.where.get(v);g=right.where.get(y//2)
        stats["lost"]+=1
        if f in visited:stats["raw_route_from_owner_valid_root_with_failed_expression"]+=1
        if f is None or g is None:continue
        same=m.template[f][1] and m.template[f]==models[1].template[g]
        if same:
            stats["both_allocating_frames_share_complete_typed_expression"]+=1
            if f not in left.grounded:stats["same_local_expression_but_P0_route_missing"]+=1
            if f in visited:stats["same_local_expression_under_bad_root"]+=1
            ls=m.roles[f];rs=models[1].roles[g]
            if any(len(values)==len(rs.get(role,()))==1 and any(l>=2 and l//2==v and (y^(l&1)) in rs[role] for l in values)
                   for role,values in ls.items()):
                stats["also_same_single_valued_native_role_and_signed_literals"]+=1
    save(out/"historical-frame-check.json",dict(diagnostic_uses_A_to_locate_peer=True,
        applied_to_transport=False,overlapping_counts=stats))


def diagnose(case,root,tmp,out):
    si=EVIDENCE/"si1b"/case
    old=root/"matrix"/case/"compact/P0/native"
    prod=root/"matrix"/case/"compact-reuse/P1/native"
    mu,pre=getmaps(prod)
    exact={int(r["ordinal"]):r for r in rows(root/"exact"/case/"actual-mu-births.tsv")}
    lib=DenseLibrary((old/"dense.bin").read_bytes())
    detail={}
    probe=EVIDENCE/"si1a/probe"/(case+"-P0.tsv.gz")
    check(digest(probe)==read(probe.with_suffix("").with_suffix(".json"))["trace_sha256"],"historical native allocation trace")
    scan(case,"P0",old/"model.tsv",probe,lib,mu[0],pre[0],exact,detail)
    del exact,lib,pre
    source=si/"source"
    doc=read(source/"source-catalog.json")
    reg=Registry()
    ms=[Model(Wire(tmp/case/"witness"/f"P{i}",source),reg,doc,i) for i in range(2)]
    join=Join(*ms).run()
    check(join.mu=={int(r["old_variable"]):int(r["positive_image"]) for r in rows(si/"join/direct-map.tsv.gz")},"B join differs")
    models=[Causes(m) for m in ms]
    a,b=models
    visited={i for i,j in join.seen_templates}
    categories=detail["categories"]; used=detail["scopes"]["used_union"]
    seen=Counter(); main=defaultdict(Counter); examples={}; event_counts=Counter()
    lost={v for v in mu[0] if mu[0][v]>=2 and v not in join.mu}
    if case=="fib-snapshot-11":historical_frames(out,ms,models,lost,used,categories,mu[0])
    wire_coordinates(si,out,ms)
    bindings(si,out,ms,used)
    event_differences(out,ms,models,lost,used,categories,mu[0])
    actual_blocks(si,out,ms,models,join,used,mu[0],categories)
    atom_rows=rows(si/"join/P0-atoms.tsv.gz")
    with table(out/"lost-atoms.tsv.gz","old A_positive used permanent_conclusion category allocation opcode SI_reason cache_missing frame local_expression route physical_value local_block") as store, jsonlines(out/"lost-theory-ports.jsonl.gz") as ports:
        for r in atom_rows:
            v=int(r["variable"])
            if v not in lost:continue
            cat=categories[v]; y=mu[0][v]; isused=v in used; perm=v in detail["scopes"]["permanent_conclusion"]
            alloc,op=detail["allocation"][v]
            reason=r["reason"];frame=a.where.get(v,0)
            exp=a.expression(a.frame[frame]) if frame else {"reason":"outside_native_frame"}
            route=("outside_native_frame" if not frame else "local_expression_failed" if not ms[0].template[frame][1] else
                   "no_certified_local_root_path" if frame not in a.grounded else "no_paired_frame_visit" if frame not in visited else
                   "visited_local_frame")
            physical=int(v in a.physical.get(frame,()))
            blocked="|".join(sorted(ms[0].block.get(v,()))) or "-"
            store([v,y,int(isused),int(perm),cat,alloc,op,reason,r["missing_cache_role"],frame,exp["reason"],route,physical,blocked])
            if not isused:continue
            seen[cat]+=1
            for label,value in (("reason",reason),("route",route),("local_expression",exp["reason"]),("native_port_block",blocked),
                                ("physical_value",str(physical)),("cache_missing",r["missing_cache_role"]),("site",alloc+" "+op)):
                main[cat+"/"+label][value]+=1
            base=dict(old=v,A_positive=y,category=cat,allocation=[alloc,op],SI_reason=reason,
                      local_native_block=blocked,native_frame=frame,expression=exp,route=route,physical_value=physical)
            if cat in ("RF","Guard"):
                info=dict(**base,P0_roles=a.port_details(v),P1_roles=b.port_details(y//2),
                          signed_P0_blocks=sorted(ms[0].interface.get(v,())),signed_P1_blocks=sorted(ms[1].interface.get(y//2,())))
                # Count each old atom once by the set of immediate event causes across both endpoints and versions.
                causes=sorted({e["reason"] for s in ("P0_roles","P1_roles") for p in info[s] for e in p["events"] if e["reason"]!="certified"})
                label=cat+"/"+("|".join(causes) or "endpoints_certified")
                event_counts[label]+=1
                ports(info);examples.setdefault(label,info)
            labels={cat+"/reason/"+reason,cat+"/route/"+route,cat+"/expression/"+exp["reason"],cat+"/site/"+alloc+" "+op}
            if "LAYOUT_INCOMPATIBLE" in reason:labels.add("layout/"+("local" if a.named.get(v) else "peer_or_component"))
            for name in sorted(labels):
                if name not in examples:
                    examples[name]=dict(**base,P0_layout_blocked_named_views=a.named.get(v,()),P1_layout_blocked_named_views=b.named.get(y//2,()),
                        template_result=ms[0].result.get(frame),typed_roles_for_atom=[[k,sorted(vals)] for k,vals in ms[0].roles.get(frame,{}).items()
                            if any(l>=2 and l//2==v for l in vals)],raw_owner_route=a.route(frame) if frame else None)
    frozen=[r for r in rows(si/"audit/coverage.tsv") if r["side"]=="P0" and r["scope"]=="used_union"]
    check(all(int(r["lost"])==seen[r["category"]] for r in frozen),"lost categories differ")
    save(out/"loss-summary.json",dict(all_old_matches_lost=len(lost),UsedLeaf_old_matches_lost=seen,
         exclusive_breakdowns_per_measure=main,interface_missing_event_reasons=event_counts,source_counts=[m.reasons for m in ms]))
    save(out/"loss-examples.json",examples)
    print(case,dict(seen),flush=True)
    for method in (Causes.route,Causes.expression,Causes.context,Causes.event):method.cache_clear()


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for n in ("d43d_restored","scratch","output"):p.add_argument(n,type=Path)
    p.add_argument("--case",choices=CASES,action="append")
    arg=p.parse_args()
    for name in arg.case or CASES:
        diagnose(name,arg.d43d_restored,arg.scratch,arg.output/name)
        gc.collect()
