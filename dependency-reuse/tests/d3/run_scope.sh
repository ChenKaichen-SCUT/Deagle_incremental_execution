#!/bin/bash
set -eu
if [ "$#" -ne 1 ]; then echo "usage: $0 NEW_OUTPUT_DIRECTORY" >&2; exit 2; fi
root=$(cd "$(dirname "$0")/../../.." && pwd)
out=$(realpath -m "$1")
mkdir "$out"
cd "$root"
g++ -std=c++11 -O2 -I src -I minisat-2.2.1 dependency-reuse/tests/d3/native_scope.cpp \
    minisat-2.2.1/minisat/core/{ProofStore,GraphTypes,ClosureTypes,Solver,Closure,ClosureSolver}.cc \
    minisat-2.2.1/minisat/utils/Options.cc -o "$out/native-scope"
"$out/native-scope" "$out/scope.bin" "$out/dynamic.bin" > "$out/observations.txt"
(cd "$out"; sha256sum native-scope scope.bin dynamic.bin observations.txt > sha256.txt)
cat "$out/observations.txt"