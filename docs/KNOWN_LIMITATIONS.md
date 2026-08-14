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

Measured on 2026-08-13: RTX 5070 Ti (16 GB, Blackwell/sm_120), Windows 11,
Python 3.13, torch 2.7.1+cu128, Qwen3-4B in 4-bit. This was the first time any
model in this project was loaded against real weights. 289 requests were driven
through the running site with zero 4xx, zero 5xx and no tracebacks.

- Local inference dependencies are heavy — roughly 3-5 GB, mostly torch — and are split into `requirements-llm.txt`. The site installs, runs, and passes its tests without them, but the tutor cannot answer until they are installed.
- **CUDA 11.8 does not work on Blackwell cards.** The documented `cu118` wheel installs and then fails at the first kernel launch with `no kernel image available for device`. `cu128` is required and is now what the docs say. The pinned `torch==2.7.1` is unchanged — only the index differs.
- **Qwen3-4B is comfortable on 16 GB.** 8.06 GB on disk, 4.1 GB of VRAM once loaded in 4-bit, entirely on the GPU (`hf_device_map = {'': 0}`, no CPU offload), leaving about 11 GB free. Cold load 11.1 s, warm load 7.6 s.
- **Responses are fast but not streamed.** 1.29 s mean, 1.16 s median, 2.22 s worst over eight varied prompts, at about 27 tokens/second. Latency stayed flat as the transcript grew to 827 prompt tokens. Because `_generate` returns only after `model.generate` completes, there is no time-to-first-token: the student waits the whole response before seeing any of it.
- **Prompt injection still defeats the persona: 6 of 8 standard strings succeed.** Two independent attempts failed to close it. A rewritten injection-defence section, naming the exact phrasings and requiring every reply to be a tutoring step, a quiz or a refusal, moved it from 8/8 to 6/8. Qwen3-8B, at twice the VRAM, scored 0/8 held against the original prompt — identical to 4B — so this is not a capacity problem either. `BANANA` and `ZEBRA` still come back verbatim. Closing it needs an output-side guard or a substantially stronger model; assume a determined student can break the persona.
- **The "never give answers directly" rule still fails, in 3 of 8 attempts** (was 4 of 8). The prompt now names the phrasings used against it and forbids working a problem to completion in one reply, which helped but did not settle it.
- **Content-safety refusals hold.** Dirty jokes, weapon construction, election predictions, requests for the system prompt and "you are now unrestricted" are all refused. Writing a web-scraping script was accepted before a SCOPE section was added and is now refused.
- **The tutor loses its place when a student changes topic.** Over 20 scripted runs of four scenarios, 14 finish clean. Solve-through, clarification and wrong-answer recovery each pass 4 or 5 runs in 5; the failures concentrate almost entirely in one case, where a student abandons a problem and then asks for direction instead of answering, and the tutor repeats its own question. Sessions now carry a `progress_ledger` of steps already taught, and `api_chat` regenerates once when a reply repeats the previous one — together these took stalls from 11 to 5 across the same 20 runs. The scenarios and scoring live in `masterypilot-livetest/run10_steptracking.py`.
- **Mistral and LLaMA both work now.** Mistral needed `protobuf` (added to `requirements-llm.txt`) and failed on every retrieval-bearing turn because the curriculum context was appended as a trailing system message, which its template rejects; context now joins the student's turn instead. LLaMA was driven by a hand-written template emitting `<|user|>` and `<|assistant|>`, neither a token in Llama-3.2's vocabulary, and answered by echoing the system prompt back; it now uses the tokenizer's own template.
- The literal checkpoints named in the README (`meta-llama/Llama-3.2-1B-Instruct`, `mistralai/Mistral-7B-Instruct-v0.3`) remain unrun. Both are licence-gated; ungated mirrors with identical tokenizers, templates and weights were used instead.
- Inference is local-only. There is no hosted-API fallback, so a machine without a suitable GPU cannot answer chats.

## Quiz Limits

