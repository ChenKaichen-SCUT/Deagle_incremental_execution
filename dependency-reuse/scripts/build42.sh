#!/usr/bin/env bash
set -euo pipefail
tree=$(realpath "$1")
out=$(realpath -m "$2")
mkdir -p "$out"
cd "$tree"
export LC_ALL=C PATH=/usr/bin:/bin
flags=(-O2 -std=c++11 -I src -I minisat-2.2.1)
g++ -O2 -std=c++11 dependency-reuse/d1/boolean_diff.cpp -o "$out/boolean-diff"
for two in 'select42 transport42' 'support-check support_check'; do
    read -r target src <<<"$two"
    g++ "${flags[@]}" "dependency-reuse/d4/$src.cpp" minisat-2.2.1/minisat/core/ProofStore.cc -o "$out/$target"
done
for f in d4_prepare d42_prepare d42_events d41_identity d1_identity d1_theory diff_d1 prepare_d3; do
    cp "dependency-reuse/scripts/$f.py" "$out/$f.py"
done
