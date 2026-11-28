"""Independent controls: real native capture, held-out signed permutation and fault injection."""
import argparse
import copy
import difflib
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from si1b_catalog import Model, Registry, Wire, check, signed, sha
from si1b_join import Join, pipeline
from si1b_native import emit_seal
from si1b_sources import source_pair
from run_stock import BASE, save


def load_one(folder,source,reg,side,transform=None):
    wire=Wire(folder,source)
    if transform:transform(wire)
    doc=json.loads((source/"source-catalog.json").read_bytes())
    return Model(wire,reg,doc,side)


def permute(w):
    """Encode a different local literal spelling; the independent oracle stays in this module."""
    def spell(u):
        x=signed(u)
        if x<0:return u
        v=x//2
        return 2*(1+((v-1+17)%(w.n-1)))+((x&1)^(v%3==0))
    for tag,n in [("B",2),("R",5),("L",1)]:
        w.rows[tag]=[r[:n]+tuple(spell(x) for x in r[n:]) for r in w.rows[tag]]
    w.rows["H"]=[(a,b,spell(l),k) for a,b,l,k in w.rows["H"]]
    w.rows["G"]=[(a,spell(l)) for a,l in w.rows["G"]]


def conflict_controls(base):
    def blank():
        m=copy.copy(base)
        m.r=defaultdict(list);m.bind=defaultdict(set);m.block=defaultdict(set)
        m.interface={};m.roots={};m.result={};m.template={};m.children={};m.roles={}
        return m
    tests={}
    for name,pairs,expected in [
        ("same-key",[("a",[2,4],[2])],"SAME_KEY_MULTIBIND"),
        ("split",[("a",[2],[2]),("b",[2],[4])],"ONE_TO_MANY"),
        ("merge",[("a",[2],[4]),("b",[4],[4])],"MANY_TO_ONE"),
        ("sign",[("a",[2],[4]),("b",[2],[5])],"POLARITY_CONFLICT"),
        ("constant",[("a",[2],[-1]),("alias",[2],[4])],"CONSTANT_VARIABLE_CHANGE"),
        ("theory",[("ordinary",[2],[4])],"THEORY_ORDINARY_CONFLICT")]:
        a,b=blank(),blank()
        for key,left,right in pairs:a.bind[a.k(key)]=set(left);b.bind[a.k(key)]=set(right)
        if name=="theory":
            a.interface[1]={("RF",a.k("write-A-read-B"),0)}
            b.interface[2]={("RF",a.k("write-B-read-A"),0)}
        # Independent negative alias must survive every unrelated conflict.
        a.bind[a.k("independent")]={7};b.bind[a.k("independent")]={8}
        j=Join(a,b).run()
        check(j.mu=={3:9} and expected in j.bad_by_side[0][1],name)
        tests[name]=dict(reason=expected,admitted=j.mu,rejected=j.bad_by_side[0])
    return tests


def cache_control(binary,folder):
    program=b"unsigned char a;\nunsigned char b;\nunsigned char c;\nvoid owner_a(void);\nvoid owner_b(void);\n"
    source=folder/"source";source_pair({"ports.c":(program,program)},None,source)
    orders=["AB","BA"]
    for mode in orders:
        out=folder/mode;out.mkdir(exist_ok=True)
        env=dict(os.environ,DEAGLE_SI1B_CATALOG=str(out/"native.bin"),DEAGLE_SI1B_TOKENS=str(source/"P0.tokens"))
        result=subprocess.run([binary,mode],env=env,capture_output=True,check=True)
        (out/"stdout").write_bytes(result.stdout);(out/"stderr").write_bytes(result.stderr)
        save(out/"run.json",dict(argv=[str(binary),mode],input_sha256={"ports.c":__import__("hashlib").sha256(program).hexdigest()}))
        emit_seal(binary,out,source,"P0")
    j=pipeline([folder/m for m in orders],source,folder/"direct",(0,0));a=j.a
    logs=[[[int(t) for t in line.split()] for line in (folder/m/"stdout").read_text().splitlines()] for m in orders]
    for log in logs:
        check(len(log)==4 and all(log[i][2:]==log[i+1][2:] for i in (0,2)),"cache hit allocated or changed result")
        check(set(log[0][3:]).isdisjoint(log[2][3:]),"erased template reused")
    check(logs[0][0][1]==logs[1][1][1]!=logs[1][0][1],"owners did not swap")
    roles=Counter()
    for row in a.r["R"]:
        _,_,label,_,_,raw=row
        if signed(raw)>=2 and raw//2 in j.mu:roles[a.S[label]]+=1
    check(roles["adder-carry"] and roles["adder-sum"] and a.r["C"] and j.cache[0]["additional_owner_role_bindings"]>0,"cache rebinding inactive")
    check(j.mu and all(y==2*v for v,y in j.mu.items()),"wrong owner or generation")
    return dict(order=orders,actual_visits=logs,roles=roles,mapped=len(j.mu),cache=j.cache)


