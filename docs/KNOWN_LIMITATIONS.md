# Known Limitations

## Overview

This project is functional as a prototype, but several current implementation choices should be understood before sponsor handoff or pilot deployment.

## Architecture and Deployment Limits

- The primary deployment guidance is Linux-oriented, while parts of the repository assume Windows tooling.
- The root repository layout is ambiguous because it contains both the Django app and a separate Windows desktop utility.
- The default database is SQLite, which is simple for prototypes but limited for larger concurrent deployments.
- The included deployment process starts Gunicorn directly and does not include a full service-management or reverse-proxy setup.

## Security and Configuration Limits

- `ALLOWED_HOSTS` is currently permissive.
- Password reset email uses Django's console email backend by default.
- Environment and secret management are not fully documented in the original repository materials.
- Production-hardening guidance is not encoded directly into the application configuration.

## Model and AI Runtime Limits

- The project includes heavy local-model dependencies and likely requires environment-specific runtime validation.
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

- Deployable application vs auxiliary tooling
- Sponsor context vs operator instructions
- Admin workflows vs end-user workflows

This handoff package addresses that gap, but ongoing updates should track the codebase as features evolve.
