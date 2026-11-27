# D2 native CDCL proof records

`--d2-proof NEW_FILE` attaches one ProofStore to the fresh native SC Closure solver. The path is exclusive. A finished archive carries the solver exit code and a closing marker. A permanent Boolean proof must have a recorded source for every parent, including root units and reasons used by minimization. The frozen runner uses one query per process.

## Records and meaning

ProofId is the append-only node index within a P0 run. Node zero represents unavailable provenance. A conclusion stores the native literals once, with raw literal `2 * SAT variable + sign`. Each derived node starts with the conflict or initial clause and pivot `-1`. Subsequent edges store a direct parent ID and the signed pivot present in that parent. Resolution removes its complement from the current resolvent. Duplicate input literals have set semantics. For a CDCL birth, the directory records the number of first-UIP parents and minimization parents. The remaining parents discharge omitted level-zero literals. Implicit learned units have a birth ID even when MiniSat allocates no clause.

The low three flag bits represent a Closure theory boundary, a query input and missing Boolean provenance, respectively. A node inherits the union of its parents' flags. Theory reasons have their native signed clause and an opaque leaf. A conditioned learned clause may retain a negated assumption without using that assumption as a premise. Archive residents describe the native `learnts` vector, which can also contain Closure lemmas. Root unit IDs and the CDCL-only resident count are reported separately. Evictions record the last proof ID present at removal. Relocation only updates the live CRef table.

The archive starts with `DEAGD2\x01\x00` and an endian marker `0x01020304`. Each section starts with a 32-bit entry count. The sections in order are nodes, conclusion literals, parent/pivot pairs, original input occurrences and actions, CDCL births, evictions, root-satisfied database removals, resident IDs, active unit IDs, terminal contradiction IDs, reverse offsets and reverse children. The footer holds the 64-bit counters in `ProofStore.h`, a 32-bit exit status and `END2`. The format uses the frozen build's 32-bit words and little-endian ABI. A missing footer or a section that exceeds the available file data is rejected.

`ProofStore::invalidatedInputs` consumes the complete D1 occurrence match vector and the persisted reverse index. It marks missing, opaque, query-specific and unmatched permanent leaves, then visits their consumers through a shared work queue. Added P1 constraints supply no invalidation seed. Every non-retired learning record has one whole surviving old proof. Materializing a translated conclusion also requires an injective signed map for its variables. The independent checker resolves actual signed clauses, checks the native D1 observation stream, and compares the reverse traversal against a separate forward computation. Resolution replay and finite-model enumeration take place during audit only.

## Reproduction

Use Linux, the reviewed D1 source and its complete clean build log, and a clean checkout of the D2 implementation SHA in the report. The commands below assume that `TREE`, `D1_TREE`, `D1_LOG` and a new output directory `OUT` are absolute paths. Both trees need the frozen build dependencies listed in the D0 report.

~~~sh
cd "$TREE"
export LC_ALL=C PATH=/usr/bin:/bin
make -C src -j12 cbmc.dir
bash dependency-reuse/scripts/build_d2_tools.sh "$TREE" "$D1_TREE" "$D1_LOG" "$OUT/tools"
python3 dependency-reuse/scripts/run_d2.py src/cbmc/deagle_exe "$OUT/tools/oracle/deagle_exe" "$OUT/runs"
python3 dependency-reuse/tests/d2/check.py "$OUT/tools" "$OUT/micro"
~~~

The D1 oracle build compiles one observation-only object against its own D1 tree. It writes each actual learned clause immediately after native analysis, the final native resident clauses and the active roots. The D2 checker links the archive and reverse-index implementation. It does not link the solver search library.

To replay one frozen proof from the D2 report checkout, use the checker built above. Repeat numbers 1, 2 and 3 each reconstruct the exact original archive, including the recorded clocks.

~~~sh
python3 dependency-reuse/scripts/recheck_d2.py "$OUT/tools/check" circular-buffer "$OUT/circular-replay" --repeat 2
~~~

For a new full run, compile the reviewed `dependency-reuse/d1/boolean_diff.cpp` as in D1. For each case decompress its D1 `runs/record/<case>/P0/native.tsv.gz` to a scratch file. Run `diff_d1.py P0.tsv P0.tsv D1_DIFF "$OUT/self/<case>"`. This self-comparison detects conservative identities even on identical native input. Then run the following from a D2 report checkout that contains the original D1 evidence.

~~~sh
python3 dependency-reuse/scripts/prepare_d2.py "$OUT/inputs" --self-diffs "$OUT/self"
python3 dependency-reuse/scripts/package_d2.py "$OUT/runs" "$OUT/tools" "$OUT/inputs" "$OUT/self" "$OUT/micro" "$OUT/evidence" "$OUT/checks"
~~~

## Audit tables

Each row of `learned.tsv` gives ProofId, arity, inherited flags, direct theory parent, invalidation cause bits, resident-in-database bit, active learned unit bit, old proof survives bit, translated conclusion available bit, UIP edge count and minimization edge count. Zero flags mean complete permanent Boolean. `survivors.tsv` stores ProofId and the signed P1 literals for diagnostic comparison.

In the invalidation mask, 1 indicates a fully mapped permanent or query clause absent on P1, 2 a missing gate identity, 4 a missing other variable, 8 a query leaf, 16 a theory leaf and 32 missing proof provenance. Bits 64 and 128 distinguish unmapped input occurrences also rejected on P0/P0 from those rejected only across the pair. These two diagnostics apply per occurrence and are propagated by union. `used.tsv` stores original occurrence ordinal, input ProofId, reachability (1 for all learned proofs, 2 for the permanent Boolean subset), seed cause, and direct edge counts into each reachable subgraph. Rates in the report count distinct physical input occurrences; raw tables also provide edge-weighted counts. The first failing native operand, frozen source line evidence when available, and a traversable path from each example input to an actual learning record are in `used-input-analysis.json`.
