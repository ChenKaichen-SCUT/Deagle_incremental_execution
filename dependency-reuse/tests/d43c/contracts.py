"""Independent fault controls on actual signed interfaces, static structure, overflow and sealed C/B data."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import struct
from faults import Campaign,Library,check,save,digest
from audit_d43b import seals,mark_dirty
from control_d43c import Structure,STRUCT,compatible,claimed_preserved,inverse,verify_models


def structural_rows(path):
    with path.open() as f:
        return [r.rstrip("\n").split("\t") for r in f if r.partition("\t")[0] in STRUCT]


def graph(rows):
    s=Structure()
    for row in rows:s.add(row)
    return s


def structural_controls(c,matrix,micro):
    for kind,case in (("RF","fib_updates_8"),("Guard","circular-buffer"),("Block","fib_updates_8"),("Direction","fib_updates_8"),("SameAddress","fib_updates_8")):
        d=matrix/case/"compact/native";lib=Library(d/"dense.bin")
        rows=structural_rows(d/"model.tsv");base=graph(rows);changed=deepcopy(rows)
        if kind=="RF":
            eligible=[i for i,p in enumerate(rows) if p[0:2]==["EDGE","rf"] and p[4]==p[7] and int(p[5])>=0 and
                      (3,int(p[5]),int(p[6]),int(p[4])) in lib.t]
            i=eligible[0];j=next(j for j in eligible if rows[j][4]!=rows[i][4]);u=rows[i]
            for column in (4,7):changed[i][column],changed[j][column]=changed[j][column],changed[i][column]
            key=(3,int(u[5]),int(u[6]),int(u[4]))
        elif kind=="Guard":
            eligible=[i for i,p in enumerate(rows) if p[0]=="GUARD" and int(p[2])>=0 and
                      (4,base.names[p[1]],-1,int(p[2])) in lib.t]
            i=eligible[0];j=next(j for j in eligible if rows[j][2]!=rows[i][2]);u=rows[i]
            changed[i][2],changed[j][2]=changed[j][2],changed[i][2]
            key=(4,base.names[u[1]],-1,int(u[2]))
        elif kind=="SameAddress":
            key=next(k for k in lib.t if k[0]==6 and k[1]!=k[2])
            node=next(v for v in changed if v[:2]==["NODE",str(key[2])])
            node[3]=str(max(n[1] for n in base.nodes.values())+1)
        else:
            key=next(k for k in lib.t if k[0]==7 and len(base.members[k[1]])>1 and
                     any(a in base.members[k[1]] for a,b in base.within))
            members=base.members[key[1]]
            a,b=next((a,b) for a,b in sorted(base.within) if a in members)
            if kind=="Block":
                sep=next(i for i in sorted(members) if i!=key[1])
                changed=[v for v in changed if not ((v[0]=="MEMBER" and list(map(int,v[1:]))==[key[1],sep])
                         or (v[0] in ("IN","OUT") and sep in map(int,v[1:])))]
                for v in changed:
                    if v[:2]==["NODE",str(sep)]:v[-1]=str(sep)
                if ["MEMBER",str(sep),str(sep)] not in changed:changed.append(["MEMBER",str(sep),str(sep)])
            else:
                changed=[v for v in changed if v not in (["OUT",str(a),str(b)],["IN",str(b),str(a)])]
        claimed_preserved(base,base,[key])
        new=graph(changed)
        # Keep just mismatching typed rows as a reproducible delta, including the old and new event bindings.
        before=set(map(tuple,rows));after=set(map(tuple,changed))
        witness=dict(case=case,premise=key,old_rows=sorted(before-after),new_rows=sorted(after-before))
        c.reject("false_unchanged_"+kind,lambda:claimed_preserved(base,new,[key]),
                 ["changed structural premise","binding missing","block direction","same-address condition missing"],witness)
    def spec(path):
        s=Structure()
        for line in path.read_text().splitlines():
            z=line.split()
            if z and z[0]=="rf":
                op,a,b,v=z;lit=2*abs(int(v))+int(int(v)<0)
                s.add(["EDGE",op,a,b,str(lit),"-1","-1",str(lit)])
        return s
    base=spec(micro/"domain/spec");expanded=spec(micro/"domain/expanded/spec")
    read=next(iter(base.domains));claimed_preserved(base,base,domains=[read])
    c.reject("false_complete_RF_domain",lambda:claimed_preserved(base,expanded,domains=[read]),
             ["changed complete candidate domain"],dict(read=read,old=sorted(base.domain(read)),new=sorted(expanded.domain(read))))


def controls(c,matrix,observed,fixtures,permutations):
    p=matrix/"fib_updates_8/compact/native";lib=Library(p/"dense.bin")
    pack=json.loads((p/"library.json").read_bytes());args=pack["argv"];model=p/"model.tsv"
    with model.open() as f:
        config=next(s.rstrip("\n").split("\t") for s in f if s.startswith("K\t"))
    compatible(config,config,args,args)
    for what in ("ABI","memory_model","rule_version"):
        q=config.copy();argv=args.copy()
        if what=="ABI":q[2]="32";argv[argv.index("--64")]="--32"
        if what=="memory_model":argv[argv.index("--mm")+1]="tso"
        if what=="rule_version":q[1]+="-different"
        c.reject("incompatible_"+what,lambda:compatible(config,q,args,argv),["incompatible ABI"],
                 dict(original=config[:5],changed=q[:5],mm=argv[argv.index("--mm")+1]))
    meta=json.loads((permutations/"fib_updates_8/identity/control.json").read_bytes())
    forward={i:2*i for i in range(1,meta["native_variables"]+1)}
    events={i:i for i in range(meta["events"])}
    bad=forward.copy();bad[1]=bad[2]
    c.reject("not_one_to_one",lambda:inverse(bad,len(bad)+1),["non-injective"],dict(old_variables=[1,2],same_image=bad[2]))
    bad=forward.copy();bad[1]^=1
    c.reject("wrong_known_polarity",lambda:verify_models(model,model,bad,events,lib),["changed typed"],dict(atom=1))
    # A complete signed fixture was independently checked. Cross-check each saved model's rule/ABI in this pass.
    configs={}
    for case_dir in sorted(permutations.iterdir()):
        if not case_dir.is_dir():continue
        old=matrix/case_dir.name/"compact/native";old_args=json.loads((old/"library.json").read_bytes())["argv"]
        def k(path):
            with path.open() as f:return next(s.rstrip("\n") for s in f if s.startswith("K\t"))
        key=k(old/"model.tsv")
        for name in ("identity","unsigned","signed"):
            target=old/"model.tsv" if name=="identity" else case_dir/name/"renamed.tsv"
            compatible(key,k(target),old_args,old_args)
        configs[case_dir.name]=dict(passed_modes=3,ABI="--64" if "--64" in old_args else "--32",memory_model=old_args[old_args.index("--mm")+1])
    save(c.out/"positive-contexts.json",configs)
    ol=Library(observed)
    for d in (0,1):
        groups=list(ol.b) if d==0 else [g for i,g in sorted(ol.t.values())]
        j=next(i for i,g in enumerate(groups) if ol.slots[d][g]==1023 and not ol.observed(d,i))
        members=[i for i,g in enumerate(groups) if ol.slots[d][g]==1023]
        check(len({groups[i] for i in members})>1,"need different overflow keys")
        observed_only=set()
        # This false claim filters out the unobserved mismatching member.
        for i in members:
            if i==j and ol.observed(d,i):observed_only.add(1023)
        correct=set();mark_dirty(correct,1023,ol.observed(d,j),False)
        def verify(claim):
            check(1023 in claim,"unconfirmed registered overflow member failed to invalidate the common slot")
        verify(correct)
        c.reject("lost_overflow_"+"BT"[d],lambda:verify(observed_only),["unconfirmed registered overflow"],
                 dict(unobserved_leaf=j,group=groups[j],different_member_groups=[groups[i] for i in members if groups[i]!=groups[j]][:2]))
    qpath=fixtures/"Q/dense.bin";qlib=Library(qpath)
    buf=bytearray(qpath.read_bytes());at=next(x for x in qlib.offsets if buf[x:x+1]==b"S");buf[at+5]=1
    c.corrupt("scope_disposition_reclassified",qpath,buf,Library,["invalid scope disposition"])
    dir=c.out/"bad-seal/native";dir.mkdir(parents=True)
    for file in ("library.sha256","library.json"):(dir/file).write_bytes((p/file).read_bytes())
    for file in pack["files"]:
        # The receipt is original and the expectation is checked before the next file is read.
        if file=="dense.bin":
            data=bytearray((p/file).read_bytes());data[28]^=1;(dir/file).write_bytes(data)
        else:(dir/file).symlink_to(p/file)
    c.reject("tampered_compact_payload",lambda:seals(dir.parent),["library file integrity"],dict(changed_file="dense.bin",byte=28))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ("B_matrix","micro","overflow_bin","fixtures","permutations","out"):p.add_argument(arg,type=Path)
    a=p.parse_args();c=Campaign(a.fixtures,a.out,None)
    structural_controls(c,a.B_matrix,a.micro);controls(c,a.B_matrix,a.overflow_bin,a.fixtures,a.permutations)
    save(c.out/"rejections.json",c.results);print(len(c.results),"contract faults independently rejected")
