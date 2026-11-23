"""Exercise both Deagle binaries and require complete property-level evidence."""
import json
import tempfile
from pathlib import Path
from xml.etree import ElementTree

from run_evidence import ROOT, RUN, capture, sha256, write_json

PROPERTIES = {
    "worker_violation": ("worker.assertion.1", "FAILURE", 10, "failure"),
    "join_pass": ("main.assertion.1", "SUCCESS", 0, "success"),
}


def check_result(payload, name):
    # Parse the entire dedicated stream. Diagnostic prefixes or trailing text are errors.
    messages = json.loads(payload)
    prop_id, verdict, _, summary = PROPERTIES[name]
    groups = [m["result"] for m in messages if "result" in m]
    totals = [m["cProverStatus"] for m in messages if "cProverStatus" in m]
    if len(groups) != 1 or totals != [summary] or messages[-1].get("cProverStatus") != summary:
        raise ValueError("Incomplete or inconsistent result document")
    rows = groups[0]
    if [(r["property"], r["status"]) for r in rows] != [(prop_id, verdict)]:
        raise ValueError("Unexpected properties or status for the fixed smoke fixture")
    row = rows[0]
    steps = row.get("trace", [])
    location = row["sourceLocation"]
    if location["file"] != f"tests/stage1/{name}.c":
        raise ValueError("Property location does not match the input")
    record = {"property": prop_id, "status": verdict, "source": location, "trace_steps": len(steps),
              "thread_ids": sorted({s["thread"] for s in steps if "thread" in s}),
              "explicit_unwind_properties": [r["property"] for r in rows if ".unwind" in r["property"]],
              "classification": "VIOLATION" if verdict == "FAILURE" else "NO_VIOLATION_WITHIN_BOUND"}
    if verdict == "FAILURE":
        failures = [s for s in steps if s.get("stepType") == "failure" and s.get("property") == prop_id]
        writes = [s for s in steps if s.get("lhs") == "flag" and s.get("value", {}).get("data") == "1"]
        if len(failures) != 1 or not any(s["thread"] == failures[0]["thread"] == 1 for s in writes):
            raise ValueError("Missing worker assignment or target failure in the counterexample")
        record.update(failure=failures[0], observed_write={"lhs": "flag", "value": 1, "thread": 1})
    return record


def main():
    directory = Path(tempfile.mkdtemp(prefix="deagle-smoke-", dir=RUN))
    flags = ["--deagle-closure", "--mm", "sc", "--64", "--unwind", "4", "--unwinding-assertions", "--trace"]
    report = {"inputs": {}, "trees": {}}
    for tree in ("deagle-baseline", "deagle-work"):
        binary = ROOT / "third_party" / tree / "src/cbmc/deagle_exe"
        rows = {}
        report["trees"][tree] = {"binary_sha256": sha256(binary), "runs": rows}
        for name, (prop, status, rc, _) in PROPERTIES.items():
            src = f"tests/stage1/{name}.c"
            report["inputs"][src] = sha256(ROOT / src)
            for mode in ("plain", "json"):
                label = f"{tree}-{name}-{mode}"
                use_json = mode == "json"
                dest = directory / (label + ".json")
                argv = [binary, *flags, *(["--json-ui"] if use_json else []), src]
                r = capture(directory, label, argv, environment={"INCDEAGLE_JSON_OUTPUT": str(dest)} if use_json else {})
                rows[label] = r
                if r["exit_code"] != rc:
                    raise ValueError(f"{label} returned {r['exit_code']}")
                text = (directory / r["stdout"]).read_text()
                if "Use Deagle's closure solver" not in text or "Set Deagle closure solver's graph" not in text:
                    raise ValueError("Closure backend evidence missing")
                if use_json:
                    r["document"] = dest.name
                    r["document_sha256"] = sha256(dest)
                    r["checked"] = check_result(dest.read_text(), name)
                elif not any(f"[{prop}]" in line and line.endswith(status) for line in text.splitlines()):
                    raise ValueError("Plain property line missing")
        label = f"{tree}-witness"
        witness = directory / (label + ".graphml")
        r = capture(directory, label, [binary, *flags, "--graphml-witness", witness, "tests/stage1/worker_violation.c"])
        rows[label] = r
        xml = ElementTree.parse(witness)
        ns = {"g": "http://graphml.graphdrawing.org/xmlns"}
        graph = xml.find("g:graph", ns)
        if graph is None:
            raise ValueError("Graph element missing")
        data = {d.get("key"): d.text for d in graph.findall("g:data", ns)}
        violations = [d for d in graph.findall("g:node/g:data", ns) if d.get("key") == "violation" and d.text == "true"]
        if r["exit_code"] != 10 or data.get("witness-type") != "violation_witness" or not violations:
            raise ValueError("Violation witness missing")
        r["graphml"] = {"file": witness.name, "sha256": sha256(witness), "specification": data.get("specification"),
                        "nodes": len(graph.findall("g:node", ns)), "edges": len(graph.findall("g:edge", ns)),
                        "violation_nodes": len(violations), "edge_thread_ids": sorted(
                            {d.text for d in graph.findall("g:edge/g:data", ns) if d.get("key") == "threadId"})}
    write_json(directory / "summary.json", report)
    print(directory)


if __name__ == "__main__":
    main()
