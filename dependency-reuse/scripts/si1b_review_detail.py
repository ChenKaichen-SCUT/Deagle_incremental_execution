"""Resolve connector failures and the signed witnesses attached to new ordinary correspondences."""
from collections import Counter, defaultdict
from functools import lru_cache
import gzip
import json

from d43_project_support import check
from si1b_join import compact_refs, descendants
from si1b_review_space import jsonlines, read, rows, save, table
from si1b_witness import Reader, immutable


def wire_coordinates(si,out,models):
    result={}
    for side,m in enumerate(models):
        ver=f"P{side}"
        base=si/"passive"/ver
        receipt=read(base/"receipt.json")
        original,shadow=receipt["original"],receipt["shadow"]
        check(all(original[k]==shadow[k] for k in ("rows","ordered_outside_guard","guard_hits_by_named_event","guard_hits",
              "guard_events","cache_instances","scope_streams")) and all(original["streams"][k]==v for k,v in shadow["streams"].items() if k!="K"),
              "shadow and default native observations disagree")
        check(m.w.allocation_hash==original["allocation_ranges"],"allocation stream changed")
        ports=defaultdict(set)
        for sym,t,*raw in m.r["B"]:
            for bit,lit in enumerate(raw):ports[m.S[sym],bit].add(m.w.lit(lit))
        rf=Counter((m.S[w],m.S[r],m.w.lit(l)) for w,r,l,ok in m.r["H"])
        guards=Counter((m.S[e],m.w.lit(l)) for e,l in m.r["G"])
        original_rf=Counter();original_guards=Counter();n=0
        with gzip.open(base/"original.tsv.gz","rt") as f:
            for line in f:
                if line.startswith("A\t"):
                    _,name,t,bit,l=line.rstrip().split("\t")
                    check(int(l) in ports[name,int(bit)],"unbound native Boolean port")
                    n+=1
                elif line.startswith("EDGE\trf\t"):
                    _,_,w,r,l,*_=line.split()
                    original_rf[w,r,int(l)]+=1
                elif line.startswith("GUARD\t"):
                    _,e,l=line.split()
                    original_guards[e,int(l)]+=1
        check(original_rf==rf and original_guards==guards and n==original["rows"]["A"],"installed named theory port mismatch")
        result[ver]=dict(native_variable_count=m.w.n-1,signed_B_port_rows=n,RF_rows=rf.total(),Guard_rows=guards.total(),
                         allocation_sha256=m.w.allocation_hash,first_root_native_streams_equal=True)
    save(out/"wire-coordinates.json",result)


