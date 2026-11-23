"""Single-update verification of a concurrent C program under its protected property."""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from incdeagle.model.identity import read
from incdeagle.repair import inspect, submit_manual
from incdeagle.workflow import doctor, execute, online


def main():
    if len(sys.argv)==3 and sys.argv[1]=="_online":
        online(Path(sys.argv[2]).resolve())
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command",required=True)
    sub.add_parser("doctor",help="check both fixed verifier binaries and the execution environment")
    check = sub.add_parser("inspect-case",help="verify the protected manifest and source hashes")
    check.add_argument("--case",type=Path,required=True,metavar="TASK_YAML")
    report = sub.add_parser("summarize",help="summarize completed and failed single-update runs")
    report.add_argument("--runs",type=Path,required=True)
    submit = sub.add_parser("submit-manual",help="deliver one local patch to a waiting native session")
    submit.add_argument("--run",required=True,type=Path)
    submit.add_argument("--patch",required=True,type=Path)
    submit.add_argument("--trace-sha256",required=True)
    submit.add_argument("--note",default="")
    for name in ("run-case","replay-pair"):
        help_text = "produce and verify one candidate" if name=="run-case" else "verify an existing frozen candidate with a fresh P0 session"
        command = sub.add_parser(name,help=help_text)
        command.add_argument("--case",required=True,type=Path,metavar="TASK_YAML")
        command.add_argument("--out",type=Path,help="new, exclusive run directory")
        command.add_argument("--check-model",action="store_true",help="also build a full diagnostic model after both verifiers finish")
        if name=="run-case":
            command.add_argument("--repair",required=True,choices=("manual","mini"))
            manual = command.add_mutually_exclusive_group()
            manual.add_argument("--patch",type=Path,help="manual unified diff, default is the case's patch.diff")
            manual.add_argument("--wait-patch",action="store_true",help="wait for a new patch submitted after the P0 counterexample")
            command.add_argument("--key-stdin",action="store_true",help="supply the mini controller credential privately on stdin")
            command.add_argument("--repair-input-sha256",help="require this exact minimized model input before the first mini call")
        else:
            command.add_argument("--from-run",type=Path,help="replay the exact candidate frozen by another run of the same P0")
    args = parser.parse_args()
    try:
        if args.command=="submit-manual":
            info = submit_manual(args.run.resolve(),args.patch,args.trace_sha256,args.note)
        elif args.command=="inspect-case":
            if args.case.name!="task.yaml":
                parser.error("--case takes the case's task.yaml")
            info = inspect(args.case.resolve().parent)
        elif args.command=="doctor":
            info = doctor()
            print(json.dumps(info,indent=2))
            return 0 if info["native_ready"] else 1
        elif args.command=="summarize":
            if not args.runs.is_dir():
                parser.error("The runs directory does not exist")
            rows = []
            for path in sorted(args.runs.rglob("workflow.json")):
                result = read(path)
                if result.get("schema")==1 and "run_id" in result:
                    rows.append({**{k:result.get(k) for k in ("case","method","status","agreement","candidate_sha256")},
                                 "run":str(path.parent)})
            info = {"runs":rows,"counts":dict(Counter(r["status"] for r in rows))}
        else:
            mode = args.repair if args.command=="run-case" else "replay"
            patch = getattr(args,"patch",None)
            stdin = getattr(args,"key_stdin",False)
            wait_patch = getattr(args,"wait_patch",False)
            expected = getattr(args,"repair_input_sha256",None)
            if ((patch or wait_patch) and mode!="manual") or ((stdin or expected) and mode!="mini"):
                parser.error("--patch is for manual repairs and --key-stdin is for mini")
            path, result = execute(args.case,method=mode,out=args.out,patch=patch,
                                   from_run=getattr(args,"from_run",None),key_stdin=stdin,check_model=args.check_model,
                                   wait_patch=wait_patch,repair_input_sha256=expected)
            print(json.dumps({"run":str(path),"status":result["status"],"agreement":result["agreement"],
                              "reason":result.get("reason") or result.get("online_reason")},ensure_ascii=False))
            return 0 if result["status"] in ("COMPLETED","OLD_NOT_VIOLATION") else 2
        print(json.dumps(info,indent=2,ensure_ascii=False))
        return 0
    except (OSError,ValueError,KeyError) as exc:
        print(str(exc),file=sys.stderr)
        return 2


if __name__=="__main__":
    sys.exit(main())
