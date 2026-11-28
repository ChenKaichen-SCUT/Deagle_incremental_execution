"""Run the predeclared D0 matrix once, serially, with a fresh stock process per entry."""
import argparse
import hashlib
import json
import os
import resource
import select
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from lock_build import UPSTREAM

BASE = Path(__file__).resolve().parents[1]
ORDER = ("smoke/worker_violation", "smoke/join_pass", "fib_updates_8",
         "circular-buffer", "airline_reservations_6")
CPU = 0
ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C", "TZ": "UTC"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run(binary, spec, name, side, directory, build_hash):
    case = BASE / "bench" / name
    work = directory / "work"
    work.mkdir(parents=True)
    inputs = {}
    for dest, src in spec["inputs"][side].items():
        path = work / dest
        shutil.copyfile(case / src, path)
        inputs[dest] = sha(path)
        if inputs[dest] != spec["files_sha256"][src]:
            raise ValueError(f"staged source mismatch: {path}")
    argv = [str(binary), *spec["argv"]]
    limits = spec["limits"]

    def limit():
        os.sched_setaffinity(0, {CPU})
        resource.setrlimit(resource.RLIMIT_AS, (limits["memory_bytes"],) * 2)
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    meta = dict(case=name, side=side, argv=argv, cwd=str(work), binary_sha256=build_hash,
                input_sha256=inputs, limits=limits, cpu_affinity=[CPU], env=ENV, target=spec["target"])
    with (directory / "stdout").open("wb") as out, (directory / "stderr").open("wb") as err:
        meta["started_utc"] = datetime.now(timezone.utc).isoformat()
        start = time.monotonic_ns()
        with subprocess.Popen(argv, cwd=work, env=ENV, stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                              start_new_session=True, preexec_fn=limit) as proc:
            fd = os.pidfd_open(proc.pid)
            try:
                remaining = max(0, limits["timeout_seconds"] - (time.monotonic_ns() - start) / 1e9)
                timed_out = not select.select([fd], [], [], remaining)[0]
                if timed_out:
                    os.killpg(proc.pid, signal.SIGKILL)
                _, status, usage = os.wait4(proc.pid, 0)
                elapsed = time.monotonic_ns() - start
                proc.returncode = os.waitstatus_to_exitcode(status)
            finally:
                os.close(fd)
    meta.update(monotonic_start_ns=start, exit_code=proc.returncode, timed_out=timed_out, wall_ns=elapsed, user_s=usage.ru_utime,
                system_s=usage.ru_stime, peak_rss_kib=usage.ru_maxrss, stdout_sha256=sha(directory / "stdout"),
                stderr_sha256=sha(directory / "stderr"))
    save(directory / "run.json", meta)
    print(f"{name}/{side}  rc={proc.returncode}  {elapsed/1e9:.3f}s  {usage.ru_maxrss} KiB", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_receipt", type=Path)
    parser.add_argument("new_run_directory", type=Path)
    args = parser.parse_args()
    receipt = json.loads(args.build_receipt.read_bytes())
    binary = Path(receipt["binary_path"])
    if receipt["source_commit"] != UPSTREAM or sha(binary) != receipt["binary_sha256"]:
        raise ValueError("stock binary does not match the supplied build receipt")
    if CPU not in os.sched_getaffinity(0):
        raise RuntimeError(f"predeclared logical CPU {CPU} unavailable")
    manifest = BASE / "bench/manifest.json"
    cases = json.loads(manifest.read_bytes())
    if set(cases) != set(ORDER):
        raise ValueError("unexpected D0 cohort")
    schedule = []
    for name in ORDER:
        spec = cases[name]
        for src, digest in spec["files_sha256"].items():
            if sha(BASE / "bench" / name / src) != digest:
                raise ValueError(f"frozen input changed: {name}/{src}")
        for side in spec["inputs"]:
            schedule.append(dict(case=name, side=side, limits=spec["limits"], argv=spec["argv"]))
    directory = args.new_run_directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    save(directory / "plan.json", dict(mode="stock", repeat_count=1, serial=True, cpu_affinity=[CPU],
         binary_sha256=receipt["binary_sha256"], source_commit=UPSTREAM, input_lock_sha256=sha(manifest),
         env=ENV, limits_enforcement="RLIMIT_AS per process; monotonic deadline for the process group",
         cold="fresh process/model/solver, no knowledge input, OS file caches left under OS control",
         defaults=dict(rnd_seed=91648253, rnd_freq=0, rnd_init=False, ccmin_mode=2,
                       luby=True, rfirst=100, rinc=2), order=schedule))
    for row in schedule:
        name, side = row["case"], row["side"]
        run(binary, cases[name], name, side, directory / name / side, receipt["binary_sha256"])


if __name__ == "__main__":
    main()
