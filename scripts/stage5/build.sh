#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
tree="$PWD/third_party/deagle-stage5"
lock=configs/stage05.lock.json
expected=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["development_commit"])' "$lock")
test "$(git -C "$tree" rev-parse HEAD)" = "$expected"
git -C "$tree" diff --quiet HEAD --
jobs=$(python3 -c 'import yaml;print(yaml.safe_load(open("configs/project.yaml"))["resources"]["build"]["jobs"])')
export CCACHE_DIR="$PWD/runs/stage-01/ccache" CCACHE_BASEDIR="$tree" PATH="/usr/lib/ccache:$PATH"
mkdir -p "$CCACHE_DIR" runs/stage-05
exec 9>runs/stage-05/build.lock
flock 9
make -C "$tree/src" -j"$jobs" cbmc.dir
expected_hash=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["development_sha256"])' "$lock")
echo "$expected_hash  $tree/src/cbmc/deagle_exe" | sha256sum -c -
