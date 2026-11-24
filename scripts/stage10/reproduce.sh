#!/usr/bin/env bash
# Run inside a 20 GiB systemd cgroup on the frozen eight-CPU host.
# bash scripts/stage10/reproduce.sh PINNED_NATIVE_WORKTREE RESTORED_STAGE7 OUTPUT
set -euo pipefail
project="$(cd "$(dirname "$0")/../.." && pwd)"
tree=$(realpath "$1"); source=$(realpath "$2"); out=$(realpath -m "$3")
mkdir -p "$out/build"
exec 9>"$out/measurement.lock"
flock -n 9
bash "$project/scripts/stage10/build.sh" "$tree" "$out/build"
for group in pilot controls formal; do
    python3 -B "$project/scripts/stage10/experiment.py" "$source" "$tree/src/cbmc/deagle_exe" "$out/build/solver-session" "$out/$group" "$group"
done
