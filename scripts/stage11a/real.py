"""Read only authenticated pilot captures. Align this reviewed pair, then check its RF witness."""
import gzip
import hashlib
import json
import zipfile
from collections import Counter, defaultdict
from functools import lru_cache

from candidate import Branch, explain, saturate
from reference import Event, Graph, strict_models


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Archive:
    def __init__(self, root):
        self.path=root/"reports/evidence/svcomp26/raw"
        raw=(self.path/"raw-index.json.gz").read_bytes()
        assert sha(raw)=="7850ceb93d79b943912dc32d868b950c5a7b02964ef51610f238ec5d140a2b3a"
        self.index=json.loads(gzip.decompress(raw))
        self.receipts={}

    @lru_cache(maxsize=8)
    def chunk(self,key):
        with zipfile.ZipFile(self.path/self.index["chunks"][key]) as archive:
            data=gzip.decompress(archive.read(key+".gz"))
        assert sha(data)==key
        return data

    def get(self, path):
        name="pairs/read_write_lock-2/P1-P2/1/"+path
        digest=self.index["files"][name]
        size,*keys=self.index["contents"][digest]
        data=b"".join(self.chunk(k) for k in keys)
        assert len(data)==size and sha(data)==digest
        self.receipts[name]=digest
        return data


def component_map(keys,edges):
    groups={k:frozenset([k]) for k in keys}
    for a,b in edges:
        group=groups[a]|groups[b]
        for member in group:
            groups[member]=group
    return groups