def lexical_controls(root):
    old=b"#define TAKE(x) (x)\nunsigned f(unsigned a) {\n unsigned x;\n x = a + 1;\n return TAKE(x);\n}\n"
    new=old.replace(b"a + 1",b"a + 2")
    patch=b"".join(difflib.diff_bytes(difflib.unified_diff,old.splitlines(True),new.splitlines(True),fromfile=b"a/ports.c",tofile=b"b/ports.c"))
    root.mkdir(exist_ok=True);(root/"edit.patch").write_bytes(patch)
    doc,_=source_pair({"ports.c":(old,new)},root/"edit.patch",root/"source")
    a,b=[d["ports.c"]["lines"] for d in doc["sides"]]
    check(a[4]["id"]==b[4]["id"] and b[4]["proof"]=="rhs-outer","outer RHS continuation")
    check(not a[5]["id"] and not b[5]["id"],"macro expansion was accepted")
    return dict(outer=[a[4],b[4]],macro=[a[5],b[5]])

def phi_control(root,binary):
    code=(BASE/"tests/si1b/phi.c").read_bytes();src=root/"source";source_pair({"phi.c":(code,code)},None,src,32)
    folder=root/"native";folder.mkdir(exist_ok=True);(folder/"phi.c").write_bytes(code)
    env=dict(os.environ,DEAGLE_SI1B_CATALOG=str(folder/"native.bin"),DEAGLE_SI1B_TOKENS=str(src/"P0.tokens"),DEAGLE_SI1B_MODEL_ONLY="1")
    cmd=[str(binary),"--function","main","--deagle-closure","--mm","sc","--32","--unwind","4","--unwinding-assertions","--json-ui","phi.c"]
    proc=subprocess.run(cmd,cwd=folder,env=env,capture_output=True);check(proc.returncode==77,"native PHI control")
    (folder/"stdout").write_bytes(proc.stdout);(folder/"stderr").write_bytes(proc.stderr)
    save(folder/"run.json",dict(argv=cmd,exit_code=77,input_sha256={"phi.c":sha(folder/"phi.c")}))
    emit_seal(binary,folder,src,"P0");m=load_one(folder,src,Registry(),0)
    rows=[dict(symbol=m.S[sym],context=signed(ctx),producer=m.symbols.get(m.S[sym],0)) for sym,event,ctx,role,*_ in m.r["V"]
          if m.S[role]=="assign4" and "choice" in m.S[sym]]
    check(rows and any(r["producer"] for r in rows),"unambiguous program PHI missing")
    return rows

