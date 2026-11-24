#!/usr/bin/env bash
# The frozen observer writes /visits.json when a caller leaves its directory unset.
# Provide a disposable, user-owned / while preserving the user's project and input paths.
set -euo pipefail
exec bwrap --die-with-parent --unshare-user --unshare-pid --unshare-net \
  --tmpfs / --ro-bind /usr /usr --ro-bind /etc /etc --ro-bind /sys /sys \
  --symlink usr/bin /bin --symlink usr/sbin /sbin --symlink usr/lib /lib \
  --symlink usr/lib64 /lib64 --proc /proc --dev /dev \
  --bind /home /home --bind /mnt /mnt --bind /tmp /tmp --chdir "$PWD" -- "$@"
