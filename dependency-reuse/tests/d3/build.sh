#!/usr/bin/env bash
# Build standalone fixtures and the checker against pinned native trees.
set -eu
tree=$(realpath "$1")
d1=$(realpath "$2")
observer=$(realpath "$3")
out=$(realpath -m "$4")
mkdir -p "$out"
cd "$tree"
export LC_ALL=C PATH=/usr/bin:/bin
g++ -std=c++11 -O2 -I src -I minisat-2.2.1 dependency-reuse/d3/check.cpp minisat-2.2.1/minisat/core/ProofStore.cc -o "$out/check"
g++ -std=c++11 -O2 -I src -I minisat-2.2.1 -DRECORD_PROOFS dependency-reuse/tests/d3/native.cpp \
  minisat-2.2.1/minisat/core/{ClosureSolver,Closure,ClosureTypes,GraphTypes,Solver,ProofStore}.cc \
  minisat-2.2.1/minisat/utils/{Options,System}.cc -o "$out/native"
g++ -std=c++11 -O2 -I "$d1/src" -I "$d1/minisat-2.2.1" dependency-reuse/tests/d3/native.cpp \
  "$observer" "$d1/src/solvers/solvers.a" -o "$out/oracle"
