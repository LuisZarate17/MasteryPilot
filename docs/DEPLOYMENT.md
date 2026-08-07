# Deployment Guide

## Overview

The main deployable application in this repository is the Django project in `code/llmsite`. The included `setup.sh` script is the closest thing to an operational reference deployment. It creates a virtual environment, installs the core requirements, writes a repository-root `.env` if one does not exist, and runs migrations. Passing `--serve` also starts Gunicorn in the foreground. It requires no root and writes nothing outside the repository.

## Deployment Scope

This guide covers the Django web application only. It does not deploy the Windows model selector utility.

## Runtime Components

- Python application server: Django
- WSGI server: Gunicorn
- Database: SQLite
- Authentication: Django auth system
- File storage: local filesystem for curriculum documents
- Model backends:
  - Local model mode via `LLM_MODULE`
  - Optional Gemini-based mode in legacy code paths

## Important Repository Paths

- Application root: `code/llmsite`
- Django settings: `code/llmsite/llmsite/settings.py`
- Main app: `code/llmsite/tutor`
- Deployment script: `setup.sh`
- Core Python dependency list: `requirements.txt`
- Local inference / RAG dependency list: `requirements-llm.txt`
- Environment file: `.env` in the repository root

## Prerequisites

### Operating system

The included setup script is Bash-based and assumes Linux. If you deploy on Windows, follow the Quick start in the root `README.md` — the same virtualenv, install, migrate, and `runserver` sequence, run by hand. Gunicorn does not run on Windows; use a Windows-capable WSGI server such as Waitress for anything beyond development.

### Required software

- Python 3.13 or compatible environment approved by the deployment team
- `pip`
- Bash shell if using `setup.sh`
- Network access to required package indexes
- Sufficient disk and memory for the chosen model backend

### Python dependencies

Dependencies are split across two files, because the two halves differ by three orders of magnitude in size.

`requirements.txt` — everything needed to install, migrate, run the test suite, and serve pages. A few megabytes.

- Django
- Gunicorn
- python-dotenv

`requirements-llm.txt` — the local inference and RAG stack, roughly 3–5 GB. Every package here is imported lazily, the first time a chat starts, so the site installs and runs without it; only tutor responses fail.

- numpy
- PyPDF2
- faiss-cpu
- sentence-transformers
- torch
- transformers
- accelerate
- bitsandbytes
- google-generativeai

Both files are exact-pinned. `requirements-llm.txt` documents a CUDA 11.8 install path for NVIDIA hosts; the default resolves CPU-only wheels. Deployments that will not use a local model can skip the second file entirely.

## Configuration

### Django settings highlights

Current settings in `code/llmsite/llmsite/settings.py` include:

- `DEBUG` — from `DJANGO_DEBUG`, defaults to `False`
- `ALLOWED_HOSTS` — from `DJANGO_ALLOWED_HOSTS`, defaults to `localhost,127.0.0.1`
- SQLite database at `BASE_DIR / "db.sqlite3"`
- `STATIC_ROOT = BASE_DIR / "staticfiles"`
- `CURRICULUM_ROOT = BASE_DIR / "curriculum"`
- `GEMINI_ENABLED = False`
- `LLM_MODULE = "qwen"`

### Required environment values

`.env.example` in the repository root is the authoritative list. At minimum, deployments must define:

- `DJANGO_SECRET_KEY` — the application raises `ImproperlyConfigured` at startup without it whenever `DJANGO_DEBUG` is off. There is no production fallback.
- `ADMIN_PASS` — the password for the initial administrator account, read once by migration `tutor/0002`. There is no default password; if this is unset, no admin account is created.

Recommended:

- `DJANGO_ALLOWED_HOSTS` — add the server's LAN IP or DNS name.
- `DJANGO_SECURE_COOKIES` — `1` behind TLS, `0` on plain HTTP. Session and CSRF cookies are marked Secure when on; leaving it on without TLS prevents the browser from sending the CSRF token and breaks login.
- `DJANGO_SECURE_SSL_REDIRECT` — `1` to redirect HTTP to HTTPS. Off by default and deliberately independent of the setting above, because enabling it without TLS makes the site unreachable. If you terminate TLS at a proxy, set `DJANGO_TRUST_PROXY_SSL_HEADER=1` at the same time or the redirect will loop indefinitely. The `setup.sh` deployment serves plain HTTP with no proxy, so both stay off there.

Depending on model strategy, operators may also need:

- `LANGUAGE_MODEL_ID`
- `GEMINI_API_KEY`

