"""Repeat the frozen six-agent P0 search with the two unmodified release binaries."""
import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from incdeagle.adapters.deagle import classify
from incdeagle.comparison import bounded
from incdeagle.model.identity import file_sha, read, save
from scripts.stage2.check_case import load_case
from scripts.stage7.results import runtime_messages


def run(source_run, tools, out):
    item = read(ROOT/"reports/evidence/stage-07/matrix.json")["airline_reservations_6"]
    case = source_run/item["case_dir"]
    _, gamma, phi = load_case(case)
    assert all(file_sha(case/k) == v for k, v in item["files"].items())
    lock = read(ROOT/"configs/stage05.lock.json")
    modes = ["baseline", "development", "development-observed"]
    out.mkdir(parents=True, exist_ok=True)
    for repeat in range(5):
        for mode in modes[repeat % 3:] + modes[:repeat % 3]:
            d = out/str(repeat+1)/mode
            if (d/"receipt.json").exists():
                continue
            d.mkdir(parents=True)
            for k in ("old/program.c", "harness.c"):
                shutil.copyfile(case/k, d/Path(k).name)
            orig = mode == "baseline"
            binary = tools/("deagle-baseline" if orig else "deagle-stage5")/"src/cbmc/deagle_exe"
            assert file_sha(binary) == lock[("baseline" if orig else "development")+"_sha256"]
            env = {"INCDEAGLE_JSON_OUTPUT": d/"result.json"}
            if mode.endswith("-observed"):
                env["INCDEAGLE_OBSERVE_DIR"] = d
            argv = [binary, *gamma["source_argv"], *gamma["verification_output"], "harness.c"]
            result = bounded(argv, d, d, gamma["limits"], env=env)
            verdict, target = classify((d/"result.json").read_bytes(), result["exit_code"], phi)
            assert verdict["classification"] == "VIOLATION"
            save(d/"receipt.json", {"binary_sha256":file_sha(binary), "mode":mode, "repeat":repeat+1,
                "source_sha256":file_sha(d/"program.c"), "harness_sha256":file_sha(d/"harness.c"),
                "argv":list(map(str,argv)), "limits":gamma["limits"], "verdict":verdict, "trace_steps":len(target["trace"]),
                "timings":runtime_messages(d/"result.json"), "service":result, "affinity":sorted(os.sched_getaffinity(0))})
            print(repeat+1, mode, runtime_messages(d/"result.json").get("Solver"), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("source_run","tools","out"):
        parser.add_argument(arg, type=Path)
    a=parser.parse_args()
    run(a.source_run.resolve(), a.tools.resolve(), a.out.resolve())
