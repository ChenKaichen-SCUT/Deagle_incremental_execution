#!/usr/bin/env bash
# Run the complete small gate with separate test executables and native traces.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
bin=$(realpath "$1")
stock=$(realpath "$2")
out=$(realpath -m "$3")
scripts="$root/persistent-solver/scripts"
obj=$(dirname "$bin")
mkdir -p "$out"
unset PI1R_LEDGER PI1R_DATABASE
for mode in R0 R1 R2; do
  export PI1R_MODE=$mode
  d="$out/$mode"
  mkdir -p "$d"
  python3 "$scripts/pi1-small.py" "$bin" "$d/small" "$stock" >"$d/core.log"
  python3 "$scripts/pi1-boundaries.py" "$bin" "$d/boundaries" >>"$d/core.log"
  python3 "$scripts/pi1-exhaustive.py" "$bin" "$stock" "$d/exhaustive" >>"$d/core.log"
  python3 "$scripts/pi1r-controls.py" "$bin" "$stock" "$d/target" >>"$d/core.log"
done
g++ -std=c++11 -O2 -Wno-literal-suffix -DDEAGLE_PI1 -I minisat-2.2.1 -I src \
  "$scripts/pi1r-progress.cpp" "$obj"/{Solver,GraphTypes,ClosureTypes,Closure,ClosureSolver,EpochSession,RestartStudy,Options,System}.o \
  -o "$obj/progress"
"$obj/progress" >"$out/progress.tsv"
PI1R_MODE=R1 bash "$scripts/pi1-owner-audit.sh" "$obj" "$out/R1/small/restart_theory_replay/protocol" "$out/owner" >"$out/owner.log"
wc -l "$out/progress.tsv"
