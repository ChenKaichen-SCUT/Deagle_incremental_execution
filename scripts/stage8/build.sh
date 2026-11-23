#!/usr/bin/env bash
# Each input is a dedicated Git worktree of the pinned native implementation.
set -euo pipefail
project="$(cd "$(dirname "$0")/../.." && pwd)"
base="$(realpath "$1")"
enh="$(realpath "$2")"
out="$(realpath -m "$3")"
mkdir -p "$out"
cd "$project"
for role in baseline enhanced; do
  if [[ "$role" == baseline ]]; then tree="$base"; expected=a159f9923722646185ba8028610b2eef2618fa72
  else tree="$enh"; expected=0be9e2167d46c66ea12ca7f9f801063a03873625; fi
  [[ "$(git -C "$tree" branch --show-current)" == "stage8-$role-diag" ]]
  if [[ "$(git -C "$tree" rev-parse HEAD)" == "$expected" ]]; then
    git -C "$tree" diff --quiet HEAD --
    python3 -B scripts/stage8/instrument.py "$tree" "$role"
    git -C "$tree" add -u
    git -C "$tree" add src/util/stage8_meter.h
    GIT_AUTHOR_DATE=2026-11-23T00:00:00Z GIT_COMMITTER_DATE=2026-11-23T00:00:00Z \
      git -C "$tree" -c user.name=Stage8 -c user.email=stage8@localhost commit -q -m "Stage 8 $role diagnostics"
  fi
  [[ "$(git -C "$tree" rev-parse HEAD^)" == "$expected" ]]
  git -C "$tree" diff --quiet HEAD --
  git -C "$tree" diff --binary HEAD^ HEAD > "$out/$role.patch"
  export CCACHE_BASEDIR="$tree" PATH="/usr/lib/ccache:$PATH"
  make -C "$tree/src" -j4 cbmc.dir > "$out/$role-build.log" 2>&1 || { tail -35 "$out/$role-build.log"; exit 1; }
  sha256sum "$tree/src/cbmc/deagle_exe" "$tree/src/config.inc" "$out/$role.patch"
done
python3 -B - "$base" "$enh" "$out" <<'PY'
import hashlib,json,subprocess,sys
from pathlib import Path
base,enh,out=map(Path,sys.argv[1:])
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
lock={}
for tag,t in [('baseline',base),('development',enh)]:
    lock[tag+'_commit']=subprocess.check_output(['git','-C',t,'rev-parse','HEAD'],text=True).strip()
    lock[tag+'_sha256']=sha(t/'src/cbmc/deagle_exe')
    lock[tag+'_parent']=subprocess.check_output(['git','-C',t,'rev-parse','HEAD^'],text=True).strip()
    lock[tag+'_config']=sha(t/'src/config.inc')
    lock[tag+'_binary']=str(t/'src/cbmc/deagle_exe')
(out/'lock.json').write_text(json.dumps(lock,indent=2)+'\n')
PY
