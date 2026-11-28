#!/usr/bin/env bash
set -euo pipefail
src=$(realpath "$1")
out=$(realpath -m "$2")
mkdir -p "$out"
cd "$src"
g++ -O2 -std=c++11 dependency-reuse/d1/boolean_diff.cpp -o "$out/boolean-diff"
g++ -O2 -std=c++11 -Wall -Wextra dependency-reuse/d4/compact_structure.cpp -o "$out/compact-structure"
for name in d43_prepare compact43 d42_events d1_identity d1_theory d41_identity diff_d1 prepare_d3; do
  cp "dependency-reuse/scripts/$name.py" "$out/$name.py"
done
