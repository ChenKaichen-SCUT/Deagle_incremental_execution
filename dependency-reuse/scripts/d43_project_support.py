"""Project frozen Audit supports offline. All retention levels use one signed injection per case."""
import argparse
from array import array
from collections import Counter, defaultdict
from contextlib import contextmanager, ExitStack
import csv
import gzip
import hashlib
import json
import mmap
from pathlib import Path
import shutil
import struct
import subprocess

from cases42 import load
from d43_owner_probe import stream_receipt
from run_stock import BASE

PLAN = json.loads((BASE/"configs/d43-plan.json").read_text())
OP = ("Config","PO","APO","RF","Guard","Schema","SameAddress","Block")
STATE = ("matched","unmapped","mapped_absent","changed","unknown","query","opaque")
PAIR = struct.Struct("<IHBB")
FACT = struct.Struct("<4i")
SOURCE = BASE / "reports/evidence/d42/raw/release/files.json"


def check(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


@contextmanager
def zipped(path):
    with path.open("wb") as file, gzip.GzipFile(filename="", fileobj=file, mode="wb", mtime=0, compresslevel=6) as gz:
        yield gz


def tsv(path):
    with path.open() as f:
        yield from csv.DictReader(f, delimiter="\t")


def canonical(key):
    return json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode()


class Groups:
    def __init__(self):
        self.index = {}
        self.rows = []

    def add(self, key):
        value = self.index.get(key)
        if value is None:
            data = canonical(key)
            raw = hashlib.sha256(PLAN["seed"].encode() + b"\0" + data).digest()
            slot = int.from_bytes(raw[:8], "little") % 1024
            value = len(self.rows) + 1, slot
            self.index[key] = value
            self.rows.append((data, slot))
        return value


def frozen_read(path, root, index, files):
    record = index[str(path.relative_to(root))]
    check(path.stat().st_size == record["bytes"] and digest(path) == record["sha256"], "archive mismatch: "+str(path))
    files[str(path.relative_to(root))] = {k:record[k] for k in ("bytes","sha256")}
    return path


def signed_map(path):
    sides = [[-1],[-1]]
    for row in tsv(path):
        dest = sides[int(row["side"])]
        check(len(dest)==int(row["variable"]), "incomplete variable directory")
        dest.append(int(row["peer"]))
    for a,b in (sides, sides[::-1]):
        for i,p in enumerate(a):
            check(p == -1 or (2 <= p and p//2 < len(b) and b[p//2] == 2*i+(p&1)), "not a signed injection")
    return sides[0]


def translated(raw, mu):
    if raw in (-1,-2):
        return raw
    if raw >= 2 and raw//2 < len(mu) and mu[raw//2] >= 0:
        return mu[raw//2] ^ (raw&1)
    return None


def first_members(path):
    result = {}
    ordinal = 0
    with path.open("rb") as f:
        for line in f:
            if line.startswith(b"C\t"):
                ordinal += 1
                if line.startswith(b"C\tB"):
                    clause = tuple(sorted(set(map(int,line.split()[2:]))))
                    result.setdefault(clause,ordinal)
    return result


def event_owner(ctx, role, obj, storage, scopes):
    site = scopes.get(int(ctx))
    if site and site[1]>=0:
        return (*site,role,obj,storage)
    return ("initial",-2,role,obj,storage) if ctx=="-2" else None


def theory_key(fact,events,names):
    op,a,b,_ = fact
    ends = [] if op==0 else ([a,b] if op in (1,2,3,6) else [a])
    owners = [events.get(names[x]) for x in ends]
    if None in owners:
        return ("T","fallback",OP[op])
    if op==6:
        owners.sort(key=canonical)
    return ("T","decl",OP[op],*owners)


def owner_ranges(observed, original, work, gold_work, output):
    a,b = stream_receipt(observed,work),stream_receipt(original,gold_work)
    check(a["canonical_sha256"]==b["canonical_sha256"], "owner observation differs from Audit")
    seq = 0
    active = None
    previous = object()
    with observed.open("rb") as f, zipped(output) as out:
        out.write(b"first_G_or_C\tphase\tcontext\tthread\n")
        for row in f:
            if row.startswith(b"OWNER43\t"):
                check(active is None, "nested owner scope")
                _, phase, ctx, thread = row.rstrip().split(b"\t")
                active = b"\t".join((phase,ctx,thread))
            elif row == b"END43\n":
                check(active is not None, "unexpected scope exit")
                active = None
            elif row.startswith((b"G\t",b"C\t")):
                seq += 1
                if previous != active:
                    out.write(str(seq).encode()+b"\t"+(active or b"outside\t-1\t-1")+b"\n")
                    previous = active
        check(active is None and seq, "incomplete source stream")
        out.write(f"{seq+1}\tEND\t-1\t-1\n".encode())


def registry(proof):
    """Scan native declaration records including unused nodes; also authenticate the installed graph receipt."""
    with proof.open("rb") as f, mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data:
        check(data[:12]==b"DEAGD3\x02\x00\x04\x03\x02\x01", "unexpected Audit format")
        pos = 12
        sections = []
        for size in (16,4,8,16,12,8,12,4,4,4,4,4,20,1):
            n, = struct.unpack_from("<I",data,pos)
            sections.append((pos+4,n))
            pos += 4+size*n
            check(pos <= len(data), "truncated Audit")
        start,count = sections[12]
        nodes,total = sections[0]
        facts = {}
        for i in range(count):
            rid, op, a, b, c = struct.unpack_from("<IIiii",data,start+20*i)
            check(rid < total, "theory record id")
            kind, = struct.unpack_from("<I",data,nodes+16*rid+8)
            if kind == 12:
                facts.setdefault((op,a,b,c),len(facts)+1)
            else:
                check(kind==13, "non-theory record")
        pos,n = sections[13]
        return facts,data[pos:pos+n]


def installed(path, receipt):
    lookup,graph = {}, bytearray()
    with path.open("rb") as f:
        for line in f:
            if line.startswith(b"G\t"):
                graph.extend(line[2:])
            elif line.startswith(b"D "):
                _, *fact, state = line.split()
                fact = tuple(map(int,fact))
                check(fact not in lookup, "duplicate certificate")
                lookup[fact] = {b"M":0,b"C":3,b"U":4}[state]
    check(graph==receipt, "installed theory graph receipt mismatch")
    return lookup


def mark(bits, index):
    bits[index//8] |= 1 << (index%8)


def project_inputs(root, case, out, observer, archived_ranges=None):
    check(digest(SOURCE)==PLAN["archive_index_sha256"], "D4.2 index lock")
    index = json.loads(SOURCE.read_bytes())["files"]
    files = {}
    def read(path):
        return frozen_read(path,root,index,files)
    run = root/"functional"/case/"1"
    old = run/"reference/P0/native"
    new = run/"Mapping-only/P1/native"
    proof = read(old/"proof.bin")
    model = read(old/"model.tsv")
    receipt = json.loads(read(old/"receipt42.json").read_bytes())
    spec = load()[case]
    for name,h in spec["files_sha256"].items():
        check(digest(BASE/"bench"/case/name)==h, "frozen source changed")
    check(receipt["mode"]=="audit" and receipt["files"]["proof.bin"]==digest(proof) and
          receipt["files"]["model.tsv"]==digest(model), "Audit library binding")
    for side in ("P0","P1"):
        stock = run/"stock"/side
        meta = json.loads(read(stock/"run.json").read_bytes())
        read(stock/"result.json")
        for name,source in spec["inputs"][side].items():
            check(digest(read(stock/"work"/name))==spec["files_sha256"][source], "stock staged input")
        check(meta["argv"][1:]==spec["argv"] and meta["target"]==spec["target"] and
              meta["limits"]==spec["limits"] and meta["input_sha256"]==
              {n:spec["files_sha256"][p] for n,p in spec["inputs"][side].items()}, "stock config")
    mu = signed_map(read(new/"effective-map.tsv"))
    members = first_members(read(new/"boundary.tsv"))
    used = {int(r["occurrence"]):(int(r["use"]),r["status"],int(r["p1_permanent_occurrence"]))
            for r in tsv(read(new/"inputs42.tsv"))}
    theory_use = {tuple(int(r[k]) for k in ("op","a","b","c")):(int(r["use"]),r["status"])
                  for r in tsv(read(new/"facts42.tsv"))}
    registered,graph = registry(proof)
    cert = installed(read(new/"delta/declarations.txt"),graph)
    check(registered.keys() <= cert.keys() and theory_use.keys() <= registered.keys(), "declaration inventory")
    for part in ("catalog42.tsv",):
        read(new/part)
    # The projection never reads P1 use receipts; only the separate summary joins them.
    ranges = out/"owners.tsv.gz"
    if archived_ranges:
        lock=json.loads((archived_ranges.parent/"owners.json").read_bytes())
        check(lock["case"]==case and lock["audit_model_sha256"]==receipt["files"]["model.tsv"] and
              lock["ranges_sha256"]==digest(archived_ranges),"source ranges do not match the Audit model")
        if archived_ranges.resolve()!=ranges.resolve():
            shutil.copyfile(archived_ranges,ranges)
    else:
        owner_ranges(observer/"on/model.tsv", model, observer/"on/work", old.parent/"work", ranges)
        probe=json.loads((observer/"on/observer.json").read_bytes())
        lock=dict(case=case,audit_model_sha256=receipt["files"]["model.tsv"],ranges_sha256=digest(ranges),
                  observer_canonical_sha256=probe["canonical_sha256"],observer_scopes=probe["scopes"])
    save(out/"owners.json",lock)
    groups = Groups()
    scopes,events,names = {},{},{}
    gates = {}
    count,statuses,origin,assignment = Counter(),Counter(),Counter(),Counter()
    directory_bytes = Counter()
    b_records = bytearray()
    bbit = {u:bytearray() for u in ("audit","all")}
    tbit = {u:bytearray((len(registered)+7)//8) for u in bbit}
    with ExitStack() as stack:
        dirs = {u:stack.enter_context(zipped(out/f"directory-{u}.bin.gz")) for u in bbit}
        for d in dirs.values():
            d.write(b"D43DIR1\x00")
        def emit(domain,idx,record,use,state):
            for u in bbit:
                if u=="audit" and not (use&2):
                    continue
                mark((bbit if domain=="B" else tbit)[u],idx-1)
                dirs[u].write(domain.encode()+record)
                directory_bytes[u+domain] += 1+len(record)
                count[u+domain] += 1
                statuses[u+domain+":"+STATE[state]] += 1
        with gzip.open(ranges,"rt") as rf, model.open() as f:
            rr = csv.reader(rf,delimiter="\t")
            next(rr)
            next_change = next(rr)
            seq = occ = 0
            for line in f:
                tag = line.partition("\t")[0]
                if tag not in ("X","E","NODE","C","G"):
                    continue
                v = line.rstrip("\n").split("\t")[1:]
                if tag=="X":
                    scopes[int(v[0])] = (int(v[1]),int(v[2]))
                elif tag=="E":
                    name,ctx,role,obj,typ,storage = v
                    event = event_owner(ctx,role,obj,storage,scopes)
                    if name in events and events[name]!=event:
                        event = None
                    events[name] = event
                elif tag=="NODE":
                    names[int(v[0])] = v[1]
                else:
                    seq += 1
                    if seq==int(next_change[0]):
                        _,phase,ctx,thread = next_change
                        site = scopes.get(int(ctx))
                        own = ("B","ssa",phase,site[0],int(thread)) if site and int(thread)>=0 else None
                        next_change = next(rr)
                    if tag=="G":
                        op,raw = v[:2]
                        atom = int(raw)//2
                        if atom>=1 and atom not in gates:
                            gates[atom] = (seq,own or ("B","gate",op,atom))
                        continue
                    occ += 1
                    scope = v[0]
                    lits = list(map(int,v[1:]))
                    use,reason,ref = used.get(occ,(0,None,0))
                    for u in bbit:
                        if (occ-1)%8==0:
                            bbit[u].append(0)
                    if scope=="B":
                        key = own
                        if key is None:
                            candidates = (gates[l//2] for l in lits if l>=2 and l//2 in gates)
                            key = max(candidates, default=(0,("B","fallback",phase)))[1]
                            assignment["first_gate_owner" if key[1]!="fallback" else "phase_fallback"] += 1
                        else:
                            assignment["direct_checked_SSA"] += 1
                        group,slot = groups.add(key)
                        origin[key[1]] += 1
                        target = [translated(l,mu) for l in lits]
                        witness = 0
                        if None in target:
                            state = 1
                        else:
                            witness = members.get(tuple(sorted(set(target))),0)
                            state = 0 if witness else 2
                        if reason is not None:
                            check((reason,ref)==(STATE[state],witness), f"input witness at {occ}")
                        emit("B",occ,struct.pack("<III",occ,group,len(lits))+
                             struct.pack(f"<{len(lits)}i",*lits),use,state)
                    else:
                        check(scope in ("Q","U") and (not use or reason=="scope") and not (use&2),"input scope")
                        group = slot = 0
                        state = 5 if scope=="Q" else 6
                    b_records.extend(PAIR.pack(group,slot,state,use))
            check(int(next_change[0])==seq+1 and next_change[1]=="END" and next(rr,None) is None, "truncated owner ranges")
        t_records = bytearray()
        for fact,idx in registered.items():
            op,a,b,c = fact
            key = theory_key(fact,events,names)
            group,slot = groups.add(key)
            origin["T_"+key[1]] += 1
            use,old_state = theory_use.get(fact,(0,None))
            state = cert[fact]
            if old_state:
                check(old_state=={0:"M",3:"C",4:"U"}[state], "declaration verdict")
            if op in (3,4) and state==0 and c>=2:
                check(translated(c,mu) is not None, "RF/Guard port not mapped")
            t_records.extend(FACT.pack(*fact)+PAIR.pack(group,slot,state,use))
            emit("T",idx,struct.pack("<II",idx,group)+FACT.pack(*fact),use,state)
    for u in bbit:
        with zipped(out/f"used-{u}.bin.gz") as f:
            f.write(b"D43USE1\x00"+struct.pack("<II",occ,len(registered))+bbit[u]+tbit[u])
    with (out/"leaves.bin").open("wb") as f:
        f.write(b"D43LEF1\x00"+struct.pack("<II",occ,len(registered))+b_records+t_records)
    with zipped(out/"groups.tsv.gz") as f:
        f.write(b"id\tsmall\tlarge\tcanonical_key\n")
        for i,(key,slot) in enumerate(groups.rows,1):
            f.write(f"{i}\t{slot%256}\t{slot}\t".encode()+key+b"\n")
    with (out/"mu.bin").open("wb") as f:
        array("i",mu).tofile(f)
    # Additional slots only if a future backend registers every declaration the graph could supply.
    # This inventory is outside both frozen UsedLeaf sets and never participates in admission.
    extra_dirty = set()
    for fact in cert.keys()-registered.keys():
        if cert[fact]:
            key = canonical(theory_key(fact,events,names))
            h = hashlib.sha256(PLAN["seed"].encode()+b"\0"+key).digest()
            extra_dirty.add(int.from_bytes(h[:8],"little")%1024)
    result = dict(case=case,plan_sha256=digest(BASE/"configs/d43-plan.json"),files=files,
                  B_occurrences_including_scope=occ,registered_T=len(registered),static_graph_T=len(cert),
                  unregistered_static_T_by_rule=dict(Counter(OP[f[0]] for f in cert.keys()-registered.keys())),
                  unregistered_dirty_large_slots=sorted(extra_dirty),
                  groups=len(groups.rows),owner_source=origin,boolean_assignment=assignment,universe=count,leaf_verdicts=statuses,
                  directory_record_bytes=directory_bytes,used_bitmap_payload_bytes=len(bbit["all"])+len(tbit["all"]),
                  directory_header_bytes=8,bitmap_header_bytes=16,owner_ranges_sha256=digest(ranges))
    save(out/"inputs.json",result)
    return proof,new


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--d42",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--engine",required=True,type=Path)
    src=p.add_mutually_exclusive_group(required=True)
    src.add_argument("--owners",type=Path,help="paired P0 owner probe receipts")
    src.add_argument("--ranges",type=Path,help="published per-case owner range streams")
    p.add_argument("--case",choices=PLAN["cases"],action="append")
    a=p.parse_args()
    for case in a.case or PLAN["cases"]:
        out = a.out/case
        out.mkdir(parents=True,exist_ok=True)
        proof,new = project_inputs(a.d42,case,out,a.owners/case if a.owners else None,
                                   a.ranges/case/"owners.tsv.gz" if a.ranges else None)
        subprocess.run([a.engine,proof,out/"leaves.bin",out/"mu.bin",new/"catalog42.tsv",out],check=True)
        for name in ("leaves.bin","births.tsv"):
            path = out/name
            with path.open("rb") as f, zipped(out/(name+".gz")) as z:
                shutil.copyfileobj(f,z)
            path.unlink()
        (out/"mu.bin").unlink()


if __name__ == "__main__":
    main()
