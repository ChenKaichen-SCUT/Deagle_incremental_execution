#!/usr/bin/env bash
# Inputs: the compiled stage-10 native tree, stage-7 sources directory, pilot project, empty run directory.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
project=$(realpath "$here/../..")
tree=$(realpath "$1"); sources=$(realpath "$2"); pilot=$(realpath "$3"); out=$(realpath -m "$4")
mkdir -p "$out"; test -z "$(ls -A "$out")"
ln -s "$tree" "$out/native"
mkdir -p "$out/build" "$out/controls"
bash "$here/build.sh" "$tree" "$out/build" > "$out/build/build.log" 2>&1
exe="$tree/src/cbmc/deagle_exe"; worker="$out/build/worker"
export LC_ALL=C PYTHONDONTWRITEBYTECODE=1
python3 "$here/trials.py" "$exe" "$worker" "$sources" "$pilot" "$out/formal" --repeats 5
python3 "$here/singles.py" "$exe" "$out/singles" "$project/reports/evidence/stage-11b/panel"
python3 "$here/trials.py" "$exe" "$worker" "$sources" "$pilot" "$out/formal" --cases ticket56-reviewed --repeats 5
g++ -std=c++11 -O2 "$here/finite.cpp" -o "$out/build/finite"
python3 "$here/finite.py" "$out/build/finite" "$out/controls/finite"
g++ -std=c++11 -O2 "$here/rup_control.cpp" -o "$out/build/rup-control"
"$out/build/rup-control" > "$out/controls/rup-control.log"
mkdir -p "$out/controls/assumptions" "$out/controls/ranks"
"$worker" --controls "$out/controls/assumptions" > "$out/controls/assumptions/stdout"
for name in shared fresh; do for i in {0..6}; do mkdir -p "$out/controls/ranks/$name-$i"; done; done
mkdir -p "$out/controls/ranks/direction-0" "$out/controls/ranks/direction-1"
"$worker" --same-graph "$out/formal/batch_retained/1/F/old" "$out/controls/ranks" > "$out/controls/ranks/stdout"
python3 "$here/negative.py" "$out"
mkdir -p "$out/rebuild"
bash "$here/build.sh" "$tree" "$out/rebuild" > "$out/rebuild/build.log" 2>&1
python3 "$here/rebuild_check.py" "$out" "$out/rebuild"
mkdir -p "$out/audit-build"
bash "$here/build.sh" "$tree" "$out/audit-build" --audit > "$out/audit-build/build.log" 2>&1
python3 "$here/audit_proofs.py" replay "$out" "$out/audit-build" "$out/export"
python3 "$here/extra.py" "$out" "$project"
python3 "$here/multiquery.py" "$out" "$pilot" "$out/arithmetic-work"
python3 "$here/weak_controls.py" "$project/reports/evidence/stage-11b/panel" "$out/export/weak-sc.json"
python3 "$here/archive_results.py" "$out" "$project" "$out/export"
python3 "$here/summarize.py" "$out/export"
