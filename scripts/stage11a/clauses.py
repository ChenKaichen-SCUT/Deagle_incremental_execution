"""Distinguish an OC proof, whole-context admission, and a mixed CDCL consequence."""
import copy
import json
import sys
from dataclasses import replace
from itertools import product

from reference import Event, Graph, strict_models
from real import sha


def mixed_clause():
    events=(Event("begin","A","N",""),Event("end","A","N",""),Event("middle","B","N","","g"))
    between=(("begin","middle"),("middle","end"))
    block=Graph(events,between,(("begin","end"),))
    split=replace(block,po=between+(("begin","end"),),apo=())
    rows=[]
    for stage,g in (("P0",block),("P1",split)):
        models=strict_models(g)
        for p,guard in product((False,True),repeat=2):
            witnesses=[seq for env,_,seq in models if dict(env)["g"]==guard]
            rows.append({"version":stage,"p":p,"g":guard,"common_boolean_clause":not p or guard,
                         "theory_witness":min(witnesses,default=None),"learned_not_p":not p})
    possible=[r for r in rows if r["common_boolean_clause"] and r["theory_witness"]]
    assert all(r["learned_not_p"] for r in possible if r["version"]=="P0")
    assert any(not r["learned_not_p"] for r in possible if r["version"]=="P1")
    return {"P0":block.document(),"P1":split.document(),"common_cnf":[["!p","g"]],
            "P0_theory_unit":"!g","resolved_clause":"!p","truth_table":rows}


def stage5(root):
    sys.path.insert(0,str(root))
    from incdeagle.theory.certificate import check
    from incdeagle.theory.cache import validate
    d=root/"reports/evidence/stage-05/batch_total"
    paths=("old-context.json","lemma-cache.json","candidate-validation.json","candidate-import.json")
    context,cache,record,native=[json.loads((d/p).read_bytes()) for p in paths]
    lemma,=cache["lemmas"]
    clause,proof=lemma["clause"],lemma["certificate"]
    assert check(context,clause,proof)
    broken=copy.deepcopy(context)
    deleted=next(step["edge"] for step in proof if step["rule"]=="static")
    broken["edges"]=[e for e in broken["edges"] if not (e["kind"] in ("po","apo")
                      and [e["from"],e["to"]]==deleted)]
    assert not check(broken,clause,proof)
    metadata=copy.deepcopy(context)
    next(iter(metadata["guard_locations"].values()))["line"]+=1
    assert check(metadata,clause,proof)
    plan,audit=validate(context,metadata,cache,None,cache["origin_version"])
    assert not plan and audit["validation_rejected"]==1 and audit["context_differences"]
    return {"inputs":{p:sha((d/p).read_bytes()) for p in paths},"frozen_admitted":record["accepted"],
            "original_native_receipt":native,"proof":proof,"clause":clause,"original_replay":True,
            "removed_static_edge":deleted,"damaged_replay":False,"line_only_replay":True,
            "whole_context_admission_after_line_edit":audit["context_differences"]}
