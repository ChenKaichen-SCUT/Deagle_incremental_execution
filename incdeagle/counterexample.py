"""Preserve the observation order of a public Deagle trace without inferring event edges."""
from incdeagle.adapters.deagle import source_location


def normalize(row, phi, gamma, hashes, trace_path):
    trace = row.get("trace")
    if not isinstance(trace, list) or not trace:
        raise ValueError("Missing counterexample for failed target")
    steps = []
    for i, raw in enumerate(trace):
        s = {"index": i, "type": raw["stepType"], "thread": raw.get("thread"),
             "source": source_location(raw.get("sourceLocation", {}))}
        for key in ("hidden", "lhs", "value", "assignmentType", "property", "reason", "function"):
            if key in raw:
                value = raw[key]
                if key == "function" and isinstance(value, dict):
                    value = {k: v for k, v in value.items() if k != "sourceLocation"}
                s[key] = value
        steps.append(s)
    failures = [s for s in steps if s["type"] == "failure" and s.get("property") == phi["id"]]
    if len(failures) != 1 or any(str(failures[0]["source"].get(k)) != str(v) for k, v in phi["source"].items()):
        raise ValueError("Missing unique failure at the protected assertion")
    missing = {field: sum(s[field] is None if field == "thread" else not s[field] for s in steps)
               for field in ("thread", "source")}
    assignments = [s["index"] for s in steps if s["type"] == "assignment" and s.get("lhs") and "value" in s]
    return {"schema_version": 1, "property": phi["id"], "failure": failures[0], "p0_sha256": hashes["program.c"],
            "input_sha256": hashes, "gamma": gamma, "raw_trace": trace_path, "raw_witness": None,
            "thread_ids": sorted({s["thread"] for s in steps if s["thread"] is not None}),
            "step_count": len(steps), "steps": steps, "assignment_indices": assignments,
            "coverage": {"steps_in_public_trace": len(trace), "copied_steps": len(steps), "missing_fields_by_step": missing,
                         "not_exported": ["complete event graph", "reads-from relation", "complete program-order relation", "SC order over all memory events"],
                         "order": "Indices follow the UI trace. Hidden and library steps are retained; raw JSON is authoritative.",
                         "witness": "No separate GraphML requested for this case."}}
