#!/usr/bin/env bash
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
stock=${1:?pristine built PI-0 source tree}
out=${2:?output binary}
test "$(git -C "$stock" rev-parse HEAD)" = d8c79eaba5df03b1a013dc6ffbb3a1e249485c1e
git -C "$stock" diff --exit-code HEAD -- minisat-2.2.1
m="$stock/minisat-2.2.1/minisat"
g++ -std=c++11 -O2 -Wno-literal-suffix -I "$repo/persistent-solver/include" -I "$stock/minisat-2.2.1" -I "$stock/src" \
    "$repo/persistent-solver/src/pi1-stock-control.cpp" "$m"/core/{Solver,GraphTypes,ClosureTypes,Closure,ClosureSolver}.o \
    "$m"/utils/Options.o -o "$out"
sha256sum "$out"
