#!/usr/bin/env bash
# Both source trees must have their own native build. D1_OBJECT is the D1 birth observer.
set -euo pipefail
tree=$(realpath "$1")
d1=$(realpath "$2")
observer=$(realpath "$3")
out=$(realpath -m "$4")
mkdir -p "$out"
cd "$tree"
export LC_ALL=C PATH=/usr/bin:/bin
flags=(-O2 -std=c++11 -I src -I minisat-2.2.1)
fixture=dependency-reuse/tests/d3/native.cpp
g++ "${flags[@]}" dependency-reuse/d3/check.cpp minisat-2.2.1/minisat/core/ProofStore.cc -o "$out/check"
g++ "${flags[@]}" -DRECORD_PROOFS "$fixture" src/solvers/solvers.a -o "$out/native"
g++ "${flags[@]}" -DIMPORT_PROOFS "$fixture" src/solvers/solvers.a -o "$out/p1"
g++ "${flags[@]}" dependency-reuse/tests/d4/imports.cpp src/solvers/solvers.a -o "$out/imports"
g++ -O2 -std=c++11 -I "$d1/src" -I "$d1/minisat-2.2.1" "$fixture" "$observer" "$d1/src/solvers/solvers.a" -o "$out/oracle"
