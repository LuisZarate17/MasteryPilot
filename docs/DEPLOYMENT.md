# Deployment Guide

## Overview

The main deployable application in this repository is the Django project in `code/llmsite`. The included `setup.sh` script is the closest thing to an operational reference deployment. It creates a virtual environment, installs requirements, creates an environment file, runs migrations, and starts Gunicorn.

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
- Python dependency list: `requirements.txt`

## Prerequisites

### Operating system

The included setup script is Bash-based and assumes Linux. If you deploy on Windows, you will need an equivalent process for virtual environment setup, dependency install, migration, and process management.

### Required software

- Python 3.13 or compatible environment approved by the deployment team
- `pip`
- Bash shell if using `setup.sh`
- Network access to required package indexes
- Sufficient disk and memory for the chosen model backend

### Python dependencies

The project currently depends on:

- Django
- Gunicorn
- PyPDF2
- python-dotenv
- httpx
- numpy
- torch
- transformers
- sentence-transformers
- faiss-cpu
- google-generativeai
- accelerate

The local-model stack is substantially heavier than the quick-start instructions in the root `README.md` imply.

## Configuration

### Django settings highlights

Current settings in `code/llmsite/llmsite/settings.py` include:

- `DEBUG = False`
- `ALLOWED_HOSTS = ["*"]`
- SQLite database at `BASE_DIR / "db.sqlite3"`
- `STATIC_ROOT = BASE_DIR / "staticfiles"`
- `CURRICULUM_ROOT = BASE_DIR / "curriculum"`
- `GEMINI_ENABLED = False`
- `LLM_MODULE = "qwen"`

### Required environment values

At minimum, deployments should define:

- `DJANGO_SECRET_KEY`

Depending on model strategy, operators may also need:

- `LANGUAGE_MODEL_ID`
- `GEMINI_API_KEY`

### Environment file handling

`setup.sh` writes an environment file to `/etc/llmsite/llmsite.env` containing:

- `DJANGO_SETTINGS_MODULE`
- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`

If you rely on local-model or Gemini settings, extend the environment strategy accordingly.

## Standard Linux Deployment Flow

1. Clone the repository onto the target host.
2. Confirm the Django project exists at `code/llmsite/manage.py`.
3. Create a virtual environment.
4. Install `requirements.txt`.
5. Create a secure environment file.
6. Run Django migrations.
7. Start Gunicorn from `code/llmsite`.
8. Confirm the service is reachable on the intended host and port.

## Reference Process from setup.sh

The repository script performs these actions:

1. Uses repository-root `.venv`.
2. Installs dependencies from `requirements.txt`.
3. Generates a secret key if missing.
4. Loads environment variables from `/etc/llmsite/llmsite.env`.
5. Runs `python manage.py migrate --noinput`.
6. Starts Gunicorn bound to `0.0.0.0:8000`.

## Recommended Production Hardening Before External Use

### Infrastructure

- Replace SQLite if concurrent multi-user load or operational resilience matters.
- Add a process supervisor such as `systemd`.
- Add a reverse proxy such as Nginx or Apache.
- Terminate TLS at the proxy layer.

### Security

- Replace `ALLOWED_HOSTS = ["*"]` with explicit hostnames.
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
