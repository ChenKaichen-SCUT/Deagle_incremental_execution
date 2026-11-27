#!/usr/bin/env bash
set -euo pipefail
tree=$(realpath "$1")
out=$(realpath -m "$2")
mkdir "$out"
cd "$tree"
export PATH=/usr/bin:/bin LC_ALL=C
g++ -O2 -std=c++11 dependency-reuse/d1/boolean_diff.cpp -o "$out/boolean-diff"
g++ -O2 -std=c++11 -I src -I minisat-2.2.1 dependency-reuse/d4/select.cpp \
  minisat-2.2.1/minisat/core/ProofStore.cc -o "$out/select"
for f in d4_prepare d41_identity d1_identity d1_theory diff_d1 prepare_d3; do
  cp "dependency-reuse/scripts/$f.py" "$out/$f.py"
done
