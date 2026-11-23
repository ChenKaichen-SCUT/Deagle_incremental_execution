#!/usr/bin/env python3
"""Run one protected, bounded Stage 5 case against its original property."""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from incdeagle.model.identity import file_sha, read, save
from incdeagle.theory.cache import collect
from scripts.stage2.check_case import load_case
from scripts.stage4.session import CASES, run_pair


class TheorySession:
    binary = ROOT / "third_party/deagle-stage5/src/cbmc/deagle_exe"
    release_lock = ROOT / "configs/stage05.lock.json"

    def prepare(self, directory, lock):
        helper = ROOT / "scripts/stage5/theory_worker.py"
        modules = [helper, *sorted((ROOT / "incdeagle/theory").glob("*.py")),
                   ROOT/"incdeagle/model/identity.py", ROOT/"incdeagle/model/observe.py"]
        save(directory / "theory-settings.json", {
            "native":lock, "schema":1, "backend":"SC/ClosureSolver/no SimpSolver",
            "implementation":{str(p.relative_to(ROOT)):file_sha(p) for p in modules},
        })
        return {"INCDEAGLE_S5_ROOT":str(directory),"INCDEAGLE_S5_HELPER":str(helper)}

    def capture(self, directory, manifest):
        return collect(directory, manifest)


def run(case, out):
    session = run_pair(case, out, theory=TheorySession())
    old = read(out/"old/theory-export.json")
    plan = read(out/"candidate/native-plan.json")
    audit_path = out/"candidate/theory-validation.json"
    if not plan["valid_plan"]:
        audit = {"accepted":0, "validation_rejected":old["unique"], "fingerprint_ns":None,
                 "candidate_audit_total_ns":None, "binding_ns":None,
                 "context_differences":["native_rejected_or_unavailable_binding_plan"]}
    else:
        audit = read(audit_path)
        if audit["validation_rejected"] is None:
            audit["validation_rejected"] = old["unique"]
    if plan["planned"] != audit["accepted"]:
        raise ValueError("Candidate solver did not receive the audited local plan")
    path = out/"candidate/native-import.json"
    native = read(path) if path.is_file() else {"rows":[], "import_ns":None}
    submitted = sum(r["effect"] != "already_inconsistent" for r in native["rows"])
    imported = sum(r["effect"] in ("attached","enqueued","contradiction") for r in native["rows"])
    stats = {k:old[k] for k in ("exported","supported","deduplicated","unique","export_rejected","old_audit_ns")}
    stats.update(accepted=audit["accepted"], validation_rejected=audit["validation_rejected"],
                 rejected=old["export_rejected"]+audit["validation_rejected"], imported=imported,
                 submitted=submitted, no_effect=submitted-imported,
                 not_submitted=audit["accepted"]-submitted, native_rows=native["rows"],
                 context_differences=audit["context_differences"], old_context=old["context_sha256"],
                 new_context=audit.get("context_sha256"), old_fingerprint_ns=old["fingerprint_ns"],
                 new_fingerprint_ns=audit["fingerprint_ns"], audit_ns=audit["candidate_audit_total_ns"],
                 binding_ns=audit["binding_ns"], import_ns=native["import_ns"])
    if not (stats["exported"] == stats["export_rejected"]+stats["unique"]+stats["deduplicated"] and
            stats["unique"] == stats["accepted"]+stats["validation_rejected"] and
            stats["accepted"] == stats["imported"]+stats["no_effect"]+stats["not_submitted"]):
        raise ValueError("Inconsistent theory counters")
    save(out/"theory-summary.json", stats)
    print(case.name, session["path"], session["candidate"]["classification"], "OC",
          *(stats[k] for k in ("exported","supported","accepted","imported")), stats["context_differences"])


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("case",choices=sorted(CASES))
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--case-dir",type=Path)
    p.add_argument("--contained",action="store_true",help=argparse.SUPPRESS)
    args = p.parse_args()
    case = args.case_dir.resolve() if args.case_dir else CASES[args.case]
    if case.name != args.case:
        p.error("case directory does not match its manifest identifier")
    if args.contained:
        run(case,args.out.resolve())
    else:
        _,gamma,_ = load_case(case)
        command = [sys.executable,"-B",str(Path(__file__).resolve()),args.case,"--out",str(args.out.resolve()),
                   "--case-dir",str(case),"--contained"]
        sys.exit(subprocess.run(["systemd-run","--quiet","--wait","--pipe","--collect",
                 "-p","WorkingDirectory="+str(ROOT),"-p","MemoryMax="+str(gamma["limits"]["memory_bytes"]),
                 "--",*command]).returncode)
