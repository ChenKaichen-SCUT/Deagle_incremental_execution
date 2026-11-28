"""Check every finished E pair against the frozen D exact results after the timing matrix."""
from collections import Counter
import csv
from functools import lru_cache
from pathlib import Path

from audit_d43d import audit, batches, model_digest
from compact43 import DenseLibrary, QUERY, UNKNOWN, require
from d43_project_support import digest
from run_d42 import compare
from run_d43d import read
from run_stock import BASE
from summarize_d43d import keyed


D_INDEX = "fc323b1764078073b641a28d3f16b914984889ccb804760c455997b02c3e28c5"
PREP_FILES = ("effective-map.tsv", "births.tsv", "input-matches.tsv", "theory-matches.tsv",
              "eligible.tsv", "ready.tsv", "delta/declarations.txt")
HIT_NAMES = ("watch_unit", "watch_conflict", "analyze", "minimize")


def table(path):
    with path.open() as source:
        return list(csv.DictReader(source, delimiter="\t"))


class Reference:
    def __init__(self, root, B, old, output):
        self.root, self.B, self.old, self.output = root, B, old, output
        index = BASE / "reports/evidence/d43d/raw/files.json"
        require(digest(index) == D_INDEX, "D raw index changed")
        self.index = read(index)["files"]

    @lru_cache(maxsize=None)
    def file(self, name):
        p = self.root / name
        require(digest(p) == self.index[name]["sha256"], "D raw file changed: "+name)
        return p

    @lru_cache(maxsize=None)
    def model(self, case, relative, manifest):
        base = f"matrix/{case}/{relative}/"
        return model_digest(self.file(base+"native/"+manifest), self.file(base+"run.json"))


def record_stats(folder):
    native = folder/"native"
    lib = DenseLibrary((native/"dense.bin").read_bytes())
    counts = keyed(native/"dense.bin.stats")
    for key in ("legacy_recorders","SupportStore_instances","proof_nodes","proof_parent_edges",
                "duplicate_condition_nodes","legacy_quality_enabled"):
        require(counts[key] == 0, "unexpected production recorder "+key)
    widths = {"B":Counter(), "T":Counter()}
    birth_bytes = 0
    for _, _, lits, b, t in lib.births():
        if lits is None:
            birth_bytes += 6
        else:
            birth_bytes += 266 + 4*len(lits)
            widths["B"][b.bit_count()] += 1
            widths["T"][t.bit_count()] += 1
    files = read(native/"library.json")["files"]
    for name, row in files.items():
        require(digest(native/name)==row["sha256"] and (native/name).stat().st_size==row["bytes"], "sealed P0 "+name)
    size = files["dense.bin"]["bytes"]
    info = dict(counts, permanent_boolean_occurrences=sum(g not in (QUERY,UNKNOWN) for g in lib.boolean),
                used_B=sum(int(x).bit_count() for x in lib.used[0]), used_T=sum(int(x).bit_count() for x in lib.used[1]),
                used_bitmap_bytes=sum(map(len,lib.used)), birth_stream_bytes=birth_bytes,
                dense_bytes=size, static_directory_bitmaps_and_framing_bytes=size-birth_bytes,
                model_bytes=files["model.tsv"]["bytes"],
                library_bytes=sum((native/k).stat().st_size for k in (*files,"library.json","library.sha256")),
                width_histogram_permanent={k:dict(sorted(c.items())) for k,c in widths.items()})
    return info


