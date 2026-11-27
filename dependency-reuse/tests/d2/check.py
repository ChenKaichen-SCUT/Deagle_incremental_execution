"""Focused native CDCL checks, exact local resolution replay, and finite-model sanity checks."""
import argparse
from itertools import combinations,product
import json
from pathlib import Path
import struct
import subprocess


def php(pigeons):
    holes=pigeons-1
    var=lambda p,h:1+p*holes+h
    c=[tuple(var(p,h) for h in range(holes)) for p in range(pigeons)]
    c.extend((-var(p,h),-var(q,h)) for h in range(holes) for p,q in combinations(range(pigeons),2))
    return [("B",clause) for clause in c]


def raw(l): return 2*abs(l)+(l<0)


def write_case(directory,n,mode,stress,rows):
    directory.mkdir()
    (directory/"case.cnf").write_text(f"{n} {mode} {int(stress)}\n"+"".join(
        tag+" "+" ".join(map(str,c))+"\n" for tag,c in rows))


def stats(file):
    return {k:int(v) for k,v in (s.split() for s in file.read_text().splitlines())}


def scenario(directory,engine,n,rows,change,proof,oracle):
    directory.mkdir()
    bases=[(tag,c) for tag,c in rows if tag in ("B","Q","U")]
    translate={v:raw(-(n+1-v) if v%3==1 else n+1-v) if change=="renumber" else 2*v for v in range(1,n+1)}
    def project(c):
        return tuple(sorted({translate[abs(l)]^(l<0) for l in c}))
    new=[(tag,project(c)) for tag,c in bases]
    if change=="renumber":new.reverse()
    if change=="add":new.append(("B",(2*(n+1),)))
    if change=="delete":new.pop(0)
    if change=="replace":new[0]=(new[0][0],tuple(sorted((*new[0][1],2*(n+1)))))
    live=set(new)
    (directory/"map").write_text("".join(f"{v} {l}\n" for v,l in translate.items()))
    (directory/"inputs").write_text("".join(" ".join(map(str,(tag,int((tag,project(c)) not in live),
        *(raw(l) for l in c))))+"\n" for tag,c in bases))
    (directory/"P1.json").write_text(json.dumps(new)+"\n")
    cmd=[str(engine),str(proof),str(directory/"inputs"),str(directory/"map"),str(oracle),str(directory)]
    subprocess.run(cmd,check=True)
    metrics=stats(directory/"metrics.tsv")
    candidates=[list(map(int,l.split()))[1:] for l in (directory/"survivors.tsv").read_text().splitlines()]
    if n<=9:
        variables=n+(change in ("replace","add"))
        model_count=0
        for truth in product((False,True),repeat=variables):
            def satisfied(c):return any(truth[(l//2)-1] != bool(l&1) for l in c)
            if all(satisfied(c) for tag,c in new if tag=="B"):
                model_count+=1
                if not all(satisfied(c) for c in candidates):raise AssertionError("survivor is false in a P1 model")
        metrics["independent_P1_models_checked"]=model_count
    if change in ("unchanged","renumber","add"):
        assert metrics["old_proof_survives"]==metrics["complete_permanent_boolean"]
    return metrics,cmd


def corrupt_checks(root,cmd,proof):
    data=bytearray(proof.read_bytes())
    pos=12;sections=[]
    for stride in (16,4,8,16,12,8,12,4,4,4,4,4):
        count=struct.unpack_from("<I",data,pos)[0]
        sections.append((pos+4,count))
        pos+=4+count*stride
    node_start,num=sections[0]
    cases={}
    for i in range(1,num):
        _,edge_end,kind,flags=struct.unpack_from("<4I",data,node_start+16*i)
        if kind==6 and flags&1 and "forged-pure" not in cases:
            cases["forged-pure"]=(node_start+16*i+12,0)
        edge_begin=struct.unpack_from("<I",data,node_start+16*(i-1)+4)[0]
        if kind==6 and edge_end>edge_begin+1 and "wrong-pivot" not in cases:
            at=sections[2][0]+(edge_begin+1)*8+4
            cases["wrong-pivot"]=(at,struct.unpack_from("<I",data,at)[0]^1)
    assert len(cases)==2
    for label,(offset,value) in cases.items():
        mutated=bytearray(data)
        struct.pack_into("<I",mutated,offset,value)
        path=root/(label+".bin")
        path.write_bytes(mutated)
        run=subprocess.run([cmd[0],str(path),*cmd[2:]],capture_output=True,text=True)
        assert run.returncode==1 and run.stderr.strip()
        (root/(label+".rejection")).write_text(run.stderr)
        path.unlink() # the exact mutation is recorded below
    (root/"mutations.json").write_text(json.dumps(cases,indent=2)+"\n")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("tools",type=Path);p.add_argument("new_dir",type=Path);a=p.parse_args()
    tools,root=a.tools.resolve(),a.new_dir.resolve()
    root.mkdir(parents=True,exist_ok=False)
    gated=[("B",(-1,2,3)),("B",(-1,2,-3)),("B",(-1,-2,3)),("B",(-1,-2,-3))]
    root_case=[("B",c) for c in ((-1,2),(-2,9),(3,4,-9),(3,-4,-9),(1,),
                                  (-3,4,-9),(-3,-4,-9),(5,-5),(1,6),(7,7,8))]
    cases={
      "root":(9,2,False,root_case,("unchanged","delete","replace","renumber")),
      "early":(3,2,False,[("B",c) for c in ((-1,2),(-1,-2),(1,),(3,))],("unchanged",)),
      "empty":(2,2,False,[("B",()),("B",(2,))],("unchanged",)),
      "sat":(4,2,False,[("B",c) for c in ((1,2),(1,-2),(3,4),(3,-4))],
             ("unchanged","add","delete","replace","renumber")),
      "assumptions":(3,2,False,gated+[("A",(1,))],("unchanged",)),
      "query":(3,2,False,gated+[("Q",(1,))],("unchanged",)),
      "theory":(3,2,False,gated+[("T",(1,))],("unchanged",)),
      "unknown":(3,2,False,gated+[("U",(1,))],("unchanged",)),
    }
    for mode in (0,1,2):
        cases[f"php{mode}"]=(20,mode,True,php(5),("unchanged","delete","replace","add","renumber") if mode==2 else ("unchanged",))
    summary={}
    for label,(n,mode,stress,rows,changes) in cases.items():
        d=root/label;write_case(d,n,mode,stress,rows)
        for binary in ("cnf-on","cnf-oracle"):
            wd=d/binary;wd.mkdir()
            with (wd/"stdout").open("w") as stdout,(wd/"stderr").open("w") as stderr:
                subprocess.run([tools/binary,d/"case.cnf",wd/"proof.bin"],check=True,cwd=wd,stdout=stdout,stderr=stderr,timeout=60)
        proof=d/"cnf-on/proof.bin";oracle=d/"cnf-oracle/native-learns.tsv"
        results=summary[label]={}
        for change in changes:
            r,cmd=scenario(d/change,tools/"check",n,rows,change,proof,oracle)
            results[change]=r
        if label=="theory":corrupt_checks(d,cmd,proof)
    m=summary["php2"]["unchanged"]
    assert m["gc"] and m["reduce_db"] and m["evicted_cdcl"] and m["used_parent_edges_to_evicted_learned"]
    assert m["relocated_to_new_cref"] and m["relocated_cdcl_to_new_cref"] and m["born_after_ancestor_eviction"]
    assert summary["php2"]["delete"]["loss_through_prior_learned"]
    assert m["minimized_births"] and m["min_success"] and m["min_failure"] and m["uses_prior_learned_directly"]
    assert summary["php1"]["unchanged"]["minimized_births"] and not summary["php0"]["unchanged"]["minimized_births"]
    for action in ("delete","replace"):
        z=summary["php2"][action]
        assert 0<z["old_proof_survives"]<z["complete_permanent_boolean"]
    z=summary["root"]["unchanged"]
    assert z["kind_4"] and z["kind_5"] and z["unit_births"] and z["input_action_1"] and z["input_action_2"]
    assert summary["early"]["unchanged"]["kind_10"] and summary["early"]["unchanged"]["input_action_3"]
    assert summary["theory"]["unchanged"]["theory_any"] and not summary["theory"]["unchanged"]["old_proof_survives"]
    assert summary["unknown"]["unchanged"]["incomplete_any"] and not summary["unknown"]["unchanged"]["old_proof_survives"]
    assert summary["query"]["unchanged"]["query_any"] and not summary["query"]["unchanged"]["old_proof_survives"]
    assert summary["assumptions"]["unchanged"]["assumptions"] and summary["assumptions"]["unchanged"]["complete_permanent_boolean"]
    assumption_learns=(root/"assumptions/unchanged/survivors.tsv").read_text().splitlines()
    assert any("3" in line.split()[1:] for line in assumption_learns) # raw 3 denotes negated assumption 1
    assert summary["sat"]["unchanged"]["old_proof_survives"] and summary["sat"]["unchanged"]["independent_P1_models_checked"]
    (root/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(f"{len(cases)} native fixtures, {sum(map(len,summary.values()))} deltas, 2 rejected corruptions")


if __name__=="__main__":main()
