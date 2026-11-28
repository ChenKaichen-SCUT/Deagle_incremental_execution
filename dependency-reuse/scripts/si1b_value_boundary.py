"""Validate the first live P1 boundary against the offline value experiment's sealed reference."""
from collections import Counter
import hashlib
import json
from pathlib import Path

from si1a_census import fingerprint
from si1b_review_space import check, digest


def model_certificate(path, work):
    # fingerprint canonicalizes only the existing SITE41 working-directory encoding,
    # term handles and unordered definition hints. Keep the native literal streams ordered.
    full = fingerprint(path, str(work))
    groups = {k: hashlib.sha256() for k in ("permanent", "query_inputs", "gates", "installed_graph", "named_ports", "boundary")}
    counts = Counter()
    root = None
    ended = False
    graph = {b"EDGE",b"GUARD",b"NODE",b"MEMBER",b"IN",b"OUT",b"CO"}
    with path.open("rb") as f:
        check(f.readline()==b"DEAGLE-D1\t1\n", "boundary header")
        for line in f:
            tag,_,rest = line.partition(b"\t")
            if root is not None:
                check(not ended and line==b"READY\tD4-P1-v1\n","extra or missing first-root boundary")
                ended = True
                continue
            if tag==b"C":
                scope = rest.split(b"\t",1)[0].strip()
                check(scope in (b"B",b"Q"), "unexpected input scope")
                group = "permanent" if scope==b"B" else "query_inputs"
            elif tag in graph: group = "installed_graph"
            elif tag==b"G": group = "gates"
            elif tag==b"A": group = "named_ports"
            elif tag==b"N":
                root = tuple(map(int,rest.split()))
                group = "boundary"
            else:
                check(tag!=b"READY","premature root boundary")
                continue
            groups[group].update(line)
            counts[group]+=1
    check(ended and root and root[0]>1 and all(counts[k]>0 for k in groups), "incomplete native model")
    return dict(canonical=full["canonical_sha256"], counts=counts, nvars=root[0], query=list(root[1:]),
                streams={k:h.hexdigest() for k,h in groups.items()})


def batch_bytes(path, nvars, expected):
    raw = path.read_bytes()
    check(hashlib.sha256(raw).hexdigest()==expected["sha256"],"fixed batch checksum")
    lines = raw.splitlines()
    check(lines and lines[0].split()==[b"D4-selected-v1",str(nvars).encode(),str(expected["selected"]).encode()] and
          len(lines)==expected["selected"]+1,"batch header or row count")
    prev=0
    for line in lines[1:]:
        birth,family,arity,*lits = line.split()
        i=int(birth)
        check(i>prev and family in (b"B",b"M",b"T") and len(lits)==int(arity) and
              all(2<=int(l)<2*nvars for l in lits),"invalid signed batch")
        prev=i
    return raw


def expected_args(lib, native, tools, arm, config):
    mode = "record-cold" if arm=="cold" else "reuse"
    return ["--d43-load",str(lib),"--d4-mode",mode,"--d4-out",str(native),"--d4-tools",str(tools),
            "--d41-identities","--d4-search-log",str(native/"search.tsv"),*config]


def validate(root, native, tools, ctl, cwd, argv, elf, seal_hash):
    check(ctl["format"]=="SI1B-value-diagnostic-v1" and ctl["arm"] in ("cold","A","new"),"diagnostic input only")
    seal=root/"seal.json"
    check(digest(seal)==seal_hash,"untrusted diagnostic seal")
    spec=json.loads(seal.read_bytes())
    check(spec["format"]==ctl["format"] and spec["case"]==ctl["case"] and elf==spec["native_elf"] and
          argv==expected_args(root,native,tools,ctl["arm"],spec["argv"]),"live native configuration or binary mismatch")
    check(all(digest(cwd/name)==sha for name,sha in spec["inputs"].items()),"live source checksum")
    model=model_certificate(native/"boundary.tsv",cwd)
    check(model==spec["model"],"live P1 model differs from admission model")
    data={arm:batch_bytes(root/(arm+".ready.tsv"),model["nvars"],spec["batches"][arm]) for arm in ("A","new")}
    batch="A" if ctl["arm"]=="A" else "new"
    return data[batch],dict(format=ctl["format"],case=spec["case"],arm=ctl["arm"],canonical_model=model,
        actual_inputs=spec["inputs"],checked_elf=elf,seal_sha256=seal_hash,batch=batch,
        checked_batches={arm:hashlib.sha256(v).hexdigest() for arm,v in data.items()},P1_identity_registration=False)
