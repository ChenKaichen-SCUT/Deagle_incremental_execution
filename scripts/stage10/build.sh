#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "$0")/../.." && pwd)"
tree=$(realpath "$1")
out=$(realpath -m "$2")
mkdir -p "$out"
test "$(git -C "$tree" rev-parse HEAD)" = a2ba2f01fcc8dc83261f614039141017fb846178
if ! test -e "$tree/src/util/stage10_hooks.h"; then python3 -B "$project/scripts/stage10/instrument.py" "$tree"; else python3 -B "$project/scripts/stage10/instrument.py" "$tree" --finish; fi
export CCACHE_BASEDIR="$tree" PATH="/usr/lib/ccache:$PATH"
make -C "$tree/src" -j4 cbmc.dir > "$out/native-build.log" 2>&1 || { tail -35 "$out/native-build.log"; exit 1; }
git -C "$tree" diff HEAD > "$out/native-tracked.patch"
cp "$out/native-tracked.patch" "$out/native.patch"
for generated in stage10_telemetry.h stage10_hooks.h stage10_bridge.inc stage10_native_stats.inc; do
  rc=0
  git -C "$tree" diff --no-index -- /dev/null "src/util/$generated" >> "$out/native.patch" || rc=$?
  test "$rc" = 1
done
sha256sum "$tree/src/cbmc/deagle_exe" "$tree/src/config.inc" "$out/native-tracked.patch" > "$out/build.sha256"
if test -e "$project/scripts/stage10/driver.cpp"; then
  g++ -std=c++11 -O2 -Wall -Wextra -Wno-unused-parameter -DSATCHECK_MINISAT2 -DHAVE_MINISAT2 -D__STDC_FORMAT_MACROS -D__STDC_LIMIT_MACROS \
    -I"$tree/minisat-2.2.1" -I"$tree/src" "$project/scripts/stage10/driver.cpp" \
    -Wl,--start-group "$tree/src/solvers/solvers.a" "$tree/src/util/util.a" -Wl,--end-group -lz -lpthread -o "$out/solver-session" > "$out/driver-build.log" 2>&1 || { tail -45 "$out/driver-build.log"; exit 1; }
  sha256sum "$out/solver-session" >> "$out/build.sha256"
fi
cat "$out/build.sha256"
