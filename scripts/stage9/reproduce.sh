#!/usr/bin/env bash
# bash scripts/stage9/reproduce.sh STAGE8_CHECKOUT RESTORED_STAGE7 STAGE8_NATIVE_LOCK OUTPUT
set -euo pipefail
cd "$(dirname "$0")/../.."
project="$PWD"
baseline=$(realpath "$1")
source_run=$(realpath "$2")
lock=$(realpath "$3")
out=$(realpath -m "$4")
mkdir -p "$out/build"
test "$(git -C "$baseline" rev-parse HEAD)" = edd7386f8674eb5db08593d327256ea874bf05f6
test -f "$source_run/matrix.json"
python3 -B scripts/stage9/build.py "$baseline" "$lock" "$out/build"
# A resumed run keeps completed receipts. All side controls share the same lock as the timed workers.
exec 8>"$(dirname "$lock")/measurement.lock"
flock 8
python3 -B scripts/stage9/trial.py "$project" "$source_run" "$lock" "$out/pilot/after" batch_total I3 1 > "$out/pilot.log"
p="$out/pilot/after/batch_total/01/off/I3"
attempt=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["attempt"])' "$p/complete.json")
if ! test -e "$out/audit/equivalence/checks.json"; then
    python3 -B scripts/stage9/equivalence.py "$source_run" "$p/$attempt/pair/frontend/compiler-spool" "$out/audit/equivalence"
fi
python3 -B scripts/stage9/negative.py "$source_run" "$out/audit/negative" >> "$out/negative.log" 2>&1
flock -u 8
python3 -B scripts/stage9/run_matrix.py "$baseline" "$source_run" "$lock" "$out" formal >> "$out/formal.log" 2>&1
python3 -B scripts/stage9/run_matrix.py "$baseline" "$source_run" "$lock" "$out" regression >> "$out/regression.log" 2>&1
flock 8
python3 -B scripts/stage9/profile.py "$baseline" "$source_run" "$lock" "$out/frontend" >> "$out/details.log" 2>&1
python3 -B scripts/stage9/release_cli.py "$source_run" "$out/audit/production" >> "$out/release-cli.log" 2>&1
flock -u 8
python3 -B scripts/stage9/evidence.py --raw "$out" --stage7 "$source_run" --write "$out/evidence"