### Environment file handling

Django loads a `.env` file from the repository root at startup (`load_dotenv` in `settings.py`). That is the only configuration file it reads.

`setup.sh` writes that same file (mode 600) on first run, containing `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_SECURE_COOKIES`, `ADMIN_USER`, `ADMIN_EMAIL`, and `ADMIN_PASS`. It generates the secret key and prompts for the admin password. If `.env` already exists the script leaves it untouched, so re-running setup never clobbers a configured deployment.

Because Django reads the file itself, no environment exporting is required: any later `manage.py` command picks up the same configuration, whether or not it was launched by the script.

Note that this file contains the admin password in plaintext. Keep its 600 permissions, and consider clearing `ADMIN_PASS` from it once the account exists — it is only read while the account migration runs.

For a hardened deployment, keep secrets out of the working tree entirely: place them somewhere like `/etc/llmsite/llmsite.env`, owned by the service account and mode 600, and export them into the process environment through your supervisor (a systemd unit's `EnvironmentFile=`, for example). Django reads real environment variables in preference to anything in `.env`, so this requires no code change — but it does mean the repository `.env` must not also carry stale values.

## Standard Linux Deployment Flow

1. Clone the repository onto the target host.
2. Confirm the Django project exists at `code/llmsite/manage.py`.
3. Create a virtual environment.
4. Install `requirements.txt`.
5. Create a secure `.env` in the repository root.
6. Run Django migrations.
7. Install `requirements-llm.txt` if the deployment will serve tutor responses.
8. Start Gunicorn from `code/llmsite`.
9. Confirm the service is reachable on the intended host and port.

`./setup.sh --serve` performs steps 3 through 6 and 8.

## Reference Process from setup.sh

The repository script performs these actions:

1. Uses repository-root `.venv`.
2. Installs dependencies from `requirements.txt`.
3. Writes repository-root `.env` if absent, generating a secret key and prompting for the admin password.
4. Runs `python manage.py migrate --noinput`.
5. With `--serve`, starts Gunicorn bound to `0.0.0.0:8000`. Without it, prints how to start the server and exits.

It does not install `requirements-llm.txt`; it prints the command instead.

`PYTHON_BIN` overrides the interpreter if `python3` is not on `PATH`.

## Recommended Production Hardening Before External Use

### Infrastructure

- Replace SQLite if concurrent multi-user load or operational resilience matters.
- Add a process supervisor such as `systemd`.
- Add a reverse proxy such as Nginx or Apache.
- Terminate TLS at the proxy layer.

### Security

- Set `DJANGO_ALLOWED_HOSTS` to the explicit hostnames the site answers to; the default covers localhost only.
- Review `CSRF_COOKIE_SECURE`, session cookie policy, and HTTPS enforcement together.
- Ensure secrets are stored outside the repository and rotated if exposed.
- Replace console email backend for real password reset delivery.

### Static and file handling

- Run `collectstatic` as part of deployment if static files are served conventionally.
- Back up curriculum uploads if they are operationally important.
- Define retention and access policy for exported chat files.

### Model/runtime planning

- Validate whether deployment will use a local model or Gemini.
- Document hardware expectations for local model execution.
- Confirm all required model assets are available in the deployment environment.

## Verification Checklist

- App starts without import errors.
- Login page loads.
- Student user can sign in and open chat.
- Session creation works.
- Quiz generation and grading path works.
- Teacher/admin dashboard loads.
- Curriculum upload works for approved file types.
- Chat export produces CSV and JSON files.
- Password reset flow behaves as expected for the selected email backend.

## Troubleshooting

### App does not start

- Check Python version and installed packages.
- Confirm the working directory is `code/llmsite` when running Django commands.
- Verify `DJANGO_SECRET_KEY` is set.

### Chat or model responses fail

- Confirm whether the system is configured for local models or Gemini.
- Check that the selected `LLM_MODULE` is supported.
- Confirm model dependencies are installed and reachable.

### Password reset appears to do nothing

- The current email backend is console-based.
- In production, use a real SMTP or transactional email provider.

### Curriculum operations fail

- Confirm the process has write permission to `CURRICULUM_ROOT`.
- Validate uploaded files are TXT or PDF and within configured size limits.

## Operational Ownership Questions for Handoff

These should be resolved with the sponsor before production-like use:

- Who owns server hosting and monitoring?
- Who manages secrets and credential rotation?
- Who approves model changes?
- Who retains exported chat data and for how long?
- Who supports account creation and password recovery?