def bindings(si,out,models,used):
    with gzip.open(si/"join/typed-keys.json.gz","rt") as f:
        keys=[immutable(x) for x in json.load(f)]
    check(keys==models[0].reg.rows,"wire registry differs from sealed witness keys")
    readers=[Reader(m,keys) for m in models]
    with table(out/"added-witnesses.tsv.gz","old positive_image UsedLeaf typed_key port_kind local_P0_literal local_P1_literal P0_frames P1_frames") as put:
        for row in rows(out/"composition.tsv.gz"):
            if row["decision"]!="added_certified_ordinary":
                continue
            v,p,k=map(int,(row["old"],row["B_positive"],row["typed_key"]))
            left,right=[x.values(k) for x in readers]
            check(len(left)==len(right)==1,"ambiguous witness")
            l,r=next(iter(left)),next(iter(right))
            check(l//2==v and r^(l&1)==p,"signed witness")
            label=keys[k][0]
            if label=="lowering-role":label+="/"+keys[k][2][1]
            put([v,p,int(v in used),k,label,l,r,*[",".join(map(str,sorted(rd.recipe(k)))) for rd in readers]])


def event_differences(out,models,cs,lost,used,categories,mu):
    left,right=cs
    registry=models[0].reg.rows
    def field(row):
        return list(row) if isinstance(row,tuple) else row
    @lru_cache(None)
    def trace(x,y):
        if not x or not y:return ("missing_endpoint",None)
        if x==y:return ("same",None)
        a,b=registry[x],registry[y]
        descriptions={"producer":("context","role","object","type","storage"),"occurrence":("spawn","caller","loops","site"),
                      "site":("function","location","lowering","operation"),"lower":("parent","location","function","role"),
                      "decl":("location","function","base","is_type","parameter"),"token":("file","lineage"),
                      "native-library":("binary","file","line","column")}
        refs={"producer":{1,4},"occurrence":{1,2,4},"site":{2,3},"lower":{1,2},"decl":{1}}
        if a[0]!=b[0]:return ("key_kind",(a[0],b[0]))
        for i,(av,bv) in enumerate(zip(a[1:],b[1:]),1):
            if av==bv:continue
            path=a[0]+"."+descriptions.get(a[0],tuple(str(j) for j in range(1,len(a))))[i-1]
            if i in refs.get(a[0],set()) and av and bv:
                child,values=trace(av,bv)
                return (path+"/"+child,values)
            return (path,(field(av),field(bv)))
        return ("arity",(len(a),len(b)))
    def loc(c,name):
        result=[]
        for sym,_,ctx,r,_,base,_,_ in c.native_events[name]:
            ctx=ctx if ctx<2**31 else ctx-2**32
            site=c.x.get(ctx,(None,))[0]
            result.append(dict(context=ctx,site=site,location=c.m.site_rows.get(site),symbol=c.s[sym],role=c.s[r],base=c.s[base]))
        return result
    totals=Counter();examples={};cache={};cross=Counter()
    with jsonlines(out/"interface-divergences.jsonl.gz") as write:
        for v in sorted(lost&used):
            role=categories[v]
            if role not in ("RF","Guard"):continue
            p=mu[v]
            ls=left.ports[v];rs=right.ports[p//2]
            raw=[{(k,t,f^(p&1)) for k,t,f in models[0].interface.get(v,())},models[1].interface.get(p//2,set())]
            equal=raw[0]==raw[1] and all(t for _,t,_ in raw[0]|raw[1])
            differences=set()
            for row in ls:
                kind=row[0];enames=row[2:4] if kind=="RF" else row[2:3]
                choices=[q for q in rs if q[0]==kind and q[1]==row[1] and q[2:2+len(enames)]==enames]
                if not choices:choices=[q for q in rs if q[0]==kind and (row[1]&1)^(p&1)==q[1]&1 and q[2:2+len(enames)]==enames]
                if not choices:choices=[q for q in rs if q[0]==kind and ((row[1]&1)^(p&1))==(q[1]&1)]
                if len(choices)!=1:
                    differences.add("ambiguous_installed_port_pair");continue
                other=choices[0]
                for n,m in zip(enames,other[2:2+len(enames)]):
                    k0=models[0].events.get(n,0);k1=models[1].events.get(m,0)
                    path,values=trace(k0,k1)
                    if path=="same":continue
                    differences.add(path)
                    pair=(n,m)
                    if pair not in cache:
                        cache[pair]=len(cache)+1
                        write(dict(event_pair_id=cache[pair],example_old_atom=v,example_A_positive=p,P0=n,P1=m,keys=[k0,k1],
                                   first_differing_field=path,first_differing_values=values,
                                   local_certification=[left.event(n),right.event(m)],P0_source=loc(left,n),P1_source=loc(right,m)))
                    examples.setdefault(role+"/"+path,dict(old=v,A_positive=p,P0_event=n,P1_event=m,event_pair_id=cache[pair],field=path,
                                                           values=values,P0_source=loc(left,n),P1_source=loc(right,m)))
            label=role+"/"+("|".join(sorted(differences)) or "no_endpoint_difference")
            totals[label]+=1
            cross[(role,"equal_all_signed_roles" if equal else "different_or_incomplete_roles")]+=1
    save(out/"interface-summary.json",dict(atoms_by_first_differing_fields=totals,
         signed_role_test={"/".join(k):n for k,n in cross.items()},examples=examples))


def multibind_source(join,old_var):
    root=join.root(old_var);samples=[]
    for side,m in enumerate((join.a,join.b)):
        off=join.n if side else 0
        def in_comp(l):return l>=2 and join.root(off+l//2)==root
        def inspect(kind,key,refs):
            ids=compact_refs(m,refs)
            if len(ids)<2:return
            values=sorted(l for l in descendants(m,refs) if in_comp(l))
            if values:
                samples.append(dict(side=side,kind=kind,key=key,frames=ids[:8],component_literal_sample=values[:8],
                                    distinct_frames=len(ids),result_sample=[m.result[i][:8] for i in ids[:2]]))
        for k,rs in m.roots.items():inspect("same_root",k,rs)
        for parent,edges in list(m.children.items()):
            for e,rs in edges.items():inspect("same_operand",[parent,e],rs)
        for k,vs in m.bind.items():
            if len(vs)>1 and any(map(in_comp,vs)):samples.append(dict(side=side,kind="bound_key",key=k,values=sorted(vs)))
        for i,roles in m.roles.items():
            for k,vs in roles.items():
                if len(vs)>1 and any(map(in_comp,vs)):samples.append(dict(side=side,kind="local_role",frame=i,key=k,values=sorted(vs)))
    return samples


def actual_blocks(si,out,models,cs,join,used,mu,categories):
    count=Counter();samples={};layout_names=Counter()
    for r in rows(si/"join/P0-atoms.tsv.gz"):
        v=int(r["variable"])
        if v not in used:continue
        for reason in r["reason"].split("|"):
            if reason not in {"SAME_KEY_MULTIBIND","POLARITY_CONFLICT","CONSTANT_VARIABLE_CHANGE","ONE_TO_MANY","MANY_TO_ONE",
                              "THEORY_ORDINARY_CONFLICT","LAYOUT_INCOMPATIBLE","UNCERTIFIED_THEORY_INTERFACE"}:continue
            count[reason]+=1
            cat=categories[v]
            if reason=="LAYOUT_INCOMPATIBLE":
                views=cs[0].named.get(v,())
                kinds=sorted({shape[0] for _,shape,_,_ in views if shape})
                kind="/".join(kinds) if kinds else "peer_or_alias"
                layout_names[kind]+=1
                examples_key=reason+"/"+kind
                if examples_key not in samples:samples[examples_key]=dict(old=v,A_positive=mu[v],category=cat,
                    failing_views=views[:8],P0_universe_key=models[0].universe,ABI=models[0].w.abi)
            elif reason not in samples:
                samples[reason]=dict(old=v,A_positive=mu[v],category=cat,direct_blocks=sorted(models[0].block.get(v,())))
                if reason=="SAME_KEY_MULTIBIND":samples[reason]["native_sources"]=multibind_source(join,v)[:6]
    save(out/"actual-blocks.json",dict(UsedLeaf_atom_counts=count,overlapping_failure_flags=True,layout_by_view_kind=layout_names,examples=samples))
