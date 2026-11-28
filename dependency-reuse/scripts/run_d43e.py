"""Execute the pre-registered serial matrix against the immutable D-stage build."""
import argparse
import fcntl
import json
import os
import platform
from pathlib import Path
import statistics
import subprocess
import time

from cases42 import load
from d43_prepare import tool_hashes
from diff_d1 import digest
from run_d43b import capture
from run_d43d import live, model, read, run_one
from run_stock import BASE, save


def total(folder):
    meta = read(folder / "run.json")
    if meta["timed_out"] or meta["exit_code"] not in (0, 10) or not read(folder / "outcome.json")["ok"]:
        raise ValueError("invalid timed sample " + str(folder))
    return meta["wall_ns"] + meta.get("setup_ns", 0) + meta.get("seal_ns", 0)


def signed_gains(folder):
    sp = total(folder / "stock/P0")
    sn = total(folder / "stock/P1")
    cp = total(folder / "compact/P0")
    cn = total(folder / "compact-reuse/P1")
    return {"P1": (sn-cn)/sn, "cycle": (sp+sn-cp-cn)/(sp+sn)}


def trigger(matrix, cases):
    values = {}
    for case in cases:
        pairs = []
        for n in range(1, 4):
            try:
                pairs.append(signed_gains(matrix / case / str(n)))
            except (OSError, ValueError, KeyError) as error:
                pairs.append({"incomplete": str(error)})
        complete = all("incomplete" not in row for row in pairs)
        by_metric = {}
        for key in ("P1", "cycle"):
            xs = [row[key] for row in pairs if key in row]
            by_metric[key] = {"paired": xs, "complete": complete,
                              "trigger": complete and statistics.median(xs) >= .05 and sum(x > 0 for x in xs) >= 2}
        values[case] = by_metric
    return {"cases": values, "extend": any(m["trigger"] for c in values.values() for m in c.values())}


def rotation(index):
    arms = read(BASE / "configs/d43-plan.json")["timing_future"]["orders"][index-1]
    light = ["light-quality", "light-no-quality"]
    if index % 2 == 0:
        light.reverse()
    return [arm for slot in arms for arm in (light if slot == "light42" else [slot])]


def execute(binary, tools, observer, root):
    specs = load()
    plan_file = BASE / "configs/d43e-execution.json"
    plan = read(plan_file)
    lock = read(BASE / "reports/evidence/d43d/build.json")
    original = read(BASE / "configs/build.json")
    stock = Path(original["binary_path"])
    build = digest(binary)
    stock_hash = digest(stock)
    observer_hash = digest(observer)
    if (list(specs) != plan["case_order"] or build != lock["production_elf_sha256"]
            or stock_hash != lock["unmodified_stock_elf_sha256"] or stock_hash != original["binary_sha256"]
            or observer_hash != lock["stock_clock_observer_elf_sha256"]
            or tool_hashes(tools) != lock["production_worker"]["names_and_sha256"]):
        raise ValueError("unapproved inputs, production build, helpers or stock")
    root.mkdir(parents=True, exist_ok=True)
    os.sched_setaffinity(0, {0})
    lease = (root.parent / "d43e-timing.lock").open("a")
    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    matrix = root / "matrix"
    manifest = dict(build=build, stock=stock_hash, observer=observer_hash, workers=tool_hashes(tools),
                    case_order=list(specs), orders=[rotation(i) for i in range(1, 6)],
                    approved_base=plan["review_base"], plan_sha256=digest(plan_file),
                    parent_plan_sha256=digest(BASE / "configs/d43-plan.json"), cpu_affinity=sorted(os.sched_getaffinity(0)),
                    limits={case:spec["limits"] for case,spec in specs.items()},
                    monotonic_resolution_s=time.get_clock_info("monotonic").resolution)
    if (root / "manifest.json").exists():
        if read(root / "manifest.json") != manifest:
            raise ValueError("resume configuration mismatch")
    else:
        save(root / "manifest.json", manifest)
        save(root / "preflight.json", {"kernel": platform.release(), "loadavg": Path("/proc/loadavg").read_text().strip(),
             "processes": subprocess.check_output(["ps", "-eo", "pid,psr,stat,comm"], text=True),
             "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    def sample(case, n, mode, side, callback):
        path = matrix / case / str(n) / mode / side
        if (path / "outcome.json").is_file():
            return
        if path.exists():
            raise RuntimeError("incomplete existing sample retained: " + str(path))
        ident = f"{n} {case} {mode}/{side}"
        start = time.monotonic_ns()
        with (root / "schedule.jsonl").open("a") as f:
            print(json.dumps(dict(sample=ident, start_ns=start)), file=f)
        try:
            callback(path)
            outcome = {"ok": True}
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, AssertionError) as err:
            path.mkdir(parents=True, exist_ok=True)
            outcome = {"ok": False, "error": f"{type(err).__name__}: {err}"}
        outcome.update(sample=ident, start_ns=start, end_ns=time.monotonic_ns())
        save(path / "outcome.json", outcome)
        print(ident, "ok" if outcome["ok"] else outcome["error"], flush=True)

    def round_(n):
        for case, spec in specs.items():
            producer = matrix / case / str(n) / "compact/P0"
            for mode in rotation(n):
                if mode == "stock":
                    for side in ("P0", "P1"):
                        sample(case, n, mode, side, lambda p: run_one(stock,spec,case,side,p,[],stock_hash))
                elif mode == "off":
                    for side in ("P0", "P1"):
                        sample(case, n, mode, side, lambda p: model(binary,spec,case,side,p,build))
                elif mode.startswith("light-"):
                    sample(case,n,mode,"P0",lambda p: capture(binary,build,case,spec,mode,p))
                else:
                    sample(case,n,"compact","P0",lambda p: model(binary,spec,case,"P0",p,build,tools))
                    sample(case,n,mode,"P1",lambda p: live(binary,tools,spec,case,p,producer/"native",
                                                           "reuse" if mode=="compact-reuse" else "record-cold",build))

    for n in range(1,4):
        round_(n)
    decision = trigger(matrix, specs)
    save(root / "confirmation.json", decision)
    rounds = 5 if decision["extend"] else 3
    for n in range(4,rounds+1):
        round_(n)
    save(root / "primary-complete.json", {"rounds":rounds, "end_ns":time.monotonic_ns()})
    # Stock's pristine executable has no clock in the CDCL restart loop.
    # Separate serial observer after primary timings so it does not interleave with any arm.
    for n in range(1,rounds+1):
        for case,spec in specs.items():
            for side in ("P0","P1"):
                sample(case,n,"stock-clock",side,lambda p: run_one(observer,spec,case,side,p,[],observer_hash))
    save(root / "timing-complete.json", {"rounds":rounds, "end_ns":time.monotonic_ns()})
    lease.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary","tools","observer","root"):
        parser.add_argument(name,type=Path)
    args = parser.parse_args()
    execute(*(p.resolve() for p in (args.binary,args.tools,args.observer,args.root)))
