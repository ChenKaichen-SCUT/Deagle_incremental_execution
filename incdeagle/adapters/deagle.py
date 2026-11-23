"""Read the complete structured UI document produced by the pinned Deagle binary."""
import json


def source_location(location):
    return {k: location[k] for k in ("file", "line", "column", "function") if k in location}


def classify(document, exit_code, prop):
    """Keep the target separate from unwind and library assertions."""
    messages = json.loads(document)
    if not isinstance(messages, list) or not messages or not all(isinstance(m, dict) for m in messages):
        raise ValueError("Expected a Deagle JSON array")
    groups = [m["result"] for m in messages if "result" in m]
    totals = [m["cProverStatus"] for m in messages if "cProverStatus" in m]
    if len(groups) != 1 or not isinstance(groups[0], list) or len(totals) != 1 or messages[-1].get("cProverStatus") != totals[0]:
        raise ValueError("Incomplete or ambiguous property results")
    rows = {}
    for row in groups[0]:
        key = row["property"]
        if key in rows:
            raise ValueError(f"Duplicate property {key}")
        rows[key] = row
    if prop["id"] not in rows:
        raise ValueError("Target assertion is absent")
    target = rows[prop["id"]]
    where = source_location(target.get("sourceLocation", {}))
    expected = prop["source"]
    if any(str(where.get(k)) != str(expected[k]) for k in ("file", "line", "function")):
        raise ValueError("Target property resolved to the wrong location")
    status = {k: v["status"] for k, v in rows.items()}
    unwind = {k: s for k, s in status.items() if "unwind" in k.split(".")[1:]}
    total = totals[0]
    if (total, exit_code) not in (("success", 0), ("failure", 10), ("inconclusive", 5)):
        raise ValueError(f"Overall result disagrees with process exit: {total}/{exit_code}")
    any_failed = "FAILURE" in status.values()
    if (total == "failure") != any_failed or (total == "success" and set(status.values()) != {"SUCCESS"}):
        raise ValueError("Overall result disagrees with property rows")
    if target["status"] == "FAILURE":
        verdict = "VIOLATION"
    elif "FAILURE" in unwind.values():
        verdict = "INCOMPLETE_UNWINDING"
    elif total == "success" and target["status"] == "SUCCESS":
        verdict = "NO_VIOLATION_WITHIN_BOUND"
    else:
        verdict = "UNKNOWN"
    return {"classification": verdict, "native_overall": total, "target": prop["id"],
            "properties": status, "unwinding_properties": unwind, "target_source": where}, target
