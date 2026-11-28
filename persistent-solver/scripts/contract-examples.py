"""Finite semantics check of the PI-0 design examples. No solver, cache or session implementation."""
import itertools
import json


def check():
    # a_before_b is the enumerated SC order of two distinct events.
    controls = list(itertools.product((False, True), repeat=6))
    values = list(itertools.product((False, True), repeat=4))
    count = 0
    counterexample = None
    for s0, s1, e0, e1, q0, q1 in controls:
        for x, y, rf, a_before_b in values:
            # P0 has a<b; both graphs include rf => b<a. Each query protects its goal.
            permanent = ((not s0 or x) and (not s1 or y) and
                         (not e0 or a_before_b) and (not e0 or not rf or not a_before_b) and
                         (not e1 or not rf or not a_before_b) and
                         (not q0 or not rf) and (not q1 or rf))
            if permanent:
                count += 1
                if e0 and rf:
                    raise ValueError("guarded theory consequence is not entailed")
            if (s0, s1, e0, e1, q0, q1) == (True, False, True, False, True, False):
                direct = x and a_before_b and (not rf or not a_before_b) and not rf
                if direct != permanent:
                    raise ValueError("P0 projection differs")
            if (s0, s1, e0, e1, q0, q1) == (False, True, False, True, False, True):
                direct = y and (not rf or not a_before_b) and rf
                if direct != permanent:
                    raise ValueError("P1 projection differs")
                if direct and not x:
                    counterexample = dict(x=x, y=y, rf=rf, order="b<a")
    if counterexample is None:
        raise ValueError("missing P1 witness rejecting both unguarded old x and unguarded old not-rf")
    return dict(valuations=len(controls)*len(values), permanent_models=count,
                projected_assignments_checked_per_version=len(values), guarded_consequence="!e0 || !rf",
                P1_counterexample_to_old_x_and_old_not_rf=counterexample)


if __name__ == "__main__":
    print(json.dumps(check(), indent=2))
