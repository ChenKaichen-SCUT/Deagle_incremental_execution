#!/bin/bash
set -eu
bin=/root/Deagle_incremental_execution/runs/stage-11b/native/src/cbmc/deagle_exe
if [ "$#" = 0 ]; then
  test -x "$bin"
  cp order.txt "order-$(sha256sum order.txt | cut -c1-12).txt"
  saved="order-$(sha256sum order.txt | cut -c1-12).txt"
  nohup bash dispatch.sh "$saved" > "$saved.log" 2>&1 < /dev/null &
  echo "submitted $saved pid $!"
  exit 0
fi
exec 9>queue.lock
flock 9
{ date -u; uname -a; lscpu; cat /proc/self/cgroup; free -b; df -B1 .; sha256sum "$bin"; gcc -dumpfullversion; python3 --version; } > "$1.host"
while read -r plan workers; do
  python3 -B run.py "$PWD" "$bin" "$plan.json" --host server-8core --workers "$workers"
done < "$1"
date -u > "$1.complete"