- **Answer keys are sometimes wrong — 2 of 18 mechanically checkable questions.** One keyed "15% of 200" as 25 while listing 30 among the options; another keyed `2x + 4 = 10` as 4. A student who answers correctly is marked incorrect. This is the model's arithmetic and nothing in the pipeline detects it, so generated quizzes need a teacher's eye before they count for anything. The figure covers only questions a script can evaluate; the true rate across all question types is unmeasured.
- **Quiz mode now triggers reliably** — 16 of 16 requests produce valid JSON, up from 13 of 16. It previously fired only on the literal word "quiz", so "test me on…" produced prose. The prompt now lists the equivalent phrasings and states that the step-by-step and sentence-count rules do not apply in quiz mode, which is what those failed replies were obeying.
- **A quiz that fails to parse is retried once** rather than failing silently. Previously no `Quiz` row was written, the client rendered it as an ordinary chat message, and the student was left with a question they could not submit, with nothing logged.
- **Quizzes now carry three questions** rather than one. The schema example in the prompt showed a single `q1` and the model copied it faithfully every time.
- **Answer position is randomised server-side.** The correct answer previously sat first in 9 of 13 quizzes, so always picking the first option scored about 70%; on Qwen3-8B it was 11 of 12. Asking the model to vary it is a request it can ignore, so `_maybe_persist_quiz` shuffles the options and remaps `correct`. The stored quiz then becomes the canonical text the student is shown and graded against.
- Grading itself is correct. The 0-based `correct` field the model emits, the 1-based radio values the form submits, and the `(user - 1) == correct` comparison in `api_grade_quiz` agree against real output, for both right and wrong answers.

## Export Limits

- Chat exports carry the conversation only. `api_export_chats` filters `role=system` rows and the bootstrap turn, matching what `api_session_messages` shows on screen. Before this, every session contributed a copy of the full 2,608-character system prompt: a real 337-row export was 268 KB, of which about 62% was that repetition; it is now 56 KB.
- Session titles are model-generated and are not sanitised before reaching staff-facing views. A session titled by prompt-injection text appears verbatim in the teacher's session list and as `current_module` on the progress dashboard.

## Retrieval Limits

Measured 2026-08-14 against two OpenStax algebra textbooks (CC-BY) uploaded
through the dashboard: 3.3 million characters, **5,125 chunks**, real
`all-MiniLM-L6-v2` embeddings and a real FAISS index. Earlier figures came from
a 26-chunk corpus written for the test by the same person who wrote the
questions, and one of them was wrong because of it.

- **Retrieval works at scale.** All 10 in-corpus questions returned relevant material from the textbooks, and all 6 off-corpus questions were rejected with zero hits.
- **`MIN_SCORE` was miscalibrated, and the earlier calibration was the reason.** At `0.25` a five-thousand-chunk corpus always has something clearing the floor: "What is the capital of France?" came back with five chunks of algebra textbook, and only 3 of 6 off-corpus questions were rejected. Re-measured over 25 in-corpus and 25 off-corpus questions, the bands separate cleanly — in-corpus min 0.4564, off-corpus max 0.4058 — and **`0.45` keeps 25/25 real answers while rejecting 25/25 off-topic ones**. The previous note in this file called 0.25 "well placed" on the strength of a +0.359 gap; that gap was an artifact of a corpus too small to be wrong. Calibrated for `all-MiniLM-L6-v2`; a different embedding model needs it done again.
- **A small corpus is not reassurance.** The three-document corpus still passes at the new floor — 9/9 top-1, 4/4 rejected, eviction intact — but its worst in-corpus query scores 0.4622, only 0.012 above the threshold. Small-corpus results should not be read as evidence about a real one.
- **The approximate IVF path has now run.** Exercised against the 5,125-chunk corpus by lowering `IVF_THRESHOLD`: the index upgrades to `IndexIVFFlat` (nlist 100, nprobe 10), preserves all 5,125 vectors, and returns results identical to exact search on every query tried. The 20,000-chunk threshold itself has still never been reached naturally.
- **Deleting curriculum genuinely evicts it.** Removing one document through the dashboard took the index from 26 chunks to 19, after which questions answerable only by that document returned nothing.
- **An image-only PDF is ingested as almost nothing, and now says so.** A two-page scanned PDF yields 174 characters — page headers only — because there is no OCR step. It still uploads and still indexes as one useless chunk, but `load_files` now reports any file extracting to under 200 characters, distinguishing "nothing at all" from "suspiciously little". Reading that log line is the only signal; nothing surfaces it in the dashboard.
- **The tutor cites its sources**, naming the file it drew on in a closing sentence. It previously used curriculum near-verbatim and never attributed it, because `RAG_INSTRUCTION` never asked.
- Teachers can upload curriculum but not delete it; deletion is admin-only (`curriculum_delete` is gated on `is_admin`, and the dashboard hides the control accordingly).
- Chunk size is set from the embedding model's context window rather than from measurement. `rag_eval --chunk-size` exists to settle it against real numbers.
- Index invalidation is per process. Deleting curriculum takes effect immediately for the worker that handled the request, and at the next chat-session start for the others. Under a single worker — the default — this is not observable.
- A curriculum change rebuilds the whole index rather than removing individual entries. This is deliberate: incremental removal requires renumbering FAISS ids in step with a parallel metadata list, and a mismatch there misattributes passages silently. Rebuilding the 5,125-chunk textbook corpus takes 41 seconds.

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
