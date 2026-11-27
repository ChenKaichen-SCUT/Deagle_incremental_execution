#!/usr/bin/env bash
# D1_SOURCE and D1_OBSERVER come from the frozen D1 observation-only build.
set -euo pipefail
tree=$(realpath "$1")
d1=$(realpath "$2")
observer=$(realpath "$3")
out=$(realpath -m "$4")
mkdir "$out"
bash "$tree/dependency-reuse/tests/d4/build.sh" "$tree" "$d1" "$observer" "$out/d4"
mkdir "$out/triplet"
for name in oracle check p1; do ln "$out/d4/$name" "$out/triplet/$name"; done
cd "$tree"
export LC_ALL=C PATH=/usr/bin:/bin
flags=(-O2 -std=c++11 -I src -I minisat-2.2.1)
g++ "${flags[@]}" -DRECORD_PROOFS -DD41_TRIPLETS dependency-reuse/tests/d3/native.cpp src/solvers/solvers.a -o "$out/triplet/native"
g++ "${flags[@]}" dependency-reuse/tests/d41/lifetime.cpp src/solvers/solvers.a -o "$out/triplet/lifetime"
g++ "${flags[@]}" dependency-reuse/d4/check_slice.cpp minisat-2.2.1/minisat/core/ProofStore.cc -o "$out/triplet/check-slice"
g++ "${flags[@]}" dependency-reuse/tests/d3/native_scope.cpp src/solvers/solvers.a -o "$out/d4/scope"
