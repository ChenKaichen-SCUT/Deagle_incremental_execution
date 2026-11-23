#!/usr/bin/env bash
# Run in a separate Linux checkout with the stage 7 binaries installed.
# bash scripts/stage8/reproduce.sh NEW_RUN_DIRECTORY [RESTORED_STAGE7_DIRECTORY]
set -euo pipefail
cd "$(dirname "$0")/../.."
project="$PWD"
a=$(realpath -m "$1")
if test -e "$a"; then echo 'Choose a fresh output directory.' >&2; exit 2; fi
mkdir -p "$a/build" "$a/audit"
s7=$(realpath -m "${2:-$a/stage7}")
if ! test -e "$s7/matrix.json"; then
  mkdir -p "$s7"
  python3 -B - "$s7" <<'PY'
from pathlib import Path
from scripts.stage7.check_evidence import restore,EVIDENCE
import sys
restore(EVIDENCE,Path(sys.argv[1]))
PY
fi
python3 -B scripts/stage7/check_evidence.py
python3 -B scripts/stage8/environment.py "$s7" "$a/audit/environment.json"
python3 -B scripts/stage8/old_controls.py "$s7" "$PWD/third_party" "$a/old-controls" > "$a/old-controls.log"
for pair in 'baseline deagle-baseline a159f9923722646185ba8028610b2eef2618fa72' 'enhanced deagle-stage5 0be9e2167d46c66ea12ca7f9f801063a03873625'; do
  read -r role tree rev <<< "$pair"
  git -C "third_party/$tree" worktree add -b "stage8-$role-diag" "$a/worktrees/$role" "$rev"
done
bash scripts/stage8/build.sh "$a/worktrees/baseline" "$a/worktrees/enhanced" "$a/build" > "$a/build-console.log" 2>&1
lock="$a/build/lock.json"
python3 -B scripts/stage8/experiment.py --source "$s7" --lock "$lock" --out "$a/pilot" --cases batch_total --repeats 1 > "$a/pilot.log"
python3 -B scripts/stage8/experiment.py --source "$s7" --lock "$lock" --out "$a/formal" > "$a/formal.log"
exec 8>"$a/build/measurement.lock"
flock 8
unit=(systemd-run --quiet --pipe --wait --collect -p MemoryMax=21474836480 -p "WorkingDirectory=$project")
"${unit[@]}" /usr/bin/python3 -B "$project/scripts/stage8/frontend_probe.py" "$s7" "$a/frontend" "$lock"
"${unit[@]}" /usr/bin/strace -f -ttt -T -s 90 -e trace=process,clock_nanosleep,openat -o "$a/strace-frontend.txt" \
  /usr/bin/python3 -B "$project/scripts/stage8/frontend_probe.py" "$s7" "$a/frontend-traced" "$lock" trace
python3 -B scripts/stage8/side.py "$s7" "$lock" "$a/side" > "$a/side.log"
bash scripts/stage8/structural_build.sh third_party/deagle-baseline third_party/deagle-stage5 "$a/worktrees/equation" "$a/build" >> "$a/side.log" 2>&1
python3 -B scripts/stage8/structural.py "$s7" "$a/worktrees/equation/src/cbmc/deagle_exe" "$a/structural" >> "$a/side.log"
bash scripts/stage8/micro.sh "$a/worktrees/enhanced" "$s7" "$a/micro" > "$a/micro.log" 2>&1
for role in baseline enhanced; do
  bash scripts/stage8/replay_build.sh "$a/worktrees/$role" "$a/worktrees/stream-$role" "$role" "$a/build" >> "$a/replay.log" 2>&1
done
python3 -B scripts/stage8/replay.py "$s7" "$a/build" "$a/replay" "$a/worktrees/stream-baseline" "$a/worktrees/stream-enhanced" >> "$a/replay.log"
"${unit[@]}" /usr/bin/python3 -B "$project/scripts/stage8/setup_probe.py" "$s7" "$a/frontend-setup" > "$a/setup.log"
flock -u 8
python3 -B scripts/stage8/provenance.py "$a/worktrees" "$a"
python3 -B scripts/stage8/statistics8.py "$a/formal" "$a/evidence"
python3 -B scripts/stage8/supplement.py "$a" "$a/evidence"
python3 -B scripts/stage8/tables.py "$a/evidence"
python3 -B scripts/stage8/frontend_report.py "$a" "$a/evidence"
python3 -B scripts/stage8/solver_report.py "$a/evidence"
python3 -B scripts/stage8/maintenance_report.py "$a/evidence"
python3 -B scripts/stage8/potential.py "$a/evidence"
python3 -B scripts/stage8/archive.py pack "$a" "$a/evidence"
python3 -B scripts/stage8/check_evidence.py --evidence "$a/evidence" --stage7 "$s7"
python3 -B scripts/stage8/plots.py "$a/evidence"
