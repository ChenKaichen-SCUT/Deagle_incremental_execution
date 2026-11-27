#!/usr/bin/env bash
# OUT must be fresh. BASELINE_ROOT contains the frozen upstream, D1 observer and D4.1 reference products.
set -euo pipefail
tree=$(cd "$(dirname "$0")/../.." && pwd)
b=$(realpath "${BASELINE_ROOT:?directory containing stock-build, rebuild-d1 and runs}")
o=$(realpath -m "${1:?new output directory}")
mkdir "$o"
cd "$tree"; export PATH=/usr/bin:/bin LC_ALL=C
implementation=dae97a351932918b7f172e23e0d93d6e8688e552
git merge-base --is-ancestor "$implementation" HEAD
git diff --quiet "$implementation" -- src minisat-2.2.1 dependency-reuse/d4 dependency-reuse/configs/d42-plan.json
s=dependency-reuse/scripts
d41="$b/runs/d41"
make -C src -j8 cbmc.dir > "$o/build.log" 2>&1
bash "$s/build42.sh" "$tree" "$o/tools"
python3 "$s/identity42.py" "$d41/matrix" "$d41/final-audit" "$d41/tools" "$o/controls"
python3 "$s/fixed42.py" "$d41/release" "$d41/tools" "$o/historical"
bash dependency-reuse/tests/d41/build.sh "$tree" "$b/rebuild-d1/final" "$b/runs/d3/observer/ClosureSolver.o" "$o/tests"
bash dependency-reuse/tests/d42/check.sh "$tree" "$o/tools" "$o/tests" "$o/micro"
python3 "$s/encoding42.py" "$tree" "$b/runs/d3/observer" "$o/encoding"
python3 "$s/run_d42.py" functional "$tree/src/cbmc/deagle_exe" "$o/tools" "$o/functional" --encoding "$o/encoding/encoding.json"
full="$o/functional/fib_updates_8/1/reference/P0/native/proof.bin"
compact="$d41/matrix/fib_updates_8/compact/P0/native/proof.bin"
"$o/tests/triplet/check-slice" "$full" "$compact" > "$o/micro/compact-positive.log"
python3 dependency-reuse/tests/d41/compact.py "$o/tests/triplet/check-slice" "$full" "$compact" "$o/micro/compact-corruption"
python3 "$s/audit_d42.py" "$o/functional" "$d41/matrix" "$d41/final-audit" "$o/controls" "$o/historical" "$o/encoding/P0/manifest/work" "$o/tools" "$o/tests" "$o/micro" "$o/audit"
python3 "$s/clock42.py" "$b/runs/d4/stock-timer/deagle_exe" "$o/functional" "$o/clocks"
python3 "$s/run_d42.py" performance "$tree/src/cbmc/deagle_exe" "$o/tools" "$o/performance" --gate "$o/audit/gate.json" --encoding "$o/encoding/encoding.json"
for round in 2 3; do
    python3 "$s/clock42.py" "$b/runs/d4/stock-timer/deagle_exe" "$o/performance" "$o/clocks-$round" --round "$round"
done
python3 "$s/summarize42.py" "$o/functional" "$o/performance" "$o/audit" "$o/clocks" "$b/runs/d4/release-runs" "$o/report" --stock-clocks "$o/clocks-2" "$o/clocks-3"
python3 "$s/diagnose42.py" "$o/functional" "$o/retirement.json"
published="$o/published"
python3 "$s/report42.py" "$o" "$published" "$implementation" --summary report --audit audit --encoding encoding --micro micro
cp dependency-reuse/reports/D4.2-{theory,lightweight,mapping}.md "$published/"
raw="$published/evidence/d42/raw/release"
python3 "$s/d4_archive.py" pack "$raw" "functional=$o/functional" "performance=$o/performance" "audit=$o/audit" \
    "encoding=$o/encoding" "lifecycle=$o/micro" "stock-search-clock-1=$o/clocks" "stock-search-clock-2=$o/clocks-2" \
    "stock-search-clock-3=$o/clocks-3" "build.log=$o/build.log" \
    "controls=$o/controls" "historical-d41=$o/historical" "review=$o/report" "retirement.json=$o/retirement.json"
python3 "$s/seal42.py" "$published" "$implementation"
python3 "$s/check_d42.py" --reports "$published" --raw
