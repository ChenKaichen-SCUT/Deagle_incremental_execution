"""PI-1 independent finite Boolean / total-order oracle and native allocator audit."""
import hashlib
import itertools
import json
import os
import subprocess
import sys
from pathlib import Path


def write(path, rows):
    data = "".join("\t".join(map(str, row)) + "\n" for row in rows).encode()
    path.write_bytes(data)
    Path(str(path) + ".sha256").write_text(hashlib.sha256(data).hexdigest() + "\n")


def model(n=3, b=(), q=(), a=(), nodes=(), edges=(), guards=(), ident=1):
    return dict(n=n, b=list(b), q=list(q), a=list(a), nodes=list(nodes), edges=list(edges),
                guards=list(guards), id=ident)


def blocks(m):
    groups = [{i} for i in range(len(m["nodes"]))]
    for k, a, b, _ in m["edges"]:
        if k == "apo":
            x, y = next(v for v in groups if a in v), next(v for v in groups if b in v)
            if x != y:
                x.update(y)
                groups.remove(y)
    return sorted(sorted(g) for g in groups)


def encode(m, previous=None):
    rows = [("PI1.1", m["n"], m["id"], "d8c79eab/SC"), ("CONFIG", "PI1-small/64/SC"),
            ("TARGET", "fixture.assertion")]
    for key, prefix in (("b", "B"), ("q", "Q")):
        rows.extend((prefix, *x) for x in m[key])
    rows.extend(("ASSUME", l) for l in m["a"])
    for name, addr, role in m["nodes"]:
        rows.append(("NODE", name, addr, int("r" in role), int("w" in role), 0, 0))
    rows.extend(("EDGE", *e) for e in m["edges"])
    rows.extend(("GUARD", *g) for g in m["guards"])
    rows.extend(("BLOCK", *b) for b in blocks(m))
    for i, (_, _, role) in enumerate(m["nodes"]):
        if "r" in role:
            rows.append(("DOMAIN", i, *(a for k, a, b, _ in m["edges"] if k == "rf" and b == i)))
    if previous:
        rows.append(("BASE",previous["_seal"]))
        for x, l in m.get("map", [(i, 2*i) for i in range(min(previous["n"], m["n"]))]):
            rows.append(("MATCH", x, l, "fixture-certified/%d/%d" % (x, l)))
        old = {e[0]: i for i, e in enumerate(previous["nodes"])}
        rows.extend(("EVENTMATCH", old[e[0]], i) for i, e in enumerate(m["nodes"]) if e[0] in old)
    rows.extend(m.get("extra", []))
    return rows + [("END", len(m["b"]) + len(m["q"]))]


