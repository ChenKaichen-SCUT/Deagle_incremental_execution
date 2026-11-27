"""Audit individual RF and Guard ports against the frozen airline event correspondence."""
import csv
from collections import Counter, defaultdict

from d1_identity import Keys, Model, load_rows
from d1_theory import Terms
from d41_identity import pair_sites
from d42_events import supplement, unchanged
from run_stock import BASE


def guard_terms(model):
    evaluator = Terms(model)
    definitions = defaultdict(set)
    for name, term in model.rows["H"]:
        definitions[name].add(term)
    return {name: evaluator.expression(next(iter(ids)))[0] if len(ids) == 1 else 0
            for name, ids in definitions.items()}


def evidence(functional, events, output):
    case = "airline_reservations_6"
    base = functional / case / "1"
    live = base / "Combined/P1/native"
    paths = (base / "record/P0/native/model.tsv", live / "boundary.tsv")
    keys = Keys()
    raw = [load_rows(p) for p in paths]
    sites = pair_sites(*raw, keys)
    src = BASE / "bench" / case
    lines = unchanged((src/"old/program.c").read_bytes(), (src/"candidate/program.c").read_bytes(),
                      (src/"patch.diff").read_bytes())
    supplement(raw, sites, keys, "program.c", lines)
    old, new = (Model(p, keys, True, recorded_queries=not side, live_boundary=bool(side),
                      records=raw[side], site_pairs=sites[side]) for side,p in enumerate(paths))
    with events.open() as f:
        event = {r["old_event"]: r for r in csv.DictReader(f, delimiter="\t")}
    def endpoint(name):
        return event.get(name, {"peer": "", "state": "no_recorded_source_event"})
    facts = {}
    with (live/"delta/declarations.txt").open() as f:
        for line in f:
            if line.startswith("D "):
                _, op, a, b, c, state = line.split()
                facts[int(op), int(a), int(b), int(c)] = state
    rf = defaultdict(list)
    for tag, a, b, pin, *_ in new.rows["EDGE"]:
        if tag.lower() == "rf":
            rf[a,b].append(pin)
    guards = defaultdict(list)
    for name, pin in new.rows["GUARD"]:
        guards[name].append(pin)
    terms0, terms1 = guard_terms(old), guard_terms(new)
    counts = {"RF": Counter(), "Guard": Counter()}
    with output.open("w") as f:
        wr = csv.writer(f, delimiter="\t", lineterminator="\n")
        wr.writerow(("kind", "old_from", "old_to", "old_literal", "peer_from", "peer_to", "new_literals",
                     "from_event_state", "to_event_state", "binding_status", "diagnosis"))
        for tag, a, b, pin, *_ in old.rows["EDGE"]:
            if tag.lower() != "rf":
                continue
            source, target = endpoint(a), endpoint(b)
            x, y = source["peer"], target["peer"]
            options = rf[x,y]
            state = facts[3,int(old.names[a]),int(old.names[b]),int(pin)]
            reason = ("endpoint_unmatched" if not (x and y) else "new_pair_absent" if not options
                      else "binding_certified" if state == "M" else "pair_exists_binding_unresolved")
            assert state != "M" or (x and y and options)
            counts["RF"][reason] += 1
            wr.writerow(("RF",a,b,pin,x,y,",".join(options),source["state"],target["state"],state,reason))
        for name, pin in old.rows["GUARD"]:
            origin = endpoint(name)
            target = origin["peer"]
            options = guards[target]
            state = facts[4,int(old.names[name]),-1,int(pin)]
            same = bool(terms0.get(name)) and terms0[name] == terms1.get(target)
            if not target:
                reason = "event_unmatched"
            elif not options:
                reason = "new_guard_absent"
            elif state == "M":
                assert same
                reason = "certified_same_literal" if pin in options else "certified_reencoded_literal"
            elif same:
                reason = "same_definition_binding_unresolved"
            elif terms0.get(name) and terms1.get(target):
                reason = "guard_definition_changed"
            else:
                reason = "guard_definition_unresolved"
            assert state != "M" or (target and options)
            counts["Guard"][reason] += 1
            wr.writerow(("Guard",name,"",pin,target,"",",".join(options),origin["state"],"",state,reason))
    return counts
