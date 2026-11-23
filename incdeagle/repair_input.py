"""Select the public, task-specific view of a native counterexample for a repairer."""
import hashlib
import json
import re

from incdeagle.model.identity import read


SENSITIVE = re.compile(
    r"(?i)(?:\bsk-[a-z0-9_-]{12,}|\b(?:gh[pousr]_[a-z0-9]{16,}|github_pat_[a-z0-9_]{20,}|AKIA[A-Z0-9]{16})"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|\bBearer\s+[A-Za-z0-9._-]{12,}"
    r"|\b(?:password|api[_ -]?key|access[_ -]?token)\s*[:=]\s*['\"]?[^\s'\"]{6,}"
    r"|(?:/root/|/home/|/etc/shadow|[a-z]:[\\/]+users[\\/]|apikey\.txt))"
)


def public_text(value, limit=16384, credential=None):
    if (len(value.encode("utf-8")) > limit or "\0" in value or SENSITIVE.search(value)
            or (credential and credential in value)):
        raise ValueError("Repair data failed the outbound content check")
    return value


def wire_text(packet):
    return json.dumps(packet, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def packet_sha(packet):
    return hashlib.sha256(wire_text(packet).encode()).hexdigest()


def make_packet(case, trace):
    source = (case/"old/program.c").read_text(encoding="utf-8")
    phi = read(case/"phi.json")
    gamma = read(case/"gamma.json")["semantics"]
    # Show the call arguments and thread boundaries; keep the rest of the harness local.
    names = re.findall(r"(?m)^\s*(?:static\s+)?(?:void|int|long|unsigned)\s+\*?\s*(\w+)\s*\(", source)
    relevant = re.compile(r"\b(?:"+"|".join(map(re.escape,[*names,"pthread_create","pthread_join"]))+r")\s*\(")
    harness = [{"line":i,"code":line.strip()} for i,line in
               enumerate((case/"harness.c").read_text(encoding="utf-8").splitlines(),1) if relevant.search(line)]
    writes = [{"index":s["index"],"thread":s["thread"],"line":s["source"].get("line"),
               "lhs":s["lhs"],"value":s["value"]["data"]} for s in trace["steps"]
              if s["type"]=="assignment" and s["source"].get("file")=="program.c" and s.get("lhs")
              and isinstance(s.get("value"),dict) and "data" in s["value"]]
    failure = trace["failure"]
    if (failure.get("property")!=phi["id"] or
            any(str(failure["source"].get(k))!=str(v) for k,v in phi["source"].items())):
        raise ValueError("Counterexample does not refer to the protected target")
    packet = {
        "program.c":source, "harness_calls":harness,
        "property":{k:phi[k] for k in ("id","description","assertion","source")},
        "bounds":{k:gamma[k] for k in ("memory_model","target_bits","unwind","check_unwinding","worker_threads","assumptions")},
        "counterexample":{"step_count":trace["step_count"],"failure":{k:failure[k] for k in ("index","thread","reason")},
                          "last_program_assignments":writes[-12:]}
    }
    public_text(wire_text(packet))
    return packet
