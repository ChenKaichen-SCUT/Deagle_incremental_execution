#!/usr/bin/env bash
# Builds the worker in a native-source-11c checkout after make -C src cbmc.dir.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
tree=$(cd "$here/.." && pwd)
out=$(realpath -m "${1:-$tree/local-build}")
mkdir -p "$out"
flags=(-std=c++11 -O2 -Wno-literal-suffix -DSATCHECK_MINISAT2 -DHAVE_MINISAT2
       -D__STDC_FORMAT_MACROS -D__STDC_LIMIT_MACROS -I"$tree/minisat-2.2.1"
       -I"$tree/src" -I"$tree/minisat-2.2.1/minisat/core" -I"$here")
objects=()
for unit in Closure ClosureSolver Solver; do
  g++ "${flags[@]}" -c "$here/$unit.cc" -o "$out/$unit.o"
  objects+=("$out/$unit.o")
done
libs=(-Wl,--start-group "$tree/src/solvers/solvers.a" "$tree/src/util/util.a" -Wl,--end-group -lz -lpthread)
g++ "${flags[@]}" "$here/driver.cpp" "${objects[@]}" "${libs[@]}" -o "$out/worker"
g++ -std=c++11 -O2 "$here/rupcheck.cpp" -o "$out/rupcheck"
for item in native_contract co_control; do
  g++ "${flags[@]}" "$here/$item.cpp" "${objects[@]}" "${libs[@]}" -o "$out/${item/_/-}"
done
sha256sum "$tree/src/cbmc/deagle_exe" "$out/"{worker,rupcheck,native-contract,co-control}
