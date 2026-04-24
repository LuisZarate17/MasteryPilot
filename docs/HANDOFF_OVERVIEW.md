# Sponsor Handoff Overview

## Purpose

This repository contains an AI tutoring prototype intended for use by school districts or similar education stakeholders. The current system supports student tutoring workflows, role-based dashboards for staff, quiz generation and grading, progress tracking, curriculum document upload, and chat export for review.

## Primary Product Components

### 1. Django web application

The main product surface is the Django application under `code/llmsite`. It provides:

- Student signup, login, password reset, landing page, progress page, and tutor chat.
- Teacher and admin dashboards.
- Curriculum file upload, viewing, and deletion.
- Session history, session rename/delete, quiz grading, and chat export.

Relevant code entry points:

- `code/llmsite/manage.py`
- `code/llmsite/llmsite/settings.py`
- `code/llmsite/tutor/urls.py`
- `code/llmsite/tutor/views.py`
- `code/llmsite/tutor/models.py`

### 2. Windows model selector utility

The repository also includes a separate Windows Forms application under `model_selector_app/ModelSelector/ModelSelector`. This utility scrapes Hugging Face model listings and writes a `LANGUAGE_MODEL_ID` value into a selected `.env` file. It is not part of the web user interface, but it is relevant for local-model configuration workflows.

### 3. Historical project material

The `docs/Reports`, `docs/Presentations`, and `docs/MoM` folders contain sprint reports, presentation artifacts, and meeting minutes. These are useful for project history, but they should not be treated as the operational handoff set.

## Intended User Roles

The Django application implements three practical roles:

- Students: use chat, quizzes, progress tracking, and session history.
- Teachers/mentors: view assigned students, monitor progress, review chat history, upload curriculum, and export student data for authorized students.
- Admins: manage all users, assign teachers, manage curriculum files, and export chat data.

Role behavior is implemented in custom profile models:

- `TeacherProfile`
- `StudentProfile`
- `AdminProfile`
- `StudentProgress`

## Current Feature Summary

### Student-facing

- Account signup and authentication.
- AI tutor chat sessions with session list, rename, and delete.
- Quiz rendering and grading flow.
- Landing page with progress summary.
- Detailed progress page and session history.
- Password reset flow.

### Staff-facing

- Dashboard with student list.
- Intervention list based on quiz average thresholds.
- Curriculum upload and viewing.
- Curriculum deletion for admins.
- Account creation and deletion.
- Student editing for classes and teacher assignment.
- Chat export in CSV or JSON.

### Operational

- SQLite-backed persistence for users, sessions, chats, quizzes, and progress.
- Management commands for student import and progress refresh.
- Linux-oriented deployment script using Gunicorn.

## Deployment Target Assumption

The current repository most directly supports a single-server deployment of the Django web application. The included `setup.sh` script assumes:

- Linux host
- Python virtual environment
- Gunicorn process
- SQLite database
- Local or externally available model/runtime dependencies

This is suitable for a prototype or limited pilot, not a hardened production rollout without further infrastructure work.

## Scope Clarification for Sponsor Handoff

The handoff package should clearly distinguish:

- Main deployable system: `code/llmsite`
- Auxiliary desktop utility: `model_selector_app`
- Historical artifacts: sprint reports and presentations

This matters because the root `README.md` currently mixes setup guidance and does not clearly separate the live application from auxiliary tooling or historical documents.

## Recommended Handoff Deliverables

- This overview document for sponsor context.
- A deployment guide for technical setup and operations.
- An admin operations guide for account and curriculum management.
- A user manual for student, teacher, and admin usage.
- A model selector guide for local model configuration workflows.
- A known limitations document for realistic transition planning.

## Suggested Sponsor Talking Points

- The project is functional as a prototype with real user-role workflows.
- The most mature surface is the Django web application.
- Deployment is feasible for pilot use, but current settings and storage choices are not fully production hardened.
- The desktop model selector is an operator utility, not a client-facing feature.
- Future hardening should focus on infrastructure, secrets handling, database strategy, and formal deployment ownership.
