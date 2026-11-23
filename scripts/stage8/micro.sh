#!/usr/bin/env bash
set -euo pipefail
tree=$(realpath "$1")
source_run=$(realpath "$2")
out=$(realpath -m "$3")
project="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "$out"
g++ -std=c++11 -O2 -DSATCHECK_MINISAT2 -DHAVE_MINISAT2 -I"$tree/src" "$project/scripts/stage8/cache_probe.cpp" "$tree/src/util/util.a" -o "$out/cache-codec"
python3 -B "$project/scripts/stage8/change_probe.py" "$source_run" "$out/cache-codec" "$out"
