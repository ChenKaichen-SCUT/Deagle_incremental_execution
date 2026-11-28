#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
build=${1:?production object directory}
protocol=${2:?two-version small protocol}
out=${3:?separate audit directory}
mkdir -p "$out"
cd "$root"
g++ -std=c++11 -O2 -Wno-literal-suffix -DDEAGLE_PI1 -I minisat-2.2.1 -I src \
  persistent-solver/scripts/pi1-owner-audit.cpp "$build"/*.o \
  -Wl,--wrap=_ZN7Minisat13ClosureSolverC1Ev,--wrap=_ZN7Minisat6SolverC2Ev,--wrap=_ZN7Minisat13ClosureSolver8runEpochERKNS_3vecINS_3LitEEEb \
  -Wl,--wrap=_ZN7Minisat7closure10push_scopeEv,--wrap=_ZN7Minisat7closure9pop_scopeEi -o "$out/owner-probe"
"$out/owner-probe" "$protocol" > "$out/out.txt" 2> "$out/owner.txt"
cat "$out/owner.txt"
