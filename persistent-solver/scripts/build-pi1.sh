#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
out=${1:?pass an out-of-tree build directory}
mkdir -p "$out"
cd "$root"
flags=(-std=c++11 -O2 -g -Wall -Wno-parentheses -Wno-literal-suffix -DDEAGLE_PI1 -I minisat-2.2.1 -I src -I persistent-solver/include)
sources=(minisat-2.2.1/minisat/core/{Solver,GraphTypes,ClosureTypes,Closure,ClosureSolver,EpochSession,RestartStudy}.cc minisat-2.2.1/minisat/utils/{Options,System}.cc persistent-solver/src/{session,pi1-driver}.cpp)
pids=()
wait_batch() {
    local result=0
    for pid in "${pids[@]}"; do wait "$pid" || result=1; done
    pids=()
    return "$result"
}
for file in "${sources[@]}"; do
    object="$out/$(basename "${file%.*}").o"
    g++ "${flags[@]}" -MMD -MP -c "$file" -o "$object" &
    pids+=("$!")
    if (( ${#pids[@]} == 4 )); then wait_batch; fi
done
wait_batch
objects=()
for file in "${sources[@]}"; do objects+=("$out/$(basename "${file%.*}").o"); done
g++ "${objects[@]}" -o "$out/pi1"
sha256sum "$out/pi1"
