#!/usr/bin/env bash
# Reproduce one PI-1 functional pass with the frozen per-case limits.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
scripts="$root/persistent-solver/scripts"
repo=$(realpath "${1:?research Git repository}")
stock=$(realpath "${2:?pristine built upstream worktree}")
out=$(realpath -m "${3:?new output directory}")
source_sha=${4:?fixed PI-1 implementation SHA}
test ! -e "$out"
mkdir -p "$out/raw" "$out/bin"
export LC_ALL=C PYTHONDONTWRITEBYTECODE=1
bash "$scripts/build-pi1.sh" "$out/final" > "$out/raw/final-compile.log"
bash "$scripts/build-pi1-stock-control.sh" "$stock" "$out/bin/stock-control" > "$out/raw/stock-control-build.log"
python3 "$scripts/pi1-small.py" "$out/final/pi1" "$out/small-checks/small" "$out/bin/stock-control"
python3 "$scripts/pi1-boundaries.py" "$out/final/pi1" "$out/small-checks/boundaries"
python3 "$scripts/pi1-exhaustive.py" "$out/final/pi1" "$out/bin/stock-control" "$out/small-checks/exhaustive"
bash "$scripts/pi1-owner-audit.sh" "$out/final" "$out/small-checks/small/native_learning/protocol" "$out/owner"
cp "$out/owner/owner.txt" "$out/small-checks/owner.txt"
for case in fib_updates_8 airline_reservations_6 fib-snapshot-11 circular-buffer; do
    python3 "$scripts/pi1-real.py" "$repo" "$out/final/pi1" "$stock/src/cbmc/deagle_exe" "$out" boundary "$case"
done
python3 - "$out" <<'PY'
import json, pathlib, sys
gates=[json.loads(p.read_text()) for p in pathlib.Path(sys.argv[1],"raw").glob("*/warning.json")]
if len(gates)!=4 or any(g["stop"] for g in gates):sys.exit("Stop full searches and review the boundary receipts")
PY
for case in fib_updates_8 circular-buffer airline_reservations_6 fib-snapshot-11; do
    python3 "$scripts/pi1-real.py" "$repo" "$out/final/pi1" "$stock/src/cbmc/deagle_exe" "$out" solve "$case"
    python3 "$scripts/pi1-witness.py" "$repo" "$out" "$case"
done
python3 "$scripts/pi1-evidence.py" collect "$repo" "$out" "$out" "$out/small-checks" "$out/final/pi1" \
    "$out/bin/stock-control" "$out/evidence" "$source_sha"
python3 "$scripts/pi1-evidence.py" verify "$out/evidence"
