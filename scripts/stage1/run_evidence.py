"""Run one bounded, serial smoke check and retain both output streams."""
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "runs/stage-01"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def capture(directory, name, argv, *, cwd=ROOT, environment=None):
    directory.mkdir(parents=True, exist_ok=True)
    limits = yaml.safe_load((ROOT / "configs/project.yaml").read_text())["resources"]["verification"]
    command = ["systemd-run", "--quiet", "--pipe", "--wait", "--collect",
               "-p", f"WorkingDirectory={cwd}", "-p", f"MemoryMax={limits['memory_bytes']}",
               "--setenv=LC_ALL=C"]
    for key, value in (environment or {}).items():
        command.append(f"--setenv={key}={value}")
    command += ["--", "/usr/bin/timeout", "--kill-after=5", str(limits["timeout_seconds"]), *map(str, argv)]
    before = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()
    out, err = directory / (name + ".stdout"), directory / (name + ".stderr")
    with out.open("wb") as stdout, err.open("wb") as stderr:
        result = subprocess.run(command, stdout=stdout, stderr=stderr)
    return {"command": command, "started_utc": before, "wall_seconds": round(time.monotonic() - start, 4),
            "exit_code": result.returncode, "stdout": out.name, "stderr": err.name,
            "stdout_sha256": sha256(out), "stderr_sha256": sha256(err)}
