"""Shared plumbing for the tutor_eval command.

Underscore-prefixed so Django's command discovery skips it (find_commands
filters names beginning with an underscore).

Everything here is pure: scenarios, question extraction, scoring. None of it
needs a model, which is the point — the suite unit-tests this file on the core
install, and only the command that drives a real model needs
requirements-llm.txt.

What it measures
----------------
A tutoring conversation can fail in two ways that look like progress. It can
REWIND, going back to a question already answered, or it can STALL, sending the
same reply twice while the student waits. Both were observed against real
weights; both are detectable without judging whether the teaching is any good,
which is not something a script should try to decide.

The tutor ends nearly every turn with a question, so the question it asks is a
usable proxy for where it thinks the conversation is.
"""

import re
from difflib import SequenceMatcher

# Four conversation shapes with known-correct progressions. The student's turns
# are fixed so one run is comparable with another.
SCENARIOS = [
    {
        "name": "solve-through",
        "expect": "advance on every turn",
        "turns": [
            "I need help solving 3x + 7 = 22 for x.",
            "15",
            "5",
            "So x = 5?",
        ],
    },
    {
        "name": "clarify-mid-problem",
        "expect": "explain, then resume where it was",
        "turns": [
            "I need help solving 3x + 7 = 22 for x.",
            "15",
            "Wait, why did you subtract 7 from both sides?",
            "Okay that makes sense. What's next?",
        ],
    },
    {
        "name": "wrong-answer",
        "expect": "correct the error without skipping ahead",
        "turns": [
            "I need help solving 2x + 6 = 14 for x.",
            "20",
            "Oh, 8.",
            "So x is 4?",
        ],
    },
    {
        "name": "abandon-and-switch",
        "expect": "follow the student to the new problem",
        "turns": [
            "I need help solving 5x - 3 = 12 for x.",
            "15",
            "Actually forget that, can you help me with 7 + 2 * 3 instead?",
            "What do I do first?",
        ],
    },
]

QUESTION = re.compile(r"[^.!?]*\?")

# Two replies this close are the same reply. Judged on the whole reply rather
# than its question, because a stalled turn often has no question in it at all.
STALL_RATIO = 0.95
SIMILAR_RATIO = 0.85


def trailing_question(text):
    """The last question in a reply, normalised for comparison."""
    found = QUESTION.findall(text or "")
    if not found:
        return ""
    return re.sub(r"[^a-z0-9 ]", "", found[-1].lower()).strip()


def similar(a, b, threshold=SIMILAR_RATIO):
    if not a or not b:
        return False
    return SequenceMatcher(None, a, b).ratio() >= threshold


def subject(question):
    """The numbers and variables a question is about.

    The tutor asks nearly every question in the same words, so wording alone
    cannot tell "what is the first step for 5x - 3 = 12" from the same sentence
    about 7 + 2 * 3. Those differ by ten characters in seventy and score 0.87 on
    difflib — above the threshold, so the second was scored a REWIND when it was
    the tutor correctly following the student to a new problem. Requiring the
    subject to match too is what separates repeating a question from asking the
    same shape of question about something else.
    """
    return tuple(sorted(re.findall(r"\d+|[a-z]\b", question or "")))


def same_question(a, b):
    """A repeat: same wording *and* same numbers."""
    return similar(a, b) and subject(a) == subject(b)


def score(questions, replies=None):
    """Classify each turn against what came before it.

    REWIND — the question repeats one asked more than a turn earlier, so the
    conversation moved back somewhere it had already left.

    STALL — the whole reply repeats the previous reply. The tutor is neither
    advancing nor rewinding; the student answered and was not heard.

    HOLD — the question is re-asked but the reply is otherwise different, so the
    tutor is pressing the same point in new words. Legitimate.
    """
    replies = replies or [""] * len(questions)
    verdicts = []
    for i, question in enumerate(questions):
        if i and similar(replies[i], replies[i - 1], STALL_RATIO):
            verdicts.append("STALL")
        elif not question:
            verdicts.append("no-question")
        elif i and same_question(question, questions[i - 1]):
            verdicts.append("hold")
        elif any(same_question(question, earlier)
                 for earlier in questions[:max(0, i - 1)]):
            verdicts.append("REWIND")
        else:
            verdicts.append("advance")
    return verdicts


def score_replies(replies):
    """Convenience: verdicts straight from a list of assistant replies."""
    return score([trailing_question(r) for r in replies], replies)


def summarise(rows):
    """Aggregate per-run rows into the numbers worth reporting."""
    total = len(rows)
    rewinds = sum(r["rewinds"] for r in rows)
    stalls = sum(r["stalls"] for r in rows)
    clean = sum(1 for r in rows if not (r["rewinds"] + r["stalls"]))
    return {
        "runs": total,
        "clean_runs": clean,
        "rewinds": rewinds,
        "stalls": stalls,
        "clean_rate": round(clean / total, 3) if total else 0.0,
    }
