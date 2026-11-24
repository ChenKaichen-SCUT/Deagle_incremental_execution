#!/usr/bin/env bash
set -euo pipefail
# Usage: bash reproduce_native.sh NATIVE_TREE STAGE10_FINAL OUTPUT_DIR
src=$(cd "$(dirname "$0")" && pwd)
tree=$(realpath "$1")
old=$(realpath "$2")
out=$(realpath -m "$3")
mkdir -p "$out"/rank/{shared,fresh}-{0..6} "$out"/rank/direction-{0,1}
test "$(sha256sum "$old/build/solver-session" | cut -d' ' -f1)" = c474a95f9d668619bdc138382bd59b1f070190c8197fa91071f9aca49075c204
date -u +%FT%TZ > "$out/rank/start.utc"
"$old/build/solver-session" --same-graph "$old/formal/batch_total/01/F/old" "$out/rank" > "$out/rank/stdout" 2> "$out/rank/stderr"
g++ -std=c++11 -O2 -DSATCHECK_MINISAT2 -DHAVE_MINISAT2 -D__STDC_FORMAT_MACROS -D__STDC_LIMIT_MACROS -I"$tree/minisat-2.2.1" -I"$tree/src" "$src/native_control.cpp" -Wl,--start-group "$tree/src/solvers/solvers.a" "$tree/src/util/util.a" -Wl,--end-group -lz -lpthread -o "$out/native-control"
for label in tacas tacas-reverse fm lock-p1 lock-p2; do
  "$out/native-control" "$src/fixtures/$label.txt" > "$out/$label.stdout" 2> "$out/$label.stderr"
done
sha256sum "$out/native-control" "$tree/src/solvers/solvers.a" "$tree/src/util/util.a" "$src/native_control.cpp" "$tree/src/cbmc/deagle_exe" "$old/build/solver-session" > "$out/control.sha256"
