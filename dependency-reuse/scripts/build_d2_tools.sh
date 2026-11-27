#!/usr/bin/env bash
# Native trees must already have been built using their own src Makefile.
set -euo pipefail
[[ $# == 4 ]] || { echo "usage: $0 D2_TREE D1_TREE D1_BUILD_LOG NEW_DIR" >&2; exit 2; }
tree=$(realpath "$1")
baseline=$(realpath "$2")
log=$(realpath "$3")
out=$(realpath -m "$4")
[[ ! -e $out ]]
mkdir -p "$out"
export PATH=/usr/bin:/bin LC_ALL=C
python3 "$tree/dependency-reuse/scripts/build_d2_oracle.py" "$baseline" "$log" "$out/oracle"
flags=(-std=c++11 -O2)
g++ "${flags[@]}" -I "$tree/src" -I "$tree/minisat-2.2.1" "$tree/dependency-reuse/d2/check.cpp" \
    "$tree/minisat-2.2.1/minisat/core/ProofStore.cc" -o "$out/check"
g++ "${flags[@]}" -DRECORD_PROOFS -I "$tree/src" -I "$tree/minisat-2.2.1" \
    "$tree/dependency-reuse/tests/d2/native_cnf.cpp" "$tree/src/solvers/solvers.a" -o "$out/cnf-on"
g++ "${flags[@]}" -I "$baseline/src" -I "$baseline/minisat-2.2.1" \
    "$tree/dependency-reuse/tests/d2/native_cnf.cpp" "$out/oracle/ClosureSolver.o" \
    "$baseline/src/solvers/solvers.a" -o "$out/cnf-oracle"
sha256sum "$out"/{check,cnf-on,cnf-oracle} "$out/oracle/deagle_exe" > "$out/sha256.txt"
