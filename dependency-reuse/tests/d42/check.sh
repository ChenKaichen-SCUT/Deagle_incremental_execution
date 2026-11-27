#!/usr/bin/env bash
set -euo pipefail
tree=$(realpath "$1"); tools=$(realpath "$2"); tests=$(realpath "$3"); out=$(realpath -m "$4")
mkdir "$out"
cd "$tree"
export LC_ALL=C PATH=/usr/bin:/bin
s=dependency-reuse
flags=(-O2 -std=c++11 -I src -I minisat-2.2.1)
bash "$s/scripts/build_d4_tools.sh" "$tree" "$out/legacy"
g++ "${flags[@]}" -DRECORD_PROOFS -DD41_TRIPLETS -DD42_LIGHT "$s/tests/d3/native.cpp" src/solvers/solvers.a -o "$tests/native42"
g++ "${flags[@]}" "$s/tests/d42/lifetime.cpp" -o "$tests/lifetime42"
python3 "$s/tests/d4/check.py" "$out/legacy/select" "$tests/d4" "$out/d4"
python3 "$s/tests/d4/guards.py" "$out/d4" > "$out/guards.json"
"$tests/d4/imports" > "$out/imports.txt"
stock=$(python3 -c 'import json;print(json.load(open("dependency-reuse/configs/build.json"))["binary_path"])')
python3 "$s/tests/d4/library.py" src/cbmc/deagle_exe "$stock" "$out/legacy" "$out/libraries"
python3 "$s/tests/d41/check.py" "$out/legacy/select" "$tests/triplet" "$out/triplets"
mkdir "$out/lifetime"
(cd "$out/lifetime"; "$tests/triplet/lifetime" > observations.txt)
"$tests/d4/scope" "$out/scope.bin" "$out/dynamic.bin" "$out/alias.bin" > "$out/scope.txt"
python3 "$s/tests/d42/negative.py" "$tools" "$tests" "$out" "$out/light"
g++ "${flags[@]}" "$s/tests/d42/structure.cpp" minisat-2.2.1/minisat/core/ProofStore.cc -o "$tests/structure42"
"$tests/structure42" "$out/light/fixture-minimize-gc/light.bin" > "$out/structure.txt"
