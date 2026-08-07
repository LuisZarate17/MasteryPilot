#!/usr/bin/env bash
#
# MasteryPilot setup — creates a virtualenv, installs dependencies, writes a
# .env if there isn't one, and runs migrations.
#
#   ./setup.sh            install and migrate, then print how to start the server
#   ./setup.sh --serve    the above, then start gunicorn in the foreground
#
# No root required. Everything is written inside the repository.
#
# Override the interpreter if python3 is not on PATH:
#
#   PYTHON_BIN=/usr/bin/python3.13 ./setup.sh
#
set -euo pipefail

### ===== CONFIG =====
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="${APP_DIR}/.venv"
PROJECT_DIR="${APP_DIR}/code/llmsite"

# Django reads this exact path at startup (load_dotenv in llmsite/settings.py),
# so every later `manage.py` command picks it up too — not just this script.
ENV_FILE="${APP_DIR}/.env"

PYTHON_BIN="${PYTHON_BIN:-python3}"

WSGI_MODULE="llmsite.wsgi:application"

# Hostnames Django will answer to. Add the server's LAN IP or DNS name here;
# requests arriving with any other Host header are rejected.
ALLOWED_HOSTS_VALUE="localhost,127.0.0.1"

BIND_HOST="0.0.0.0"
BIND_PORT="8000"
WORKERS="1"
TIMEOUT="300"
### ==================

SERVE=0
for arg in "$@"; do
  case "$arg" in
    --serve) SERVE=1 ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)"; exit 1 ;;
  esac
done

echo_step() { echo; echo "==> $1"; }

if [[ ! -f "${PROJECT_DIR}/manage.py" ]]; then
  echo "Could not find Django project at: ${PROJECT_DIR}"
  exit 1
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Python interpreter not found: ${PYTHON_BIN}"
  echo "Install Python 3.13, or point PYTHON_BIN at it:"
  echo "  PYTHON_BIN=/path/to/python3 ./setup.sh"
  exit 1
fi

echo_step "Create venv and install requirements.txt"
"${PYTHON_BIN}" -m venv "${VENV_DIR}"

# Windows venvs put executables in Scripts/ rather than bin/.
if [[ -d "${VENV_DIR}/Scripts" ]]; then
  VENV_BIN="${VENV_DIR}/Scripts"
else
  VENV_BIN="${VENV_DIR}/bin"
fi

"${VENV_BIN}/python" -m pip install --upgrade pip wheel
"${VENV_BIN}/python" -m pip install -r "${APP_DIR}/requirements.txt"

echo_step "Create ${ENV_FILE} and generate SECRET_KEY (if missing)"

if [[ ! -f "${ENV_FILE}" ]]; then
  # Formula name: secrets.token_hex
  # Formula: token_hex(nbytes)
  # Inputs: nbytes = 32
  SECRET_KEY="$("${VENV_BIN}/python" -c 'import secrets; print(secrets.token_hex(32))')"

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
DJANGO_SECRET_KEY=${SECRET_KEY}
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=${ALLOWED_HOSTS_VALUE}
# This script serves plain HTTP, so Secure cookies are off: turning them on
# without TLS stops the browser sending the CSRF token and breaks login.
# Set to 1 once you put a TLS-terminating proxy in front of gunicorn.
DJANGO_SECURE_COOKIES=0
ADMIN_PASS=${ADMIN_PASS}
# Username defaults to "admin". Leave these commented unless you want
# something else: migration tutor/0002 treats ADMIN_USER or ADMIN_EMAIL set
# without ADMIN_PASS as a half-finished configuration and refuses to run.
# ADMIN_USER=admin
# ADMIN_EMAIL=
# GEMINI_API_KEY=
EOF

  # No-op on Windows/Git Bash, where chmod does not map onto NTFS ACLs.
  chmod 600 "${ENV_FILE}"
  echo "Wrote ${ENV_FILE}"
else
  echo "Env file exists, leaving as-is: ${ENV_FILE}"
fi

echo_step "Run migrations"
# Django loads ${ENV_FILE} itself, so nothing needs exporting here. Read
# ADMIN_PASS back out only to decide whether to print the notice below.
ADMIN_PASS="$(sed -n 's/^ADMIN_PASS=//p' "${ENV_FILE}" | head -n 1)"
"${VENV_BIN}/python" "${PROJECT_DIR}/manage.py" migrate --noinput

if [[ -z "${ADMIN_PASS:-}" ]]; then
  echo
  echo "NOTE: no admin account was created (ADMIN_PASS is empty)."
  echo "To create one, set ADMIN_PASS in ${ENV_FILE}, then replay the"
  echo "account migration (its reverse is a no-op, so this is safe):"
  echo "  ${VENV_BIN}/python ${PROJECT_DIR}/manage.py migrate tutor 0001"
  echo "  ${VENV_BIN}/python ${PROJECT_DIR}/manage.py migrate tutor"
fi

echo
echo "The tutor itself needs the local-inference stack, which this script does"
echo "not install (several GB). To enable chat:"
echo "  ${VENV_BIN}/python -m pip install -r ${APP_DIR}/requirements-llm.txt"

if [[ "${SERVE}" -eq 0 ]]; then
  echo
  echo "Setup complete. To start the server:"
  echo
  echo "  production (this script):"
  echo "    ./setup.sh --serve"
  echo
  echo "  development (auto-reload, serves static files; set DJANGO_DEBUG=1 in ${ENV_FILE}):"
  echo "    ${VENV_BIN}/python ${PROJECT_DIR}/manage.py runserver"
  echo
  exit 0
fi

echo_step "Start server (gunicorn, foreground)"
echo "Binding: ${BIND_HOST}:${BIND_PORT}"
echo "Open from LAN: http://<SERVER_LAN_IP>:${BIND_PORT}"
exec "${VENV_BIN}/gunicorn" "${WSGI_MODULE}" \
  --chdir "${PROJECT_DIR}" \
  --bind "${BIND_HOST}:${BIND_PORT}" \
  --workers "${WORKERS}" \
  --timeout "${TIMEOUT}"
