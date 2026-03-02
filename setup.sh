#!/usr/bin/env bash
set -euo pipefail

### ===== CONFIG (matches your project) =====
APP_NAME="llmsite"
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="${APP_DIR}/.venv"

ENV_DIR="/etc/${APP_NAME}"
ENV_FILE="${ENV_DIR}/${APP_NAME}.env"

DJANGO_SETTINGS_MODULE_VALUE="llmsite.settings"
WSGI_MODULE="llmsite.wsgi:application"

BIND_HOST="0.0.0.0"
BIND_PORT="8000"
WORKERS="2"
TIMEOUT="60"
### =======================================

need_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Run as root: sudo ./deploy.sh"
    exit 1
  fi
}

echo_step() { echo; echo "==> $1"; }

need_root

echo_step "Create venv and install requirements.txt"
python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip wheel
"${VENV_DIR}/bin/pip" install -r "${APP_DIR}/requirements.txt"

echo_step "Install gunicorn (server runner)"
"${VENV_DIR}/bin/pip" install gunicorn

echo_step "Create env file and generate SECRET_KEY (if missing)"
mkdir -p "${ENV_DIR}"
chmod 755 "${ENV_DIR}"

if [[ ! -f "${ENV_FILE}" ]]; then
  # Formula name: secrets.token_hex
  # Formula: token_hex(nbytes)
  # Inputs: nbytes = 32
  SECRET_KEY="$("${VENV_DIR}/bin/python" -c 'import secrets; print(secrets.token_hex(32))')"

  cat > "${ENV_FILE}" <<EOF
DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE_VALUE}
DJANGO_SECRET_KEY=${SECRET_KEY}
DJANGO_DEBUG=0
EOF

  chmod 600 "${ENV_FILE}"
  echo "Wrote ${ENV_FILE}"
else
  echo "Env file exists, leaving as-is: ${ENV_FILE}"
fi

echo_step "Load env vars for this run"
set +u
# shellcheck disable=SC1090
source "${ENV_FILE}"
set -u

echo_step "Run migrations"
"${VENV_DIR}/bin/python" "${APP_DIR}/manage.py" migrate --noinput

echo_step "Start server (gunicorn, foreground)"
echo "Binding: ${BIND_HOST}:${BIND_PORT}"
echo "Open from LAN: http://<SERVER_LAN_IP>:${BIND_PORT}"
exec "${VENV_DIR}/bin/gunicorn" "${WSGI_MODULE}" \
  --bind "${BIND_HOST}:${BIND_PORT}" \
  --workers "${WORKERS}" \
  --timeout "${TIMEOUT}"