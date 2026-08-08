## MasteryPilot

> **Team capstone project** (WSU CPT_S 421/423). Built by [Zelefant](https://github.com/Zelefant),
> [Jesse Boakye](https://github.com/jesseboakye), and [Luis Zarate](https://github.com/LuisZarate17).
> This is Luis Zarate's fork of the team repository. Its history has been rewritten to strip
> large binaries — a screen recording, textbook PDFs, and dev database snapshots — so commit
> hashes here diverge from upstream.
> Canonical upstream: [Zelefant/MasteryPilot](https://github.com/Zelefant/MasteryPilot).

**Stack:** Python 3.13 · Django · SQLite · local LLM inference (Qwen3 / LLaMA / Mistral) · hybrid RAG retrieval

## Project summary

A system for school districts to create individual AI tutors for their students, following their own curriculums and learning paths with teacher guidance.

### Additional information about the project

This AI tutoring system enables school districts to offer personalized learning experiences by providing students with an interactive AI tutor that adapts to their curriculum and skill level. The tutor delivers step-by-step guidance, practice exercises, and quizzes, while teachers can monitor progress, track mastery, and receive alerts if a student struggles. Built for dynamic content generation and strict privacy safeguards, the system supports multiple subjects and student profiles and is designed to scale from individual classrooms to district-wide deployment, with future plans for local LLM usage and advanced analytics dashboards.

## Installation

### Prerequisites

- Python 3.10–3.13 (3.13 recommended; Django 5.2 does not support 3.14 yet)

The base install is small and takes seconds. The AI tutor needs a separate
multi-gigabyte model stack — see [Enabling the AI tutor](#enabling-the-ai-tutor).

### Quick start (development, any OS)

```
git clone https://github.com/LuisZarate17/MasteryPilot.git
cd MasteryPilot
```

Create a virtual environment and install the core dependencies:

```
python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

Create your configuration file:

```
cp .env.example .env
```

Open `.env` and set three things:

- `DJANGO_SECRET_KEY` — generate one with
  `python -c "import secrets; print(secrets.token_hex(32))"`
- `DJANGO_DEBUG=1` — required for local development, otherwise `runserver`
  does not serve static files and the site renders without CSS
- `ADMIN_PASS` — the password for the first administrator account

Then create the database and start the server:

```
cd code/llmsite
python manage.py migrate
python manage.py runserver
```

Open <http://127.0.0.1:8000/> and sign in as `admin` with the password you set.

### Server deploy (Linux)

`setup.sh` does the same work non-interactively — virtualenv, dependencies,
generated `.env`, migrations — and can start Gunicorn. It needs no root and
writes only inside the repository.

```
chmod +x setup.sh
./setup.sh --serve
```

Without `--serve` it stops after migrations and prints how to start the server.
It prompts for the initial admin password and generates a secret key for you.
See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) before exposing it to a network.

### Enabling the AI tutor

The steps above give you a running site — accounts, dashboards, curriculum
upload, progress tracking. Chat responses need the local inference and RAG
stack, which is a separate install of roughly 3–5 GB:

```
pip install -r requirements-llm.txt
```

For an NVIDIA GPU with CUDA 11.8, install torch from PyTorch's index first:

```
pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cu118
pip install -r requirements-llm.txt
```

The model itself is downloaded from Hugging Face on the first chat message, so
the first response after a fresh install takes a while.

### Model add-ons

- Qwen3 — default module
- LLaMA — requires a license from Meta
- Mistral

Selected via `LLM_MODULE` in `code/llmsite/llmsite/settings.py`. See
[Known Problems](#known-problems).

## Configuration

All secrets and environment-specific settings come from environment variables.
`.env.example` documents every one of them; copy it to `.env` (gitignored) and
fill it in.

The three that matter most:

| Variable | Why |
| --- | --- |
| `DJANGO_SECRET_KEY` | Required. The app refuses to start without it unless `DJANGO_DEBUG=1`. Generate one with `python -c "import secrets; print(secrets.token_hex(32))"`. |
| `ADMIN_PASS` | The password for the first administrator account. **There is no default.** If it is unset when you first run `manage.py migrate`, no admin account is created and migrate prints a notice explaining how to add one. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames the site answers to. Defaults to `localhost,127.0.0.1`, so add your server's LAN IP or DNS name before other machines can reach it. |

For local development, set `DJANGO_DEBUG=1` — with debug off, `runserver` does
not serve static files and the site will render without CSS.

If you already ran `migrate` without `ADMIN_PASS`, set it and replay the
account migration (its reverse is a no-op):

```
python manage.py migrate tutor 0001
python manage.py migrate tutor
```

## Functionality

1. Start the application by running the above commands.
2. The AI tutor will introduce itself and display the initial instructions.
3. Enter a message describing the topic or problem you want help with.
4. The tutor will respond with one step at a time. After completing the step, ask it to continue or ask for clarification.
5. Request quizzes by asking the tutor; it will provide them in a specially formatted quiz UI.
6. The system maintains safeguards to prevent inappropriate content and adheres to the structured step-by-step approach.


## Known Problems

- Model Swapper is not functional with the current version of the product. To swap the LLM, you must access code/llmsite/llmsite/settings.py and change LLM_MODULE to either "qwen", "mistral" or "llama" depending on the model you wish to use.


## Contributing

1. Fork the repository.
2. Create your feature branch: git checkout -b my-new-feature.
3. Make your changes and commit: git commit -am 'Add some feature'.
4. Push to the branch: git push origin my-new-feature.
5. Submit a pull request for review.

## Additional Documentation

- [Documentation Index](docs/README.md) - Entry point for sponsor handoff, deployment, admin, and user documentation.
- [Handoff Overview](docs/HANDOFF_OVERVIEW.md) - Sponsor-facing project summary and scope.
- [Deployment Guide](docs/DEPLOYMENT.md) - Technical setup and operational guidance for the Django application.
- [Admin Operations Guide](docs/ADMIN_OPERATIONS.md) - Staff workflows for accounts, curriculum, exports, and maintenance.
- [User Manual](docs/USER_MANUAL.md) - Client-facing usage guide for students, teachers, and admins.
- [Model Selector Utility](docs/MODEL_SELECTOR.md) - Notes for the separate Windows model configuration tool.
- [Known Limitations](docs/KNOWN_LIMITATIONS.md) - Current technical and operational limits.

- [Sprint 6 Report](docs/Reports/SPRINT_6_REPORT.md) – Sprint 6 latest overview of work completed and unfinished work.
- [Presentations](docs/Presentations/README.md) - Sprint decks and the Sprint 1 demo recording.
- [GitHub Issues](https://github.com/Zelefant/MasteryPilot/issues) - Current issues, user stories, and progress tracking.

## License

[See License](LICENSE.txt)






