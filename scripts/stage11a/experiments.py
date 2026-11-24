"""Systematic, bidirectional finite graph updates and targeted counterexamples."""
from collections import Counter
from dataclasses import astuple, replace
from itertools import product

from candidate import explain, run
from reference import Event, Graph, strict_models


def difference(old,new):
    def declarations(g):
        return ({("event",*astuple(e)) for e in g.events} |
                {(k,a,b) for k,rows in (("po",g.po),("apo",g.apo),("rf",g.rf)) for a,b in rows})
    a,b=declarations(old),declarations(new)
    return {"remove":sorted(a-b),"add":sorted(b-a)}


def signed_atoms(bindings):
    """Decode complete alias groups, constant values, polarity; reject ambiguous input.

    x >= 0 is Minisat internal Lit.x; -1/-2 are the capture's true/false sentinels.
    The atom descriptions themselves must already have an authenticated semantic match.
    """
    atoms={}
    byvar={}
    for atom,x in bindings:
        if not isinstance(atom,str) or not atom or type(x) is not int or x < -2 or atom in atoms:
            raise ValueError("unknown_or_ambiguous_binding")
        atoms[atom]=x
        if x>=0: byvar.setdefault(x//2,[]).append(atom)
    out={}
    for atom,x in atoms.items():
        if x<0: out[atom]=("constant",x==-1)
        else:
            group=sorted(byvar[x//2])
            out[atom]=("literal",tuple((a,(atoms[a]^x)&1) for a in group))
    return out


def check_binding():
    baseline=[("guard(A)",6),("guard(B)",7),("RF(W,R)",8)]
    a=signed_atoms(baseline)
    tests={"pure_renumber":[("RF(W,R)",34),("guard(B)",25),("guard(A)",24)],
           "split_alias":[("guard(A)",6),("guard(B)",11),("RF(W,R)",8)],
           "flip_one_sign":[("guard(A)",6),("guard(B)",6),("RF(W,R)",8)],
           "change_semantic_RF_at_same_number":[("guard(A)",6),("guard(B)",7),("RF(V,R)",8)],
           "replace_with_constant":[("guard(A)",-1),("guard(B)",7),("RF(W,R)",8)]}
    out={}
    for name,rows in tests.items():
        b=signed_atoms(rows)
        out[name]={"before":baseline,"after":rows,"same_semantic_bindings":b==a}
        assert (a==b)==(name=="pure_renumber")
    def definition(rows, meaning):
        # The toy Boolean language is a positive predicate with an optional negation.
        return {atom:(meaning[x//2][0],meaning[x//2][1] ^ bool(x&1)) for atom,x in rows}
    origin=[("guard(A)",6),("guard(B)",7)]
    before=definition(origin,{3:("gate",False)})
    for label,rows,meaning,valid in (
        ("compensated_polarity", [("guard(A)",15),("guard(B)",14)], {7:("gate",True)},True),
        ("same_slots_changed_definition",origin,{3:("different_gate",False)},False),
        ("all_signs_flipped_without_definition_change",
         [("guard(A)",7),("guard(B)",6)],{3:("gate",False)},False)):
        assert signed_atoms(rows)==signed_atoms(origin)
        after=definition(rows,meaning)
        assert (before==after)==valid
        out[label]={"old_decoded_definitions":before,"new_decoded_definitions":after,
                    "same_alias_partition":True,"semantic_admission":valid}
    # An isolated Boolean atom may be globally complemented if its semantic
    # binding also changes sign. Re-encode its signed semantics on import.
    for rows in ([("guard(A)",6),("guard(A)",8)],[("unknown",-3)]):
        try: signed_atoms(rows)
        except ValueError: continue
        raise AssertionError("unsafe binding accepted")
    return out


def check_update(old,new,prior,fresh,oracle):
    got,updated,stats=run(new,prior)
    assert got==oracle, (old,new,got^oracle)
    assert updated.keys()==fresh.keys()
    for key,facts in updated.items():
        assert facts.keys()==fresh[key].keys(), (old,new,key)
    return stats,updated


def targeted():
    a=Event("a","A","W","x")
    b=Event("b","B","W","x")
    c=Event("c","B","R","x")
    d=Event("d","D","N","")
    base=Graph((a,b,c,d),rf=(("a","c"),("b","c"),("init:x","c")))
    ordered=replace(base,po=(("a","b"),("b","c")))
    acyclic=replace(ordered,rf=(("b","c"),))
    cycle=replace(acyclic,po=acyclic.po+(("c","a"),))
    alt=Graph((a,b,replace(c,op="N"),d),po=(("a","b"),("b","d"),("a","c"),("c","d")))
    # c is an external event with mandatory timing between a and b.
    apart=Graph((replace(a,thread="B"),b,replace(c,op="N",thread="C")),
                po=(("a","b"),("a","c"),("c","b")))
    together=replace(apart,po=(("a","c"),("c","b")),apo=(("a","b"),))
    guarded=replace(base,events=(replace(a,guard="g"),b,c,d))
    with_new=replace(ordered,events=ordered.events+(Event("e","E","W","x"),),
                     rf=ordered.rf+(("e","c"),))
    renamed=replace(ordered,events=(replace(a,key="a_new"),b,c,d),
                    po=(("a_new","b"),("b","c")),rf=(("a_new","c"),("b","c"),("init:x","c")))
    projected=Graph((a,replace(b,guard="0"),replace(c,op="N")),po=(("a","b"),("b","c")))
    cases={"addition_closes_cycle":(acyclic,cycle),"deletion_revokes_conflict":(cycle,acyclic),
           "alternate_proof_after_deletion":(alt,replace(alt,po=alt.po[1:])),
           "merge_po_to_apo":(apart,together),"split_apo_to_po":(together,apart),
           "guard_polarity":(guarded,replace(guarded,events=(replace(a,guard="!g"),b,c,d))),
           "replace_read_from":(replace(ordered,rf=(("a","c"),)),acyclic),
           "new_event_and_source":(ordered,with_new),"remove_event_and_source":(with_new,ordered),
           "replace_event_identity":(ordered,renamed),
           "renumber_and_reorder_declarations":(ordered,replace(ordered,events=ordered.events[::-1],
                                                                rf=ordered.rf[::-1],po=ordered.po[::-1])),
           "guarded_out_static_midpoint":(projected,replace(projected,po=projected.po[1:])),
           "change_operand_type_at_old_key":(base,replace(base,events=(replace(a,typ="uint32"),b,c,d),
                                                          rf=(("b","c"),("init:x","c"))))}
    out={}
    for name,(old,new) in cases.items():
        old_models,bank,_=run(old)
        assert old_models==strict_models(old)
        reference=strict_models(new)
        _,fresh,_=run(new)
        stats,updated=check_update(old,new,bank,fresh,reference)
        row={"old":old.document(),"new":new.document(),"difference":difference(old,new),
             "old_orders":len(old_models),"new_orders":len(reference),"cache_counts":dict(stats),
             "old_only_example":min(old_models-reference,default=None),
             "new_only_example":min(reference-old_models,default=None)}
        if name in ("addition_closes_cycle","deletion_revokes_conflict"):
            key=next(iter(bank))
            bad=updated[key] if name=="addition_closes_cycle" else bank[key]
            row["cycle_proof"]=explain(bad,("a","a"))
            assert [len(old_models)==0,len(reference)==0].count(True)==1
        if name=="alternate_proof_after_deletion":
            key=next(iter(bank))
            row["proofs"]=[explain(t[key],("a","d")) for t in (bank,updated)]
            assert bank[key]["a","d"].leaves!=updated[key]["a","d"].leaves
            assert stats["retained"] and stats["discarded"]
        if name=="merge_po_to_apo": assert old_models and not reference
        if name=="split_apo_to_po": assert not old_models and reference
        if name=="renumber_and_reorder_declarations":
            assert old_models==reference and stats["retained"] and not stats["inserted"]
        out[name]=row
    refused={}
    for name,g in {"duplicate_event_key":replace(base,events=(a,a)),
                   "unbound_order":replace(base,po=(("unknown","a"),)),
                   "cross_thread_atomic":replace(base,apo=(("a","b"),)),
                   "misbound_rf_address":replace(base,events=(replace(a,addr="y"),b,c,d))}.items():
        try: run(g)
        except ValueError as err: refused[name]=str(err)
        else: raise AssertionError(name)
    # A corrupted cache labels a false reverse edge with the true forward proof.
    good=Graph((a,b),po=(("a","b"),))
    models,original,_=run(good)
    branch=next(iter(original))
    corrupt={branch:dict(original[branch])}
    corrupt[branch]["b","a"]=original[branch]["a","b"]
    actual,after,stats=run(good,corrupt)
    assert actual==models==strict_models(good) and ("b","a") not in after[branch]
    assert stats["discarded"]==1
    refused["forged_reverse_proof"]={"rejected_fact":["b","a"],"real_premise":["po","a","b"],
                                     "discarded":stats["discarded"],"surviving_orders":len(actual)}
    return out,refused


def systematic():
    fixed=(Event("a","A","W","x"),Event("b","B","W","x"),Event("c","B","R","x"),Event("d","D","N",""))
    edges=(("a","b"),("b","c"),("c","a"),("c","d"))
    sources=(("init:x","c"),("a","c"),("b","c"))
    space={}
    for key in product(range(16),range(1,8),range(3),range(2)):
        em,rm,gm,am=key
        g=Graph((replace(fixed[0],guard=("1","g","!g")[gm]),)+fixed[1:],
                tuple(edge for j,edge in enumerate(edges) if em&(1<<j)),
                (("b","c"),) if am else (),tuple(edge for j,edge in enumerate(sources) if rm&(1<<j)))
        exact=strict_models(g)
        cold,bank,_=run(g)
        assert cold==exact,key
        space[key]=(g,bank,exact)
    totals=Counter()
    per_edit=Counter()
    for (em,rm,gm,am),(old,prior,_) in space.items():
        neighbors=[("order",(em^(1<<j),rm,gm,am)) for j in range(4)]
        neighbors.extend(("rf",(em,rm^(1<<j),gm,am)) for j in range(3) if rm^(1<<j))
        neighbors.extend(("guard",(em,rm,g2,am)) for g2 in range(3) if g2!=gm)
        neighbors.append(("atomic",(em,rm,gm,am^1)))
        for kind,key in neighbors:
            new,fresh,oracle=space[key]
            stats,_=check_update(old,new,prior,fresh,oracle)
            totals.update(stats)
            per_edit[kind]+=1
    return {"graphs":len(space),"directed_updates":sum(per_edit.values()),"kinds":dict(per_edit),
            "cold_strict_orders_including_guard_and_rf":sum(len(m) for _,_,m in space.values()),
            "cache_counts":dict(totals),"model_set_disagreements":0,"closure_fact_set_disagreements":0,
            "generator":{"po":edges,"rf_nonempty_subsets":sources,"guard_on_a":["1","g","!g"],
                         "atomic_edge_options":[[],[["b","c"]]],"events":[astuple(e) for e in fixed]}}