def run(root,cache_binary,output):
    source=root/"source"
    selfjoin=pipeline([root/"P0",root/"same-cwd-control"],source,None,(0,0))
    cross=pipeline([root/"P0",root/"P1"],source,None)
    a,b=selfjoin.a,selfjoin.b
    check(a.w.seal["inputs"]==b.w.seal["inputs"] and a.w.allocation_hash==b.w.allocation_hash,"cwd changed native input")
    check(all(y==2*v for v,y in selfjoin.mu.items()) and len(selfjoin.mu)>0,"same-model identity")
    check(a.decls==b.decls and a.sites==b.sites and a.contexts==b.contexts and a.symbols==b.symbols and
          a.bind==b.bind and a.roots==b.roots and a.roles==b.roles,"same-model supported ports changed")
    perm=Join(a,load_one(root/"same-cwd-control",source,a.reg,0,permute)).run()
    expect={v:2*(1+(v-1+17)%(a.w.n-1))+(v%3==0) for v in selfjoin.mu}
    check(perm.mu==expect,"incorrect held-out signed image")
    moved=sum(y//2!=v for v,y in cross.mu.items());check(moved>0,"unrelated code did not renumber mapped variables")
    check(len(cross.mu)==len({p//2 for p in cross.mu.values()}),"non-injective")
    repeat=[(i,site) for i,site in a.site_rows.items() if site[0]=="model.c" and "repeated" in site[3] and site[2]=="main"]
    surviving=set(cross.b.sites.values())
    repeat=sorted((a.site_rows[i][1],i in a.sites and a.sites[i] in surviving) for i,_ in repeat)
    check(len(repeat)==2 and [r[1] for r in repeat]==[True,False],"deleted repeated call incorrectly reused")
    workers={a.reg.rows[x][1] for x in a.contexts.values() if x and a.reg.rows[x][1]}
    nested=sum(i in a.contexts and len(loops)>=4 for i,_,_,_,*loops in a.r["X"])
    phi=[(a.S[sym],int(ctx),a.S[sym] in a.symbols) for sym,event,ctx,role,*_ in a.r["V"] if a.S[role]=="assign4"]
    check(len(workers)>=2 and nested and phi,"thread/loop/PHI fixture did not exercise requested paths")
    def reorder(w):
        for t in ("F","H","G"):w.rows[t].reverse()
    reordered=Join(a,load_one(root/"P0",source,a.reg,0,reorder)).run()
    check(selfjoin.mu==reordered.mu,"RF installation order became identity")
    def reverse(w):w.rows["H"]=[(r,s,lit,ok) for s,r,lit,ok in w.rows["H"]]
    reversed_=Join(a,load_one(root/"P0",source,a.reg,0,reverse)).run()
    rf={v for v in selfjoin.mu if any(role=="RF" for role,_,_ in a.interface.get(v,()))}
    check(rf and rf.isdisjoint(reversed_.mu),"reversed RF endpoint was accepted")
    def mutate_layout(w):
        w.rows["M"]=[(p,c,n,off+1,width,pad) for p,c,n,off,width,pad in w.rows["M"]]
        w.rows["Q"]=[]  # Withdraw actual non-reserved address-object interpretations.
    changed_model=load_one(root/"P0",source,a.reg,0,mutate_layout)
    changed=Join(a,changed_model).run()
    changed_layout=[(t,a.layout_key(t),changed_model.layout_key(t)) for t in a.members
                    if a.members[t] and a.layout_key(t)!=changed_model.layout_key(t)]
    layout_loss=len(selfjoin.mu.keys()-changed.mu.keys())
    check(changed_layout and layout_loss>0,"changed layout accepted every old port")
    with TemporaryDirectory() as t:
        t=Path(t);(t/"seal.json").write_bytes((root/"P0/seal.json").read_bytes())
        (t/"native.bin").write_bytes((root/"P0/native.bin").read_bytes()[:-4])
        try:Wire(t,source)
        except ValueError:pass
        else:raise AssertionError("truncated archive accepted")
    cache=cache_control(cache_binary,root/"native-cache")
    native=Path(json.loads((root/"P0/run.json").read_bytes())["argv"][0])
    phi_positive=phi_control(root/"single-phi",native)
    lexical=lexical_controls(root/"lexical")
    result=dict(cwd_supported=len(selfjoin.mu),bound_port_keys=len(a.bind),same_cwd_wrong=0,
                hidden_signed_permutation=len(expect),permutation_flips=sum(x&1 for x in expect.values()),permutation_wrong=0,
                genuine_cross_accepted=len(cross.mu),genuine_renumbered=moved,similar_call=repeat,
                thread_births=len(workers),nested_contexts=nested,phi=phi,positive_phi=phi_positive,lexical=lexical,
                rf_reordered=len(rf),rf_reversed_rejected=len(rf),changed_layouts=len(changed_layout),
                layout_withdrawals=layout_loss,truncated_body_rejected=True,
                negative=conflict_controls(a),native_cache=cache)
    save(output,result)

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("controls","cache_binary","output"):p.add_argument(name,type=Path)
    a=p.parse_args();run(a.controls,a.cache_binary.resolve(),a.output)
