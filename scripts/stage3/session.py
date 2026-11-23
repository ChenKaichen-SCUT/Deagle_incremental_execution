#!/usr/bin/env python3
"""Single-case NDJSON protocol for two separately built native full models."""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.stage2.check_case import load_case
from incdeagle.adapters.deagle import classify
from incdeagle.model.identity import file_sha, read, save
from incdeagle.model.observe import build_model
from incdeagle.model.compare import delta, manifest

OPS = ("LOAD_OLD", "BUILD_OLD", "VERIFY_OLD", "WAIT_FOR_CANDIDATE",
       "UPDATE_CANDIDATE", "VERIFY_CANDIDATE", "EXPORT_RESULT", "SHUTDOWN")
CASES = {p.parent.name: p.parent for base in (ROOT / "cases", ROOT / "tests/stage3")
         for p in base.glob("*/task.yaml")}
BINARY = ROOT / "third_party/deagle-work/src/cbmc/deagle_exe"


def memory_max():
    groups = Path("/proc/self/cgroup").read_text().splitlines()
    relative = next(row[3:] for row in groups if row.startswith("0::"))
    return (Path("/sys/fs/cgroup") / relative.lstrip("/") / "memory.max").read_text().strip()


class Worker:
    def __init__(self, role, case, gamma, task, out, shim, stack):
        self.role = role
        self.directory = d = out / role
        d.mkdir()
        shutil.copyfile(case / task["old_source" if role == "old" else "candidate_source"], d / "program.c")
        shutil.copyfile(case / "harness.c", d / "harness.c")
        self.limit = gamma["limits"]["timeout_seconds"]
        self.started = time.monotonic()
        self.cmd = [str(BINARY), *gamma["source_argv"], *gamma["verification_output"], "harness.c"]
        env = dict(os.environ, PATH=str(shim) + os.pathsep + os.environ["PATH"], LC_ALL="C",
                   INCDEAGLE_OBSERVE_DIR=str(d), INCDEAGLE_STAGE3_SESSION="1",
                   INCDEAGLE_JSON_OUTPUT=str(d / "result.json"), INCDEAGLE_CPP_RECORD=str(d / "cpp.jsonl"))
        self.process = subprocess.Popen(self.cmd, cwd=d, stdin=subprocess.PIPE,
                                       stdout=stack.enter_context((d / "diagnostic.stdout").open("wb")),
                                       stderr=stack.enter_context((d / "diagnostic.stderr").open("wb")),
                                       env=env, start_new_session=True)
        stack.callback(self.close)
        self.marker("built", self.started, self.limit)
        self.build_wall = time.monotonic() - self.started

    def marker(self, name, start, remaining):
        while time.monotonic() - start < remaining:
            if self.process.poll() is not None:
                raise RuntimeError(f"{self.role} exited {self.process.returncode} before {name}")
            f = self.directory / (name + ".json")
            if f.is_file() and read(f).get("state") == name:
                return
            time.sleep(0.005)
        raise TimeoutError(f"{self.role} exhausted its {self.limit}s active build/verify budget at {name}")

    def send(self, command):
        self.process.stdin.write((command + "\n").encode())
        self.process.stdin.flush()

    def verify(self, phi):
        start = time.monotonic()
        self.send("VERIFY")
        self.marker("verified", start, self.limit - self.build_wall)
        self.verify_wall = time.monotonic() - start
        self.metrics = read(self.directory / "metrics.json")
        self.result, row = classify((self.directory / "result.json").read_bytes(), self.metrics["exit_code"], phi)
        self.result["trace_steps"] = len(row.get("trace", []))
        return self.result

    def release(self):
        self.send("RELEASE")
        rc = self.process.wait(timeout=10)
        if rc != self.metrics["exit_code"]:
            raise RuntimeError(f"{self.role} exit {rc} disagrees with native result")
        return rc

    def status(self):
        return {"pid": self.process.pid, "alive": self.process.poll() is None}

    def close(self):
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait()
        self.process.stdin.close()


