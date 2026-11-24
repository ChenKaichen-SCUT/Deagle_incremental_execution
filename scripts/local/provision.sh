#!/usr/bin/env bash
# Install build and verification prerequisites in the dedicated local Jammy distribution.
set -euo pipefail
source /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 22.04 && $(id -u) == 0 ]]
export DEBIAN_FRONTEND=noninteractive
apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=18 -o Acquire::https::Timeout=18 update
apt-get -y --no-install-recommends -o Acquire::Retries=2 install \
  build-essential gcc-multilib g++-multilib git cmake flex bison zlib1g-dev \
  libgoogle-perftools-dev libgmp-dev ccache ca-certificates curl file time \
  bubblewrap python3.10 python3.10-venv python3-yaml systemd systemd-sysv dbus libpam-systemd dbus-user-session
id deagle >/dev/null 2>&1 || useradd --create-home --shell /bin/bash deagle
# The original privileged mini controller reads these two locked, deagle-owned Git checkouts.
for checkout in /home/deagle/runtime/baseline /home/deagle/runtime/stage05; do
  if ! git config --system --get-all safe.directory | grep -Fxq "$checkout"; then
    git config --system --add safe.directory "$checkout"
  fi
done
if [[ ! -f /etc/wsl.conf ]]; then
  printf '[boot]\nsystemd=true\n[user]\ndefault=deagle\n' > /etc/wsl.conf
fi
getent passwd deagle
gcc -dumpfullversion
python3 --version
