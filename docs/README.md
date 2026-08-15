# Documentation Index

This folder contains the handoff documentation for the AI Tutor project.

## Recommended Reading Order

1. [Handoff Overview](HANDOFF_OVERVIEW.md)
2. [Deployment Guide](DEPLOYMENT.md)
3. [Admin Operations Guide](ADMIN_OPERATIONS.md)
4. [User Manual](USER_MANUAL.md)
5. [Known Limitations](KNOWN_LIMITATIONS.md)

## Implementation Details

Deeper notes on individual subsystems, for developers changing them:

- [Progress Tracker](ImplementationDetails/PROGRESS_TRACKER_IMPLEMENTATION.md) — how the 70/30 completion percentage is calculated and cached.

## Audience Guide

- Sponsors and technical reviewers should start with the handoff overview.
- Developers and operators should use the deployment and admin guides.
- Client users should use the user manual.
- Teams managing local model configuration should use the configuration section of the deployment guide, which covers `LLM_MODULE` and `LANGUAGE_MODEL_ID`.
