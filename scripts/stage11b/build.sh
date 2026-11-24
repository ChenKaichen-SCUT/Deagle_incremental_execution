#!/usr/bin/env bash
set -euo pipefail
tree=$(realpath "$1")
out=$(realpath -m "$2")
here=$(cd "$(dirname "$0")" && pwd)
test "$(git -C "$tree" rev-parse HEAD)" = a2ba2f01fcc8dc83261f614039141017fb846178
# Stage 10 prepared these archives. The standalone worker links the changed native objects first.
sha256sum "$tree/src/cbmc/deagle_exe" | grep '^b84a95d9d02e9fc48217373bf71564db1cb8ce4029644936a893aaaaef0a529e '
python3 "$here/instrument.py" "$tree" "$out/src"
if [[ ${3:-} == --audit ]]; then python3 "$here/audit_proofs.py" instrument "$out/src/native_root.hpp"; fi
flags=(-std=c++11 -O2 -Wno-literal-suffix -DSATCHECK_MINISAT2 -DHAVE_MINISAT2 -D__STDC_FORMAT_MACROS -D__STDC_LIMIT_MACROS -I"$tree/minisat-2.2.1" -I"$tree/src" -I"$tree/minisat-2.2.1/minisat/core")
for unit in Closure ClosureSolver; do
  g++ "${flags[@]}" -c "$out/src/$unit.cc" -o "$out/$unit.o"
done
g++ "${flags[@]}" "$out/src/driver.cpp" "$out/Closure.o" "$out/ClosureSolver.o" -Wl,--start-group "$tree/src/solvers/solvers.a" "$tree/src/util/util.a" -Wl,--end-group -lz -lpthread -o "$out/worker"
sha256sum "$out/worker" "$out/src/"* "$tree/src/solvers/solvers.a" "$tree/src/util/util.a" > "$out/build.sha256"
g++ --version | head -1
cat "$out/build.sha256"
