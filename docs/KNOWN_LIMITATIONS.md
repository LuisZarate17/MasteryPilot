# Known Limitations

## Overview

This project is functional as a prototype, but several current implementation choices should be understood before sponsor handoff or pilot deployment.

## Architecture and Deployment Limits

- `setup.sh` and the Gunicorn serving path are Linux-only. Windows development is supported through `manage.py runserver`, which is not a production server.
- The default database is SQLite, which is simple for prototypes but limited for larger concurrent deployments.
- The included deployment process starts Gunicorn directly and does not include a full service-management or reverse-proxy setup.

## Security and Configuration Limits

- `ALLOWED_HOSTS` defaults to `localhost,127.0.0.1`. Operators must set `DJANGO_ALLOWED_HOSTS` before any other machine can reach the site, and a wrong value fails as a refused request rather than an obvious error.
- Password reset email uses Django's console email backend by default, so reset links are printed to the server log instead of being delivered.
- The transport-hardening switches exist and are documented (`DJANGO_SECURE_COOKIES`, `DJANGO_SECURE_SSL_REDIRECT`, `DJANGO_TRUST_PROXY_SSL_HEADER`), but no TLS terminator or reverse proxy ships with the project. Serving HTTPS is left to the deployer.

## Model and AI Runtime Limits

- Local inference dependencies are heavy — roughly 3-5 GB, mostly torch — and are split into `requirements-llm.txt`. The site installs, runs, and passes its tests without them, but the tutor cannot answer until they are installed.
- Only the Qwen path has been exercised end to end. Mistral and LLaMA share the same code path but have not been run against real weights.
- LLaMA is driven through a hand-written chat template rather than the one its tokenizer provides.
- Inference is local-only. There is no hosted-API fallback, so a machine without a suitable GPU cannot answer chats.

## Product and UX Limits

- Some user interface content remains placeholder-oriented, especially in the chat sidebar notes/resources area.
- Progress indicators are derived metrics and should not be treated as formal academic records.
- Intervention status is based on simple quiz thresholds rather than a broader student-support model.
- Curriculum upload supports only TXT and PDF files.
- The curriculum library UI does not show upload timestamps.

## Administrative Limits

- Bulk account management in the web UI is limited.
- Export is per student rather than bulk export by cohort, class, or date range.
- Operational auditing and reporting are limited.
- There is no dedicated admin manual in the original repo; this handoff set fills that gap.

## Documentation Limits Resolved by This Handoff Set

The original repository documentation did not adequately separate:

- Sponsor context vs operator instructions
- Admin workflows vs end-user workflows

This handoff package addresses that gap, but ongoing updates should track the codebase as features evolve.