def translate(archive,version):
    def doc(name):
        return json.loads(archive.get("F/"+version+"/"+name+".json"))
    model,native,goto,visits=map(doc,("full_model","native-bindings","goto","visits"))
    assert native["site"]=="bmc_util before save_raw_graph/init"
    pool=model["ireps"]
    @lru_cache(None)
    def ir(index):
        if index is None: return None
        term=pool[index]
        return [term["id"],{k:ir(v) for k,v in term.get("named",{}).items()},
                [ir(v) for v in term.get("sub",[])]]
    coords={(i["function"],i["pc"]):i for i in goto["instructions"]}
    occurrence=Counter()
    names,events,explicit={}, {}, defaultdict(set)
    assert [(b["parent"],b["child"],b["function"]) for b in model["thread_births"]]==[
        (0,i,"main") for i in (1,2,3,4)]
    for s in model["steps"]:
        name=s.get("oc_name")
        if not name: continue
        fn=s["function"]
        addr=native["addresses"][name]
        role="release_read_count" if s["thread"] in (2,4) and s.get("object")=="r" and fn in (
            "reader","__VERIFIER_atomic_release_read_lock") else fn
        # Birth order is verified against the frozen main in lock.py. No cross-program matcher
        # may infer this reviewed move from equal ordinals. Spawn objects use call occurrences.
        obj=s.get("object") or "thread_birth"
        base=(("main","W1","R1","W2","R2")[s["thread"]],role,s["kind"],obj)
        occurrence[base]+=1
        key="/".join((*base,str(occurrence[base])))
        assert key not in events and name not in names
        names[name]=key
        instr=coords[fn,s["pc"]]
        frame=visits[s["visit"]-1]
        assert frame["thread"]==s["thread"]
        lhs=s["lhs"]
        typ=ir(pool[lhs].get("named",{}).get("type")) if lhs is not None else None
        events[key]={"endpoint":name,"thread":s["thread"],"kind":s["kind"],"object":s.get("object"),
                     "solver_address":addr,"type":typ,"guard":ir(s["guard"]),"site":instr,
                     "frames":frame["frames"],"explicit_section_id":s["atomic_section"]}
        if s["atomic_section"]:
            explicit[s["atomic_section"]].add(key)
    assert set(names)==set(native["addresses"])
    edges=[]
    slots={}
    aliases=defaultdict(list)
    for i,(edge,raw) in enumerate(zip(native["edges"],model["oc_edges"],strict=True)):
        assert edge["slot"]==i and all(raw[k]==edge[k] for k in ("from","to","kind"))
        a,b=names[edge["from"]],names[edge["to"]]
        atom=(edge["kind"],a,b)
        assert atom not in slots
        x=edge["x"]
        if edge["kind"]=="rf":
            assert x>=0
            aliases[x//2].append([atom,x%2])
        else:
            assert edge["kind"] in ("po","apo") and x==-1
        edges.append(atom)
        slots[atom]={"slot":i,"x":x,"symbol":ir(raw["guard"])}
    guards={x["local_symbol"]:x for x in model["oc_guards"]}
    assert set(guards)=={x["event"] for x in native["guards"]}
    for i,g in enumerate(native["guards"],len(edges)):
        a=names[g["event"]]
        decl=guards[g["event"]]
        atom=("guard",a)
        assert i==g["slot"] and int(decl["solver_line"] or 0)==g["line"]
        slots[atom]={"slot":i,"x":g["x"],"symbol":ir(decl["guard"]),"line":g["line"]}
        if g["x"]>=0:
            aliases[g["x"]//2].append([atom,g["x"]%2])
    block=component_map(events,[(a,b) for k,a,b in edges if k=="apo"])
    meta={"events":events,"edges_in_native_order":edges,"layout":goto["layout"],
          "births":model["thread_births"],"literal_records":[[k,v] for k,v in sorted(slots.items())],
          "alias_groups":sorted(sorted(al) for al in aliases.values()),
          "apo_components":sorted(set(tuple(sorted(g)) for g in block.values())),
          "explicit_sections":sorted(sorted(g) for g in explicit.values())}
    return meta,slots,block


def projection(meta,slots,blocks,bits):
    def k(t,fn,kind):
        key=t+"/"+fn+"/"+kind+"/r/1"
        assert key in meta["events"]
        return key
    acquire="__VERIFIER_atomic_take_read_lock"
    source=k("R1",acquire,"write")
    ar,aw=k("R2",acquire,"read"),k("R2",acquire,"write")
    rr,rw=k("R1","release_read_count","read"),k("R1","release_read_count","write")
    keys=(source,ar,aw,rr,rw)
    local={source:"S",ar:"Aread",aw:"Awrite",rr:"Dread",rw:"Dwrite"}
    for key in (source,aw,rw):
        raw=slots["guard",key]["x"]
        assert raw==-1 or (raw>=0 and bits[raw//2]==raw%2)
    rf=[]
    for a,b in ((source,ar),(source,rr)):
        raw=slots["rf",a,b]["x"]
        assert bits[raw//2]==raw%2
        rf.append((local[a],local[b]))
    # Reachability in the actual typed declaration, before projection.
    reach={(a,b) for kind,a,b in meta["edges_in_native_order"] if kind in ("apo","po")}
    for z in meta["events"]:
        reach.update((a,b) for a in [u for u,v in reach if v==z]
                     for b in [v for u,v in reach if u==z])
    po,apo=[],[]
    for a in keys:
        for b in keys:
            if (a,b) in reach:
                (apo if blocks[a]==blocks[b] else po).append((local[a],local[b]))
    events=tuple(Event(local[k],k.split("/")[0],"R" if "read"==meta["events"][k]["kind"] else "W","r")
                 for k in keys)
    graph=Graph(events,tuple(po),tuple(apo),tuple(rf))
    models=strict_models(graph)
    facts,_=saturate(Branch(graph,(),graph.rf))
    cycles=sorted(p for p in facts if p[0]==p[1])
    return {"keys":local,"input":graph.document(),"orders":[x[2] for x in sorted(models)],
            "contradiction":explain(facts,cycles[0]) if cycles else None}


def study(root):
    archive=Archive(root)
    m0,s0,b0=translate(archive,"old")
    m1,s1,b1=translate(archive,"candidate")
    assert m0["layout"]==m1["layout"] and m0["events"].keys()==m1["events"].keys()
    for key,old in m0["events"].items():
        new=m1["events"][key]
        assert all(old[f]==new[f] for f in ("thread","kind","object","solver_address","type","guard"))
        old_stack=[frame["function"] for frame in old["frames"]]
        new_stack=[frame["function"] for frame in new["frames"]]
        if "/release_read_count/" in key:
            assert new_stack==old_stack+["__VERIFIER_atomic_release_read_lock"]
        else:
            assert new_stack==old_stack
    stream=archive.get("F/old/s8-input.bin")
    assert stream==archive.get("F/candidate/s8-input.bin")
    queries={}
    for side in ("old","candidate"):
        assert archive.get("S/"+side+"/s8-input.bin")==stream
        assert archive.get("S/"+side+"/s8-graph.tsv")==archive.get("F/"+side+"/s8-graph.tsv")
        command=json.loads(archive.get("F/"+side+"/command.json"))
        result=json.loads(archive.get("F/"+side+"/result.json"))
        prop,=[p for row in result for p in row.get("result",[])]
        assert prop["property"]=="reach_error.assertion.1"
        assert prop["status"]==("FAILURE" if side=="old" else "SUCCESS")
        assert command["model_reuse"] is False and "--32" in command["argv"]
        queries[side]={"argv":command["argv"][1:],"source_sha256":command["input_sha256"],
                       "property":prop["property"],"status":prop["status"],"trace_steps":len(prop.get("trace",[]))}
    assert queries["old"]["argv"]==queries["candidate"]["argv"]
    answer=archive.get("S/old/answer.txt").decode().splitlines()
    code,nv=map(int,answer[0].split())
    bits=list(map(int,answer[1].split()))
    assert code==0 and len(bits)==nv
    e0,e1=set(m0["edges_in_native_order"]),set(m1["edges_in_native_order"])
    def delta(a,b):
        return {"removed":sorted(a-b),"added":sorted(b-a)}
    def blocks(m):
        return set(map(tuple,m["apo_components"]))
    changes={}
    for k in sorted(m0["events"]):
        old,new=m0["events"][k],m1["events"][k]
        diff=[f for f in old if old[f]!=new[f]]
        if diff: changes[k]=diff
    basic={k for k in s0.keys()&s1.keys() if k[0] in ("guard","rf")}
    def alias_key(m):
        return {tuple((tuple(atom),sign) for atom,sign in group) for group in m["alias_groups"]}
    p0=projection(m0,s0,b0,bits)
    p1=projection(m1,s1,b1,bits)
    assert p0["orders"] and not p1["orders"] and p1["contradiction"]
    summary={"stable_comparison_roles":len(m0["events"]),"literal_values":nv,
             "ordered_input_sha256":sha(stream),"receipts":archive.receipts,"frozen_queries":queries,
             "counts":[dict(Counter(k for k,a,b in es)) for es in (e0,e1)],
             "semantic_edges":delta(e0,e1),"apo_components":delta(blocks(m0),blocks(m1)),
             "alias_groups":delta(alias_key(m0),alias_key(m1)),
             "changed_event_fields":changes,
             "changed_atom_fields":[[k,[f for f in s0[k] if s0[k][f]!=s1[k][f]]]
                                   for k in sorted(basic) if s0[k]!=s1[k]],
             "projection_P1":p0,"projection_P2_same_boolean_assignment":p1}
    return summary,{"P1":m0,"P2":m1}
