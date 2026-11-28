"""Build sealed first-query transactions from the pinned archives. No native solves or pair mapping on P0."""
import collections
import csv
import gzip
import hashlib
import io
import json
import re
import sys
from pathlib import Path
from frozen import blob, digest, require, save

ROOT=Path(__file__).resolve().parents[1]


def native_address(name):
    m=re.fullmatch(r"([^#]*)#\d+([^\d].*)",name)
    return m[1]+m[2] if m else name.partition("#")[0]


def prepare(repo, out, case, side):
    scale=json.loads((ROOT/"reports/evidence/pi0/scale.json").read_text())["cases"][case]
    plan=json.loads((ROOT/"configs/frozen-pairs.json").read_text())["cases"][case]
    base=f"reports/evidence/si1b/{case}"
    lock=scale[side]
    packed=blob(repo,lock["model"])
    require(digest(packed)==lock["compressed_sha256"],"model seal")
    nodes={}; names={}; edges=[]; guards=[]; blocks=collections.defaultdict(list)
    prior=set(); later=set(); sites={}; contexts={}; events={}; by_arg={}; bits=[]; targets=[]
    out.mkdir(parents=True,exist_ok=True); path=out/(side+".txn")
    h=hashlib.sha256(); clauses=0; n=lock["native_nvars"]
    with path.open("wb") as dest:
        def row(*items):
            line=("\t".join(map(str,items))+"\n").encode()
            dest.write(line);h.update(line)
        row("PI1.1",n,1,"d8c79eab/Closure-SC/v1")
        for data in gzip.GzipFile(fileobj=io.BytesIO(packed)):
            f=data.rstrip(b"\n").decode().split("\t"); t=f[0]
            if t=="C":
                clauses+=1;row(*f[1:])
            elif t=="K":
                # Preserve all encoding/configuration fields, including original argv content.
                config=json.dumps(f[1:],separators=(",",":")); row("CONFIG",config)
            elif t=="NODE":nodes[int(f[1])]=f[2:];names[f[2]]=int(f[1])
            elif t=="MEMBER":blocks[int(f[1])].append(int(f[2]))
            elif t=="IN":prior.add(tuple(map(int,f[1:])))
            elif t=="OUT":later.add(tuple(map(int,f[1:])))
            elif t=="EDGE":edges.append(f[1:])
            elif t=="GUARD":guards.append(f[1:])
            elif t=="TARGET":targets.append(f[1]);row("TARGET",f[1])
            elif t=="S":sites[int(f[1])]=int(f[-1]) if f[-1].isdigit() else 0
            elif t=="X":contexts[int(f[1])]=int(f[2])
            elif t=="E":events[f[1]]=(int(f[2]),f[3])
            elif t=="A":bits.append(f[1:])
            elif t=="N":
                require(int(f[1])==n and list(map(int,f[2:]))==lock["native_assumptions"],"query boundary")
                for a in f[2:]:row("ASSUME",a)
            elif t=="CO":raise ValueError("dynamic CO in immutable first-root model")
        require(targets==lock["targets"] and len(nodes)==len(names) and set(nodes)==set(range(len(nodes))),"incomplete model")
        require(clauses==sum(s["occurrences"] for s in lock["scopes"].values()),"input occurrence count")
        require(prior=={(b,a) for a,b in later},"reciprocal atomic order")
        guard_set={g[0] for g in guards}
        addr={};addr_inverse={};locations={}
        # add_init_writes copies the source PC of the first non-synthetic shared access
        # to this exact L1 SSA object, including the thread/frame and field/index suffix.
        first_actual={}
        for nm,(ctx,role) in events.items():
            if ctx>0 and role in ("write","read"):
                first_actual.setdefault(re.sub(r"#\d+","",nm,count=1),ctx)
        for i in sorted(nodes):
            name,cls,r,w,rep=nodes[i]
            label=native_address(name)
            require(addr.setdefault(cls,label)==label and addr_inverse.setdefault(label,cls)==cls,"address class mismatch")
            require(i in blocks[int(rep)],"atomic representative mismatch")
            # Native oc_location_map is populated for entries of oc_guard_map only.
            location=0
            if name in guard_set:
                context,kind=events[name]
                if context==-2:context=first_actual[name]
                location=sites[contexts[context]] if context else 0
            locations[name]=location
            row("NODE",name,label,int(r=="r"),int(w=="w"),int(events.get(name,(0,""))[0]==-2),location)
        domains=collections.defaultdict(list)
        closure_in=[{i} for i in nodes]; closure_out=[{i} for i in nodes]
        for kind,frm,to,port,installed_from,installed_to,observed in edges:
            a,b=names[frm],names[to]
            if kind=="rf":
                require((a,b,int(port))==(int(installed_from),int(installed_to),int(observed)),"installed RF alias")
                domains[b].append(a)
            elif kind in ("apo","po"):
                require(int(port)==-1,"conditional PO")
            elif kind!="race":raise ValueError(kind)
            if kind=="apo":
                for x in list(closure_in[a]):closure_out[x].update(closure_out[b])
                for x in list(closure_out[b]):closure_in[x].update(closure_in[a])
            row("EDGE",kind,a,b,port)
        require(prior=={(x,y) for x in nodes for y in closure_in[x] if x!=y}
                and later=={(x,y) for x in nodes for y in closure_out[x] if x!=y},"full native APO direction")
        for name,port in guards:row("GUARD",names[name],port)
        for block in sorted(blocks.values()):row("BLOCK",*sorted(block))
        for i in sorted(nodes):
            if nodes[i][2]=="r":row("DOMAIN",i,*sorted(domains[i]))
        if side=="P1":
            # Event keys/identity correspondences are introduced only by the P1 transaction.
            before=json.loads((out/"P0-seal.json").read_text())
            require(before["source_sha256"]==scale["P0"]["compressed_sha256"]
                    and before["transaction_sha256"]==digest((out/"P0.txn").read_bytes()),"wrong predecessor evidence")
            row("BASE",before["transaction_sha256"])
            old=json.loads((out/"P0-directory.json").read_text())
            event_maps=[]
            for s in ("P0","P1"):
                data=json.loads(gzip.decompress(blob(repo,f"{base}/join/{s}-ir.json.gz")))["event"]
                event_maps.append(data)
            def unique(directory, keys):
                grouped=collections.defaultdict(list)
                for nm,idx in directory.items():
                    if keys.get(nm):grouped[keys[nm]].append(idx)
                return {k:v[0] for k,v in grouped.items() if len(v)==1}
            a,b=unique(old["nodes"],event_maps[0]),unique(names,event_maps[1])
            event_pairs=sorted((a[k],b[k]) for k in a.keys()&b.keys())
            for x,y in event_pairs:row("EVENTMATCH",x,y)
            cat=blob(repo,scale["map_path"])
            require(digest(cat)==scale["map_sha256"],"diagnostic mapping digest")
            typed=json.loads(gzip.decompress(blob(repo,f"{base}/join/typed-keys.json.gz")))
            src=set();dst=set()
            for entry in csv.DictReader(io.StringIO(gzip.decompress(cat).decode()),delimiter="\t"):
                x=int(entry["old_variable"]);l=int(entry["positive_image"]);k=int(entry["witness_key"])
                require(x not in src and l//2 not in dst and 0<x<scale["P0"]["native_nvars"]
                        and 0<l//2<n and typed[k],"invalid certified mapping")
                src.add(x);dst.add(l//2);row("MATCH",x,l,k)
            if case=="fib-snapshot-11":
                coord=json.loads(blob(repo,"reports/evidence/d42/encoding.json"))
                for s,ids in (("P0",src),("P1",dst)):
                    require(not ids.intersection(map(int,coord[s]["alpha"]["permutation"])),"query-only coordinate bridge")
        row("END",clauses)
    seal=h.hexdigest();Path(str(path)+".sha256").write_text(seal+"\n")
    save(out/(side+"-directory.json"),dict(nodes=names,locations=locations,assignment_bits=bits))
    receipt=dict(case=case,side=side,source=lock["model"],source_sha256=lock["compressed_sha256"],transaction_sha256=seal,
                 native_vars=n,occurrences=clauses,event_count=len(nodes),edge_count=len(edges),guards=len(guards),
                 atomic_directions=len(prior),rf_domain_count=sum(n[2]=="r" for n in nodes.values()),properties=targets,
                 inputs=plan["staged"][side],read_future_mapping=side=="P1")
    save(out/(side+"-seal.json"),receipt)
    return receipt


if __name__=="__main__":
    repo,out,case,side=sys.argv[1:]
    print(json.dumps(prepare(repo,Path(out),case,side)))