def serve(case, out):
    task, gamma, phi = load_case(case)
    memory = int(memory_max())
    if memory != gamma["limits"]["memory_bytes"]:
        raise RuntimeError(f"Unexpected session cgroup limit {memory}")
    lock = read(ROOT / "configs/stage03.lock.json")
    if file_sha(BINARY) != lock["development_sha256"]:
        raise RuntimeError("Unexpected development executable")
    out.mkdir(parents=True, exist_ok=False)
    shim = out / "tools"
    shim.mkdir()
    shutil.copyfile(ROOT / "scripts/stage3/record_gcc.py", shim / "gcc")
    (shim / "gcc").chmod(0o755)
    gcc_bin = Path("/usr/bin/gcc").resolve()
    gcc = {"binary": str(gcc_bin), "sha256": file_sha(gcc_bin),
           "version": subprocess.check_output([gcc_bin, "-dumpfullversion"], text=True).strip()}
    workers, versions, models = {}, {}, {}
    with ExitStack() as stack:
        for op in OPS:
            line = sys.stdin.readline()
            if not line:
                raise EOFError("Session input ended before " + op)
            if json.loads(line) != {"op": op}:
                raise ValueError("Expected command " + op)
            response = {"op": op}
            if op == "LOAD_OLD":
                response.update(case=case.name, mode="full", checkpoint_used=False, memory_max_bytes=memory)
            elif op in ("BUILD_OLD", "UPDATE_CANDIDATE"):
                role = "old" if op == "BUILD_OLD" else "candidate"
                workers[role] = Worker(role, case, gamma, task, out, shim, stack)
                response["built"] = role
            elif op in ("VERIFY_OLD", "VERIFY_CANDIDATE"):
                role = "old" if op == "VERIFY_OLD" else "candidate"
                response["result"] = workers[role].verify(phi)
            elif op == "WAIT_FOR_CANDIDATE":
                if not workers["old"].status()["alive"]:
                    raise RuntimeError("Old model holder exited while parked")
            elif op == "EXPORT_RESULT":
                for role, worker in workers.items():
                    d = worker.directory
                    versions[role] = manifest(d, case, gamma, phi, lock, gcc)
                    models[role] = build_model(d, phi["id"])
                    save(d / "manifest.json", versions[role])
                    save(d / "model.json", models[role])
                    summary = {"result": worker.result, "command": worker.cmd, "pid": worker.process.pid,
                               "metrics": worker.metrics, "build_wall_seconds": worker.build_wall,
                               "verify_wall_seconds": worker.verify_wall, "model": models[role]["structure_sha256"],
                               "counts": models[role]["counts"], "version": versions[role]["version_sha256"]}
                    save(d / "summary.json", summary)
                diff = delta(models["old"], models["candidate"], versions["old"], versions["candidate"])
                save(out / "delta.json", diff)
                response["delta"] = "delta.json"
            elif op == "SHUTDOWN":
                response["exit_codes"] = {k: w.release() for k, w in workers.items()}
            response["workers"] = {k: v.status() for k, v in workers.items()}
            if op != "SHUTDOWN" and not all(w["alive"] for w in response["workers"].values()):
                raise RuntimeError("Native model holder exited prematurely")
            print(json.dumps(response), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=sorted(CASES))
    parser.add_argument("--out", type=Path, required=True, help="a new session directory")
    parser.add_argument("--contained", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    case = CASES[args.case]
    if not args.contained:
        _, gamma, _ = load_case(case)
        argv = ["systemd-run", "--quiet", "--pipe", "--wait", "--collect",
                "-p", "WorkingDirectory=" + str(ROOT), "-p", "MemoryMax=" + str(gamma["limits"]["memory_bytes"]),
                "--", sys.executable, "-B", str(Path(__file__).resolve()), args.case,
                "--out", str(args.out.resolve()), "--contained"]
        return subprocess.run(argv).returncode
    try:
        serve(case, args.out.resolve())
    except (EOFError, ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}), flush=True)
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
