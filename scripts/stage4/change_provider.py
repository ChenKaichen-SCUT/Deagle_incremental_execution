"""Stage 4 sources and GOTO correspondence. Native code separately certifies the entire arena."""
from difflib import SequenceMatcher
from collections import Counter

from incdeagle.model.identity import GotoMap, read
from incdeagle.model.compare import compare_mapping


def mutex_calls(doc):
    counts=Counter()
    pool=doc["ireps"]
    for row in doc["instructions"]:
        if row["kind"]!="FUNCTION_CALL" or row["file"]!="program.c":
            continue
        operands=pool[row["code"]].get("sub",[])
        if len(operands)<2 or operands[1] is None:
            continue
        target=pool[operands[1]]
        if target["id"]=="symbol":
            identifier=pool[target["named"]["identifier"]]["id"]
            if identifier in {"pthread_mutex_lock","pthread_mutex_unlock","pthread_mutex_trylock"}:
                counts[row["function"],identifier]+=1
    return counts


def changes(old, front, manifests):
    a, b = (p.joinpath("program.c").read_text().splitlines() for p in (old, front))
    docs=[read(p/"goto.json") for p in (old,front)]
    maps = [GotoMap(p, doc) for p,doc in zip((old,front),docs)]
    edits, ambiguous = [], False
    for op, i, j, k, l in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        sites = []
        for mapping, begin, end in zip(maps, (i, k), (j, l)):
            found = sorted(key for key, info in mapping.sources.items() if any(
                loc["file"] == "program.c" and loc["line"].isdigit() and begin < int(loc["line"]) <= end
                for loc in info["locations"]))
            ambiguous |= any(not mapping.sources[key]["unique"] for key in found)
            sites.append(found)
        edits.append({"operation": op, "old_lines": [i+1,j], "new_lines": [k+1,l],
                      "old_sources": sites[0], "new_sources": sites[1]})
    context_keys = [key for key in manifests[0]["context"] if
                    manifests[0]["context"][key] != manifests[1]["context"][key]]
    old_calls,new_calls=map(mutex_calls,docs)
    lock_changes=[{"function":fn,"callee":target,"old":old_calls[fn,target],"new":new_calls[fn,target]}
                  for fn,target in sorted(old_calls.keys() | new_calls.keys()) if old_calls[fn,target]!=new_calls[fn,target]]
    result = {"edits": edits, "native_mutex_call_changes":lock_changes,"ambiguous_changed_source":ambiguous,
              "source_map": compare_mapping(maps[0].sources, maps[1].sources),
              "goto_map": compare_mapping(maps[0].rows, maps[1].rows), "configuration_changes": context_keys,
              "source_hashes": [m["source_sha256"] for m in manifests]}
    if context_keys:
        refusal = "config_headers_or_layout_changed"
    elif lock_changes:
        refusal = "synchronization_calls_changed:"+",".join(sorted({row["function"] for row in lock_changes}))
    elif ambiguous:
        refusal = "ambiguous_changed_source"
    elif not edits:
        refusal = "no_source_edit"
    else:
        refusal = ""
    result["preflight_refusal"] = refusal
    return result