def value(lit, bits):
    return lit == -1 if lit < 0 else bits[lit // 2] != bool(lit & 1)


def orders(m, bits):
    nodes = m["nodes"]
    guards = {i: value(p, bits) for i, p in m["guards"]}
    precedence = [(a,b) for k,a,b,p in m["edges"] if k in ("po","apo") or (k == "rf" and value(p,bits))]
    reachable = set(precedence)
    for i in range(len(nodes)):
        reachable |= {(a,b) for a,c in reachable for d,b in reachable if c == d == i}
    if any(k == "race" and value(p,bits) and ((a,b) in reachable or (b,a) in reachable)
           for k,a,b,p in m["edges"]):
        return
    for seq in itertools.permutations(range(len(nodes))):
        ranks = {node: i for i, node in enumerate(seq)}
        if any(ranks[a] >= ranks[b] for a,b in precedence):
            continue
        if any(max(ranks[i] for i in g)-min(ranks[i] for i in g)+1 != len(g) for g in blocks(m)):
            continue
        if any(ranks[a]<ranks[w]<ranks[b] for k,a,b,p in m["edges"] if k=="rf" and value(p,bits)
               for w,(_,addr,role) in enumerate(nodes) if "w" in role and addr==nodes[a][1] and guards.get(w,False)):
            continue
        yield ranks


def allowed(m, bits, contextual=True):
    if contextual and (any(not any(value(p,bits) for p in c) for c in m["b"]+m["q"])
                       or not all(value(p,bits) for p in m["a"])):
        return False
    return next(orders(m,bits),None) is not None


def examples():
    W=("x#1","x","w");R=("x#2","x","r"); W2=("x#3","x","w")
    nodes=[W,R]; rev=[("rf",0,1,0),("po",1,0,-1)]
    def rf(edges, a=(0,), guards=((0,-1),)):return model(nodes=nodes,edges=edges,a=a,guards=guards)
    cycle=[("po",0,1,-1),("po",1,0,-1)]
    inert=[("a","a",""),("b","b",""),("c","c","")]
    change=rf([("rf",0,1,1)],(1,),((0,2),))
    atomic=[("apo",0,2,-1),("po",0,1,-1),("po",1,2,-1)]
    tri=[("rf",0,1,0),("po",0,2,-1),("po",2,1,-1)]
    triplet=model(nodes=[W,R,W2],edges=tri,guards=[(0,-1),(2,2)],a=[0,2])
    newDomain=model(nodes=[W,R,W2],edges=tri+[("rf",2,1,4)],guards=[(0,-1),(2,2)],a=[1,4,2])
    x=model(b=[[0]],a=[1]); nt=model(a=[1])
    co=model(nodes=[W,W2],guards=[(0,-1),(1,-1)])
    signed=model(b=[[3],[0]],a=[0]);signed["map"]=[(0,3),(1,0),(2,4)]
    signed_ports=rf([("rf",0,1,1)],(1,),((0,3),))
    signed_ports["map"]=[(0,1),(1,3),(2,4)]
    cases={
        "boolean_add_delete_replace":[x,nt,model(b=[[0],[1]]),model(b=[[1]])],
        "duplicates_constants_empty":[model(b=[[0],[0],[-1],[2,3],[0,-2]],a=[1]),x,nt,model(b=[[]]),model(b=[[-2]]),model(b=[])],
        "immutable_query":[model(b=[[0]],q=[[1]],a=[-1]),model(b=[[0]],q=[[0]],a=[-1])],
        "native_constant_assumption":[model(a=[-2]),model(a=[-1])],
        "reverse_rf_delete_po":[rf(rev),rf(rev[:1])],
        "static_cycle_recovery":[model(nodes=inert,edges=cycle),model(nodes=inert,edges=cycle[:1])],
        "same_graph_changed_B":[rf(rev,()),dict(rf(rev,()),b=[[0]])],
        "surviving_binary_gc":[rf(rev,()),dict(rf(rev,()),b=[[0]])],
        "certified_signed_interfaces":[rf(rev[:1],(0,),((0,2),)),signed_ports],
        "signed_port_and_guard":[rf(rev,(),((0,2),)),change],
        "changed_endpoint":[rf(rev),model(nodes=[W,R,W2],edges=[("rf",2,1,0)],guards=[(2,-1)],a=[0])],
        "atomic_split_merge":[model(nodes=inert,edges=atomic),model(nodes=inert,edges=atomic[1:]),model(nodes=inert,edges=atomic)],
        "signed_numbering":[model(b=[[0],[2]]),signed],
        "trinary_immediate":[dict(triplet,guards=[(0,-1),(2,-1)],a=[0]),newDomain],
        "trinary_delayed_rf_guard":[triplet,dict(triplet,a=[2,0]),newDomain],
        "dynamic_co":[co,co,model(nodes=[W,("y#3","y","w")],guards=co["guards"])],
        "race":[model(nodes=inert,edges=[("race",0,1,0),("po",0,1,-1)],a=[0]),model(nodes=inert,edges=[("race",0,1,0)],a=[0])],
        "native_learning_gc":[model(b=[[0,2],[0,3]]),model(b=[[0,2],[0,3]])],
        "restart_theory_replay":[model(n=4,b=[[2,4],[2,5],[3,4]],nodes=nodes,edges=rev,guards=[(0,-1)]),
                                 model(n=4,b=[[2,4],[2,5],[3,4]],nodes=nodes,edges=rev,guards=[(0,-1)])],
        "native_learning":[model(b=[[0,2],[0,3]]),model(b=[[0,2],[0,3]])],
        "address_directory":[newDomain,dict(newDomain,nodes=[W,R,("y#3","y","w")],edges=tri[:1],a=[0,2])],
    }
    return cases


def parse(output):
    return [json.loads(l[4:]) for l in output.splitlines() if l.startswith("ROW ")]


def inspect_reason(line, mu, m):
    payload, native=line.split(" |")
    _,ver,generation,kind,epoch,conclusion,current,*body=payload.split()
    e,c=int(epoch),int(conclusion)
    clauses=[tuple(map(int,b.split("/"))) for b in body]
    raw=set(map(int,native.split()))
    got={p for p,_,_ in clauses}
    expected=(raw-{ -2 })|{e^1}
    if c>=0:expected.add(c)
    assert got==expected and len(got)==len(clauses) and (e^1) in got, line
    if kind=="P":
        assert clauses[0][0]==c and clauses[0][1] in (2,3)
        assert all(v==1 and h<=int(current) for _,v,h in clauses[1:])
    else:assert all(v==1 and h<=int(current) for _,v,h in clauses)
    # Discharge the epoch; all non-CO projected reasons must be consequences of this theory alone.
    inv={raw//2:(i,raw&1) for i,raw in enumerate(mu)}
    if any((p//2 not in inv and p!=(e^1)) for p in got):return "extension"
    for bits in itertools.product((False,True),repeat=m["n"]):
        if allowed(m,bits,False):
            assert any(value(2*inv[p//2][0]+((p&1)^inv[p//2][1]),bits)
                       for p in got if p!=(e^1)), ("non-entailed allocator reason",line,bits)
    return "exhaustive"


def main(binary, out, stock=None):
    out.mkdir(parents=True,exist_ok=True)
    all_results={}
    cases=examples()
    for name,models in cases.items():
        work=out/name;work.mkdir(exist_ok=True);steps=[("RESTART",1)] if name=="restart_theory_replay" else []; previous=None
        for i,m in enumerate(models):
            path=work/f"v{i}.txn";write(path,encode(m,previous));m["_seal"]=Path(str(path)+".sha256").read_text().strip()
            steps.extend([("APPEND",path),("SOLVE",m["id"])])
            if name in ("native_learning_gc","surviving_binary_gc") and i==0:steps.append(("GC",))
            previous=m
        protocol=work/"protocol";protocol.write_text("".join("\t".join(map(str,s))+"\n" for s in steps))
        audit=work/"native.txt"
        run=subprocess.run([binary,protocol,audit],capture_output=True,text=True,timeout=20)
        (work/"output.txt").write_text(run.stdout+run.stderr)
        assert run.returncode==0,(name,run.returncode,run.stdout[-200:],run.stderr)
        rows=parse(run.stdout);assert len(rows)==len(models)
        stock_rows=[]
        for i,(m,r) in enumerate(zip(models,rows)):
            if stock:
                ctrl=subprocess.run([stock,work/f"v{i}.txn"],capture_output=True,text=True,timeout=10)
                (work/f"stock{i}.txt").write_text(ctrl.stdout+ctrl.stderr)
                assert ctrl.returncode==0 and "STOCK "+r["status"] in ctrl.stdout,(name,i,ctrl.stderr)
                stock_rows.append(r["status"])
            expected=any(allowed(m,bits) for bits in itertools.product((False,True),repeat=m["n"]))
            assert r["status"]==("SAT" if expected else "UNSAT"),(name,i,expected,r)
            assert r["solver_construct_count"]==1 and r["old_learnt_import_count"]==r["old_learnt_export_count"]==r["per_clause_reproof_count"]==0
            if expected:
                bits=tuple(c=="1" for c in r["assignment"])
                assert "?" not in r["assignment"] and allowed(m,bits),(name,r)
                assert set(r["order"])=={n[0] for n in m["nodes"]}
                assert any(all(r["order"][m["nodes"][a][0]] <= r["order"][m["nodes"][b][0]]
                               for a in seq for b in seq if seq[a]<seq[b]) for seq in orders(m,bits))
        if name=="certified_signed_interfaces":
            assert rows[1]["reused"]==3 and rows[1]["rejected_ports"]==0
        if name=="signed_port_and_guard":
            assert rows[1]["rejected_ports"]>0
        mus={};checked=[];co_checked=0
        for line in audit.read_text().splitlines():
            if line.startswith("MU "):
                _,version,*vals=line.split();mus[int(version)]=list(map(int,vals))
            if line.startswith("REASON "):
                v=int(line.split()[1]);checked.append(inspect_reason(line,mus[v],models[v-1]))
            if line.startswith("ENQUEUE "):
                _,ref,conclusion,position,*antecedents=line.split()
                assert all(int(p.split("/")[1])<int(position) for p in antecedents)
            if line.startswith("CO "):
                _,v,e,a,b,*body=map_or_strings(line)
                assert (int(e)^1) in map(int,body) and a!=b
                co_checked+=1
        all_results[name]={"statuses":[r["status"] for r in rows],"actual_reasons":checked,"co_clauses":co_checked,"independent_stock":stock_rows,
                            "metrics":[r["native"] for r in rows]}
    assert all_results["native_learning"]["metrics"][1]["families"][0]["hits"][0]>0
    restart=all_results["restart_theory_replay"]["metrics"][0]
    if os.environ.get("PI1R_MODE","R0")=="R0":
        assert restart["rebuilds"]>=2
    else:
        assert restart["restart_study"]["ordinary"]>=1
    assert all_results["surviving_binary_gc"]["metrics"][1]["collections"] and all_results["surviving_binary_gc"]["metrics"][1]["families"][2]["hits"][0]>0
    assert all_results["dynamic_co"]["co_clauses"]==1
    assert all_results["changed_endpoint"]["metrics"][1]["families"][2]["dormant"]==1
    (out/"small.json").write_text(json.dumps(all_results,indent=2)+"\n")
    print("PASS",len(cases),"finite sequences")


def map_or_strings(line):
    return line.split()


if __name__=="__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]) if len(sys.argv)>3 else None)
