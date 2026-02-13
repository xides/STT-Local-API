#!/usr/bin/env bash
set -euo pipefail

# Instala dependencias de sistema para Rocky Linux 10.x
# Uso:
#   ./setup_rocky10.sh

if [[ "${EUID}" -ne 0 ]]; then
  if ! command -v sudo >/dev/null 2>&1; then
    echo "Este script requiere root o sudo."
    exit 1
  fi
  exec sudo -E bash "$0" "$@"
fi

dnf -y update
dnf -y install dnf-plugins-core curl ca-certificates
dnf config-manager --set-enabled crb || true
dnf -y install epel-release

RPMFUSION_RPM="/tmp/rpmfusion-free-release-10.noarch.rpm"
curl -fsSL -o "${RPMFUSION_RPM}" "https://download1.rpmfusion.org/free/el/rpmfusion-free-release-10.noarch.rpm"
rpm -Uvh "${RPMFUSION_RPM}" || true
rm -f "${RPMFUSION_RPM}"

dnf -y install python3 python3-pip python3-devel gcc gcc-c++ make
dnf -y install ffmpeg || dnf -y install --nobest ffmpeg

dnf clean all
rm -rf /var/cache/dnf

echo "Dependencias de Rocky Linux 10 instaladas."
echo "Siguiente paso:"
echo "  python3 -m venv .venv && source .venv/bin/activate && pip install -U pip && pip install -r requirements.txt"
