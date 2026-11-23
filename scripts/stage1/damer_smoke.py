"""Exercise the upstream native old/new pair using independent writable copies."""
import re
import shutil
import tempfile
from pathlib import Path

from run_evidence import ROOT, RUN, capture, sha256, write_json

SOURCE = ROOT / "third_party/damer-camc"
BINARY = SOURCE / "build/PDNet2_0"
NAME = "08_Lazy"


def main():
    root = RUN / "damer-smoke"
    root.mkdir(parents=True, exist_ok=True)
    report = {"binary_sha256": sha256(BINARY), "input_sha256": {}, "runs": {}}
    report["runs"]["help"] = capture(root, "help", [BINARY, "-help"])
    for mode in ("old", "new", "cia"):
        # The tool creates .iii, CSV and formula.xml files relative to its working directory.
        scratch = Path(tempfile.mkdtemp(prefix=mode + "-", dir=root))
        for sub in ("test", "build"):
            (scratch / sub).mkdir()
        shutil.copytree(SOURCE / "properties", scratch / "properties")
        (scratch / "include").symlink_to(SOURCE / "include", target_is_directory=True)
        for filename in (NAME + ".c", NAME + "-new.c", NAME + ".xml"):
            shutil.copyfile(SOURCE / "test" / filename, scratch / "test" / filename)
            report["input_sha256"][filename] = sha256(scratch / "test" / filename)
        program = NAME + ("-new.c" if mode == "new" else ".c")
        flags = ["-CIA", "-PDNetSlice"] if mode == "cia" else []
        argv = [BINARY, *flags, "-property", "../test/" + NAME + ".xml", "../test/" + program]
        result = capture(root, mode, argv, cwd=scratch / "build")
        report["runs"][mode] = result
        output = (root / result["stdout"]).read_text()
        verdicts = re.findall(r"^checked result:(TRUE|FALSE)$", output, re.M)
        if verdicts != ["FALSE"]:
            raise ValueError(f"Missing expected native verdict for {mode}: {verdicts}")
        result["verdict"] = verdicts[0]
        result["model_counts"] = {key: int(value) for key, value in
                                  re.findall(r"^\s*(placenum|transnum|Synthesised graph node num):\s*(\d+)", output, re.M)}
        if mode == "cia":
            result["previous_verdict_reused"] = "Reuse checking failed" not in output
            if result["previous_verdict_reused"] or "time to modify the previous model" not in output:
                raise ValueError("Expected change construction and slice recheck for this fixed pair")
        result["csv"] = {f.name: f.read_text(errors="replace") for f in (scratch / "build").glob("*.csv")}
        result["rendered_property_sha256"] = sha256(scratch / "properties/formula.xml")
    write_json(root / "runs.json", report)
    if any(r["exit_code"] for k, r in report["runs"].items() if k != "help"):
        raise SystemExit("A native DAMER invocation failed")


if __name__ == "__main__":
    main()
