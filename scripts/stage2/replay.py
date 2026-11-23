"""Re-run frozen case pairs under the independent baseline in a new output directory."""
import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from check_case import ROOT, capture, check, sha256, write_json


def main():
    parent = ROOT / "runs/stage-02"
    parent.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix="replay-", dir=parent))
    start = time.monotonic()
    result = {"started_utc":datetime.now(timezone.utc).isoformat(), "directory":str(dest.relative_to(ROOT)), "cases":{}}
    resource = capture(dest, "limit", ["/usr/bin/python3","-c",
        "from pathlib import Path; p=Path('/proc/self/cgroup').read_text().strip().split('::')[-1]; "
        "print((Path('/sys/fs/cgroup') / p.lstrip('/') / 'memory.max').read_text().strip())"])
    result["measured_cgroup_memory_max_bytes"] = int((dest / resource["stdout"]).read_text())
    for manifest in sorted((ROOT / "cases").glob("*/freeze.json")):
        case = manifest.parent
        frozen = json.loads(manifest.read_bytes())
        pair = {}
        result["cases"][case.name] = pair
        for version in ("old","candidate"):
            out = dest / case.name / version
            original = json.loads((case / "evidence" / version / "run.json").read_bytes())
            run = check(case,version,out)
            if run["classification"] != frozen["results"][version] or run["properties"] != original["properties"]:
                raise ValueError("Changed property outcome on replay")
            if run["input_sha256"] != original["input_sha256"] or run["target_source"] != original["target_source"]:
                raise ValueError("Changed program, configuration or property on replay")
            if run["resource_limits"]["memory_bytes"] != result["measured_cgroup_memory_max_bytes"]:
                raise ValueError("Unexpected kernel memory limit")
            pair[version] = {"classification":run["classification"], "properties":run["properties"],
                             "verify_exit":run["runs"]["verify"]["exit_code"], "run_json_sha256":sha256(out / "run.json"),
                             "wall_seconds":{k:r["wall_seconds"] for k,r in run["runs"].items()}}
            if (out / "cex0.json").exists():
                cex = json.loads((out / "cex0.json").read_bytes())
                pair[version].update(trace_steps=cex["step_count"],thread_ids=cex["thread_ids"],failure_source=cex["failure"]["source"])
    if not result["cases"]:
        raise ValueError("No frozen cases")
    result["elapsed_seconds"] = round(time.monotonic()-start,4)
    write_json(dest / "replay.json",result)
    print(dest / "replay.json")


if __name__ == "__main__":
    main()
