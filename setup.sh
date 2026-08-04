#!/usr/bin/env bash
set -euo pipefail

### ===== CONFIG (matches your project) =====
APP_NAME="llmsite"
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="${APP_DIR}/.venv"
PROJECT_DIR="${APP_DIR}/code/llmsite"

ENV_DIR="/etc/${APP_NAME}"
ENV_FILE="${ENV_DIR}/${APP_NAME}.env"

DJANGO_SETTINGS_MODULE_VALUE="llmsite.settings"
WSGI_MODULE="llmsite.wsgi:application"

# Hostnames Django will answer to. Add the server's LAN IP or DNS name here;
# requests arriving with any other Host header are rejected.
ALLOWED_HOSTS_VALUE="localhost,127.0.0.1"

BIND_HOST="0.0.0.0"
BIND_PORT="8000"
WORKERS="1"
TIMEOUT="300"
### =======================================

need_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Run as root: sudo ./setup.sh"
    exit 1
  fi
}

echo_step() { echo; echo "==> $1"; }

need_root

if [[ ! -f "${PROJECT_DIR}/manage.py" ]]; then
  echo "Could not find Django project at: ${PROJECT_DIR}"
  exit 1
fi

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

  # Password for the initial admin account. There is no default: if this stays
  # empty, the migration creates no account at all (see .env.example).
  ADMIN_PASS=""
  if [[ -t 0 ]]; then
    echo
    echo "Choose a password for the initial admin account (blank to skip)."
    read -rsp "ADMIN_PASS: " ADMIN_PASS
    echo
  fi

  cat > "${ENV_FILE}" <<EOF
DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE_VALUE}
DJANGO_SECRET_KEY=${SECRET_KEY}
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=${ALLOWED_HOSTS_VALUE}
# This script serves plain HTTP, so Secure cookies are off: turning them on
# without TLS stops the browser sending the CSRF token and breaks login.
# Set to 1 once you put a TLS-terminating proxy in front of gunicorn.
DJANGO_SECURE_COOKIES=0
ADMIN_USER=admin
ADMIN_EMAIL=
ADMIN_PASS=${ADMIN_PASS}
# GEMINI_API_KEY=
EOF

  chmod 600 "${ENV_FILE}"
  echo "Wrote ${ENV_FILE}"
else
  echo "Env file exists, leaving as-is: ${ENV_FILE}"
fi

echo_step "Load env vars for this run"
# set -a exports everything sourced below, so the migrate and gunicorn child
# processes actually see these values. Without it they are shell-local and
# Django silently falls back to its development defaults.
set +u
set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a
set -u

echo_step "Run migrations"
"${VENV_DIR}/bin/python" "${PROJECT_DIR}/manage.py" migrate --noinput

if [[ -z "${ADMIN_PASS:-}" ]]; then
  echo
  echo "NOTE: no admin account was created (ADMIN_PASS is empty)."
  echo "To create one, set ADMIN_PASS in ${ENV_FILE}, then replay the"
  echo "account migration (its reverse is a no-op, so this is safe):"
  echo "  set -a; source ${ENV_FILE}; set +a"
  echo "  ${VENV_DIR}/bin/python ${PROJECT_DIR}/manage.py migrate tutor 0001"
  echo "  ${VENV_DIR}/bin/python ${PROJECT_DIR}/manage.py migrate tutor"
fi

echo_step "Start server (gunicorn, foreground)"
echo "Binding: ${BIND_HOST}:${BIND_PORT}"
echo "Open from LAN: http://<SERVER_LAN_IP>:${BIND_PORT}"
exec "${VENV_DIR}/bin/gunicorn" "${WSGI_MODULE}" \
  --chdir "${PROJECT_DIR}" \
  --bind "${BIND_HOST}:${BIND_PORT}" \
  --workers "${WORKERS}" \
  --timeout "${TIMEOUT}"
