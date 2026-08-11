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
- No model has been run against real weights on the development machine, for any of the three families. There is no GPU and `requirements-llm.txt` is not installed, so the generation path is reviewed rather than exercised. The test suite covers it against a fake adapter, which is deliberate — the suite must stay fast and GPU-free — but 400+ passing tests say nothing about a model emitting a token.
- LLaMA is driven through a hand-written chat template rather than the one its tokenizer provides.
- Inference is local-only. There is no hosted-API fallback, so a machine without a suitable GPU cannot answer chats.

## Retrieval Limits

- **Retrieval quality has never been measured on this machine.** `manage.py rag_eval` scores a labelled query set for recall, MRR and rejection accuracy, but it needs a real embedding model. Run the `rag-verify` GitHub Actions workflow (dispatch-only) to get numbers; until then, retrieval is reviewed and unit-tested, not measured.
- The score floor that decides whether a question has an answer at all (`MIN_SCORE`) is the one value in the retrieval path that genuinely requires a calibrated model, and it has not had one. Everything downstream of it uses a relative cutoff instead, so being miscalibrated degrades the rejection of off-topic questions rather than the ranking of good ones.
- Chunk size is set from the embedding model's context window rather than from measurement. `rag_eval --chunk-size` exists to settle it against real numbers.
- Index invalidation is per process. Deleting curriculum takes effect immediately for the worker that handled the request, and at the next chat-session start for the others. Under a single worker — the default — this is not observable.
- A curriculum change rebuilds the whole index rather than removing individual entries. This is deliberate: incremental removal requires renumbering FAISS ids in step with a parallel metadata list, and a mismatch there misattributes passages silently. Rebuilding a pilot-sized corpus takes seconds.
- Retrieval is exact search up to 20,000 chunks and approximate above it. The approximate path has never run.

## Product and UX Limits

- Some user interface content remains placeholder-oriented, especially in the chat sidebar notes/resources area.
- Progress indicators are derived metrics and should not be treated as formal academic records.
- Intervention status is based on simple quiz thresholds rather than a broader student-support model.
- Curriculum upload supports TXT, Markdown, JSON, PDF and DOCX.
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
