"""Record, certify and bind original ordering conflicts across one program update."""
import json
from time import perf_counter_ns

from incdeagle.model.identity import digest, read, save
from .certificate import check, derive
from .context import BACKEND, SCHEMA, freeze

SITE = "ClosureSolver::propagate/pre-analyze"
ORIGINS = {"self_cycle", "atomic_order_cycle"}


def snapshot(directory, manifest):
    start = perf_counter_ns()
    context, registry = freeze(directory, read(directory.parent / "theory-settings.json"), manifest)
    fingerprint = digest(context)
    ns = perf_counter_ns() - start
    save(directory / "theory-context.json", context)
    return context, registry, fingerprint, ns


def collect(directory, manifest):
    snapshot_error = None
    start = perf_counter_ns()
    try:
        context, registry, fingerprint, fingerprint_ns = snapshot(directory, manifest)
    except (OSError, KeyError, ValueError, TypeError, IndexError) as error:
        snapshot_error = str(error)
        context = {"schema":SCHEMA,"backend":BACKEND,"unavailable":snapshot_error}
        save(directory / "theory-context.json", context)
        registry, fingerprint, fingerprint_ns = None, digest(context), perf_counter_ns() - start
    audit_start = perf_counter_ns()
    lemmas, observed, seen = [], [], set()
    raw = [json.loads(line) for line in (directory / "native-conflicts.jsonl").read_text().splitlines()]
    supported = duplicates = 0
    for index, row in enumerate(raw):
        outcome = {"raw_index": index}
        try:
            if snapshot_error:
                raise ValueError("old_context_unavailable:" + snapshot_error)
            if row["site"] != SITE or row["origin"] not in ORIGINS:
                raise ValueError("unaudited_conflict_origin")
            clause = registry.decode_clause(row["clause_x"])
            proof = derive(context, clause)
            if not check(context, clause, proof):
                raise ValueError("invalid_origin_certificate")
            supported += 1
            key = digest(clause)
            if key in seen:
                duplicates += 1
                outcome.update(status="deduplicated", clause_sha256=key)
            else:
                seen.add(key)
                lemmas.append({"kind":"oc-cycle", "export_site":SITE, "origin":row["origin"],
                               "origin_version":manifest["version_sha256"], "raw_index":index,
                               "clause":clause, "certificate":proof, "clause_sha256":key})
                outcome.update(status="supported", clause_sha256=key)
        except (KeyError, ValueError, TypeError, IndexError, RecursionError) as error:
            outcome.update(status="rejected", reason=str(error))
        observed.append(outcome)
    cache = {"schema":SCHEMA, "backend":context["backend"], "dependency_mode":"whole_theory_context",
             "origin_version":manifest["version_sha256"], "context_sha256":fingerprint,
             "lemmas":lemmas}
    save(directory / "lemma-cache.json", cache)
    result = {"exported":len(raw), "supported":supported, "deduplicated":duplicates,
              "unique":len(lemmas), "export_rejected":len(raw)-supported, "records":observed,
              "fingerprint_ns":fingerprint_ns, "old_audit_ns":perf_counter_ns()-audit_start,
              "cache_sha256":digest(cache), "context_sha256":fingerprint, "snapshot_error":snapshot_error}
    save(directory / "theory-export.json", result)
    return result


def validate(old_context, context, cache, registry, expected_origin):
    """Verify the complete declaration and replay only the recorded short proof DAG."""
    reasons = []
    if cache["schema"] != SCHEMA or old_context["schema"] != SCHEMA or context["schema"] != SCHEMA:
        reasons.append("schema_mismatch")
    if any(h["backend"] != BACKEND for h in (cache, old_context, context)):
        reasons.append("backend_mismatch")
    if cache["origin_version"] != expected_origin or cache["dependency_mode"] != "whole_theory_context":
        reasons.append("origin_or_dependency_mode_mismatch")
    if cache["context_sha256"] != digest(old_context):
        reasons.append("origin_context_fingerprint_mismatch")
    if old_context != context:
        reasons.extend("context_changed:" + k for k in sorted(old_context.keys() | context.keys())
                       if old_context.get(k) != context.get(k))
    plan, records, seen = [], [], set()
    audit_ns = binding_ns = 0
    for lemma in cache["lemmas"]:
        start = perf_counter_ns()
        record = {"clause_sha256":lemma.get("clause_sha256"), "raw_index":lemma.get("raw_index")}
        try:
            if reasons:
                raise ValueError(reasons[0])
            clause = lemma["clause"]
            if (lemma["kind"] != "oc-cycle" or lemma["origin"] not in ORIGINS or lemma["export_site"] != SITE
                    or lemma["origin_version"] != expected_origin or digest(clause) != lemma["clause_sha256"]):
                raise ValueError("unaudited_or_modified_lemma")
            if lemma["clause_sha256"] in seen or not check(context, clause, lemma["certificate"]):
                raise ValueError("duplicate_or_invalid_certificate")
            checkpoint = perf_counter_ns()
            bindings = registry.bind(clause)
            binding_ns += perf_counter_ns() - checkpoint
            record.update(status="accepted", plan_index=len(plan))
            plan.append(bindings)
            seen.add(lemma["clause_sha256"])
        except (ValueError, KeyError, TypeError, IndexError) as error:
            record.update(status="rejected", reason=str(error))
        audit_ns += perf_counter_ns() - start
        records.append(record)
    return plan, {"accepted":len(plan), "validation_rejected":len(records)-len(plan), "records":records,
                  "context_differences":reasons, "binding_ns":binding_ns, "lemma_check_including_bind_ns":audit_ns}


def bind(directory):
    root = directory.parent
    old = root / "old"
    export = {}
    start = perf_counter_ns()
    try:
        export = read(old / "theory-export.json")
        cache = read(old / "lemma-cache.json")
        if digest(cache) != export["cache_sha256"]:
            raise ValueError("cache_integrity_mismatch")
        old_context = read(old / "theory-context.json")
        manifest = read(root / "frontend/manifest.json")
        context, registry, fingerprint, fingerprint_ns = snapshot(directory, manifest)
        plan, result = validate(old_context, context, cache, registry, read(old/"manifest.json")["version_sha256"])
        result.update(context_sha256=fingerprint, fingerprint_ns=fingerprint_ns)
    except (OSError, KeyError, ValueError, TypeError, IndexError) as error:
        plan = []
        result = {"accepted":0, "validation_rejected":export.get("unique"), "records":[],
                  "context_differences":[str(error)], "fingerprint_ns":None, "binding_ns":None}
    lines = ["stage5-local-bindings-v1"]
    for i, slots in enumerate(plan):
        lines.append(" ".join(map(str,[i,len(slots),*(number for pair in slots for number in pair)])))
    (directory/"local-bindings.txt").write_text("\n".join(lines)+"\n")
    result["candidate_audit_total_ns"] = perf_counter_ns() - start
    save(directory / "theory-validation.json", result)
    return result