def same_in_order(folder, case, n, ref):
    prod=folder/"compact/P0"; reuse=folder/"compact-reuse/P1"; cold=folder/"compact-cold/P1"
    dirs=[arm/"native" for arm in (cold,reuse)]
    producer=digest(prod/"native/library.json")
    dense=digest(prod/"native/dense.bin")
    context=f"{case} round {n}"
    require(dense==digest(ref.file(f"matrix/{case}/compact/P0/native/dense.bin")),context+" P0 birth/tag bytes")
    require(model_digest(prod/"native/model.tsv",prod/"run.json")==ref.model(case,"compact/P0","model.tsv"),context+" old model")
    delta=[]
    for arm,native in zip((cold,reuse),dirs):
        require(model_digest(native/"boundary.tsv",arm/"run.json")==ref.model(case,"compact-reuse/P1","boundary.tsv"),
                context+" live P1")
        d=read(native/"compact-delta.json"); delta.append(d)
        require(d["producer"]==read(native/"control43.json")["library_sha256"]==producer,
                context+" distinct P0 seal")
        require(set(d["inputs_read"])=={"dense.bin","model.tsv","library.json","library.sha256"},context+" P0 files")
        timing=keyed(native/"import-time.tsv")
        require(timing["P1_proof_recorder"]==timing["P1_dense_recorder"]==0,context+" recorder in P1")
    hashes={k:digest(dirs[1]/k) for k in PREP_FILES}
    identical={k:(digest(dirs[0]/k)==v) for k,v in hashes.items()}
    shape=[keyed(p/"structure-stats.tsv") for p in dirs]
    if not all(identical.values()):
        raise ValueError(f"cold and reuse preparation differed {context}: {identical}, budgets: {shape}")
    expected_mu=digest(ref.file(f"matrix/{case}/compact-reuse/P1/native/effective-map.tsv"))
    same_map=hashes["effective-map.tsv"]==expected_mu
    if same_map:
        exact=batches(ref.file(f"exact/{case}/batch-rows.tsv"))
        old=ref.file(f"matrix/{case}/compact-reuse/P1/native/delta/declarations.txt")
        require(hashes["delta/declarations.txt"]==digest(old),context+" changed declaration certificates")
        oracle="D independently replayed exact under identical dense/canonical models/mu/certificates"
    else:
        require(ref.B is not None and ref.old is not None,context+" new mu requires offline B and D42")
        location=ref.output/"new-maps"/str(n)
        view=location/"matrix"
        view.mkdir(parents=True,exist_ok=True)
        (view/case).symlink_to(folder.resolve(),target_is_directory=True)
        audit_folder=location/case
        audit(case,view,ref.B,ref.old,ref.root/"offline-tools",
              ref.file(f"oracles/{case}/native-learns.tsv"),audit_folder)
        exact=batches(audit_folder/"batch-rows.tsv")
        oracle="new offline exact replay under actual mu"
    eligible=batches(dirs[1]/"eligible.tsv")
    selected=batches(dirs[1]/"ready.tsv",True)
    require(all(exact.get(i)==v for i,v in eligible.items()),context+" admission outside exact")
    require(list(eligible)==sorted(eligible) and list(selected.items())==list(eligible.items())[:512],
            context+" selection order")
    cold_rows=table(dirs[0]/"imports.tsv")
    require([int(r["id"]) for r in cold_rows]==list(selected)
            and all(r["disposition"]=="check_only" for r in cold_rows)
            and not any(int(r[k]) for r in cold_rows for k in HIT_NAMES)
            and not table(dirs[0]/"hits.tsv"),context+" cold attached/hit")
    rows=table(dirs[1]/"imports.tsv")
    require([int(r["id"]) for r in rows]==list(selected),context+" native import order")
    first={(int(r["id"]),HIT_NAMES[int(r["use"])]):r for r in table(dirs[1]/"hits.tsv")}
    policy=read(dirs[1]/"policy.json")
    families=[]
    consumed=set()
    for f in ("B","M","T","scope_only"):
        group=[r for r in rows if r["family"]==f]; distinct=0
        for row in group:
            i=int(row["id"])
            require((f,list(map(int,row["translated"].split())))==selected[i],context+" signed literals changed")
            distinct+=any(int(row[k]) for k in HIT_NAMES)
            for k in HIT_NAMES:
                require(bool(int(row[k]))==((i,k) in first),context+" missing native first-use witness")
                if int(row[k]):
                    consumed.add((i,k))
        family=policy["classes"][f]
        families.append(dict(family=f,born=family.get("births",0),query=family.get("query",0),unknown=family.get("unknown",0),
                        permanent=family.get("permanent",0),mapped=family.get("mapped",0),
                        exact=sum(fam==f for fam,_ in exact.values()),eligible=family.get("eligible",0),
                        selected=family.get("chosen",0),attached=sum(r["disposition"]=="attached" for r in group),
                        distinct_hits=distinct,**{k:sum(int(r[k]) for r in group) for k in HIT_NAMES}))
    require(consumed==set(first),context+" spurious first-use event")
    evidence=dict(seal_sha256=producer,dense_sha256=dense,prep_sha256=hashes,identical_cold_reuse=identical,
                  same_mu_as_D=same_map,exact_oracle=oracle,independent_false_admissions=0,
                  dirty_slots=delta[1]["dirty_slots"],groups=delta[1]["groups"],
                  budget=[{k:r[k] for k in ("rounds","checks","added","ambiguous","collisions","stop")} for r in shape])
    return evidence,families


def correctness(folder,case):
    checked={}
    for mode,sides in (("off",("P0","P1")),("compact",("P0",)),("light-quality",("P0",)),
                       ("light-no-quality",("P0",)),("compact-cold",("P1",)),("compact-reuse",("P1",)),
                       ("stock-clock",("P0","P1"))):
        for side in sides:
            sample=folder/mode/side
            checked[f"{mode}/{side}"]=compare(folder/"stock"/side,sample,mode=="stock-clock")
            if mode in ("light-quality","light-no-quality","compact","compact-cold"):
                compare(folder/"off"/side,sample,True)
    if case=="fib-snapshot-11":
        for v in checked.values():
            contract=v["properties"]
            require(contract["classification"]=="INCOMPLETE_UNWINDING" and len(contract["unwinding_property_ids"])==3,
                    "historical unwind status")
    else:
        require(checked["compact/P0"]["properties"]["classification"]=="VIOLATION" and
                checked["compact-reuse/P1"]["properties"]["classification"]=="BOUNDED_PASS","repair status")
    return checked
