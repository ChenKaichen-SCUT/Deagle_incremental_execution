"""Independently replay the signed literal map on every original input occurrence."""
from collections import Counter
import gzip


def lines(path):
    with gzip.open(path,"rt") as file:
        for line in file:
            yield line.split()


def verify(pair, manifests):
    maps = [{},{}]
    for s, v, peer, role, reason, key in lines(pair/"variables.tsv.gz"):
        if int(peer)>=0:
            maps[int(s)][int(v)] = int(peer)
    for s in (0,1):
        for var,peer in maps[s].items():
            if maps[1-s][peer//2] != 2*var+(peer&1):
                raise ValueError("literal map fails signed inverse")
    keys = {int(i):(scope,tuple(map(int,lits))) for i,scope,*lits in lines(pair/"clause-keys.tsv.gz")}
    expected = {int(i):(int(a),int(b)) for i,_,a,b in lines(pair/"clause-counts.tsv.gz")}
    if keys.keys()!=expected.keys(): raise ValueError("inconsistent declaration index")
    source = iter(lines(pair/"occurrences.tsv.gz"))
    counts = [Counter(),Counter()]
    total = [Counter(),Counter()]
    candidates = {}
    witness = None
    for s,p in enumerate(manifests):
        n = 0
        with p.open() as file:
            for line in file:
                if not line.startswith("C\t"): continue
                n += 1
                _,scope,*raw = line.split()
                actual = tuple(map(int,raw))
                side,seq,table_scope,leaf,reason = next(source)
                if (int(side),int(seq),table_scope) != (s,n,scope): raise ValueError("source order mismatch")
                total[s][scope] += 1
                canonical = []
                unresolved = None
                for l in actual:
                    if l in (-1,-2): canonical.append(l+2)
                    elif l//2 not in maps[s]:
                        unresolved = l
                        break
                    else:
                        canonical.append(l if not s else maps[s][l//2] ^ (l&1))
                leaf = int(leaf)
                if not leaf:
                    if reason.startswith("literal:"):
                        if unresolved != int(reason.split(":")[1]): raise ValueError("wrong missing literal")
                    elif not ((reason=="query_scope_changed_or_unknown" and scope=="Q") or
                              (reason=="unknown_origin" and scope not in ("B","Q"))):
                        raise ValueError(f"unjustified unknown input at {s}/{seq}: {reason}")
                    continue
                if unresolved is not None or keys[leaf] != (scope,tuple(sorted(set(canonical)))):
                    raise ValueError(f"invalid matched input at side {s}, occurrence {n}")
                counts[s][leaf] += 1
                if scope=="B" and expected[leaf][1] and len(actual) <= 4:
                    if not s: candidates.setdefault(leaf,(n,actual))
                    elif leaf in candidates:
                        oldseq,oldraw = candidates[leaf]
                        differs = set(oldraw)!=set(actual)
                        if witness is None or (not witness["different_local_literals"] and differs):
                            witness = dict(key=leaf,old_occurrence=oldseq,old_raw=oldraw,
                                           new_occurrence=n,new_raw=actual,canonical=keys[leaf][1],
                                           different_local_literals=differs)
    if next(source,None) is not None: raise ValueError("extra occurrences")
    if any((counts[0][i],counts[1][i]) != pair_counts for i,pair_counts in expected.items()):
        raise ValueError("leaf multiplicity mismatch")
    return dict(verified_occurrences=total, verified_variable_pairs=len(maps[0]), boolean_witness=witness)
