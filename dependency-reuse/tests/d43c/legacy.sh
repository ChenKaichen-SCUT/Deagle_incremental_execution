#!/usr/bin/env bash
# Rebuild only the fixture clients against the C library. Keep the independent D1 oracle executable frozen.
set -euo pipefail
tree=$(realpath "$1")
frozen=$(realpath "$2")
tools=$(realpath "$3")
out=$(realpath -m "$4")
mkdir -p "$out/tools/d4" "$out/tools/triplet"
cd "$tree"
f=(-O2 -std=c++11 -I src -I minisat-2.2.1)
d=dependency-reuse
lib=src/solvers/solvers.a
cp "$frozen/d4/oracle" "$out/tools/d4/oracle"
cp "$frozen/triplet/oracle" "$out/tools/triplet/oracle"
g++ "${f[@]}" "$d/d3/check.cpp" minisat-2.2.1/minisat/core/ProofStore.cc -o "$out/tools/d4/check"
cp "$out/tools/d4/check" "$out/tools/triplet/check"
g++ "${f[@]}" -DRECORD_PROOFS "$d/tests/d3/native.cpp" "$lib" -o "$out/tools/d4/native"
g++ "${f[@]}" -DIMPORT_PROOFS "$d/tests/d3/native.cpp" "$lib" -o "$out/tools/d4/p1"
cp "$out/tools/d4/p1" "$out/tools/triplet/p1"
g++ "${f[@]}" "$d/tests/d4/imports.cpp" "$lib" -o "$out/tools/d4/imports"
g++ "${f[@]}" "$d/tests/d3/native_scope.cpp" "$lib" -o "$out/tools/d4/scope"
g++ "${f[@]}" -DRECORD_PROOFS -DD41_TRIPLETS "$d/tests/d3/native.cpp" "$lib" -o "$out/tools/triplet/native"
g++ "${f[@]}" "$d/tests/d41/lifetime.cpp" "$lib" -o "$out/tools/triplet/lifetime"
g++ "${f[@]}" "$d/d4/check_slice.cpp" minisat-2.2.1/minisat/core/ProofStore.cc -o "$out/tools/triplet/check-slice"
bash "$d/tests/d42/check.sh" "$tree" "$tools" "$out/tools" "$out/results"
