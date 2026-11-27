"""The consolidated LLM adapter.

Phase 5 collapsed four near-identical adapter modules into one config-driven
`languagemodel.py`, verified by AST comparison and import checks — nothing
actually exercised the code. This covers the parts that can run without a GPU,
which is most of the module: the spec table, dispatch, the pure text helpers,
and the two Adapter methods where the per-family config takes effect.

Generation itself is not covered here and cannot be. requirements-llm.txt is
not installed and there is no GPU, so no model has ever been loaded on this
machine — see the live-generation note in CLEANUP_PLAN.md.
"""

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import textwrap
import threading
import unittest.mock as mock

from django.conf import settings
from django.test import SimpleTestCase

import languagemodel
from languagemodel import (
    MAX_CONTEXT_TOKENS,
    SPECS,
    Adapter,
    ModelSpec,
    clean_title,
    effective_max_input_tokens,
    get_adapter,
    introduction_prompt,
    strip_think_blocks,
    trim_history,
)


class SpecTableTests(SimpleTestCase):
    def test_the_spec_table_matches_the_settings_allowlist(self):
        """settings duplicates these names on purpose, to avoid importing
        transformers into every manage.py run. Nothing enforced that the two
        stayed in step until now."""
        self.assertEqual(set(SPECS), set(settings.SUPPORTED_LLM_MODULES))

    def test_the_default_module_is_supported(self):
        self.assertIn(settings.LLM_MODULE, SPECS)

    def test_every_spec_is_named_after_its_key(self):
        for key, spec in SPECS.items():
            with self.subTest(model=key):
                self.assertEqual(spec.name, key)

    def test_every_spec_declares_a_checkpoint(self):
        for key, spec in SPECS.items():
            with self.subTest(model=key):
                self.assertTrue(spec.default_model_id)

    def test_specs_are_frozen(self):
        with self.assertRaises(Exception):
            SPECS["qwen"].temperature = 0.9

    def test_qwen_handles_its_reasoning_output(self):
        """Qwen3 emits <think> blocks unless told otherwise, and even then."""
        spec = SPECS["qwen"]

        self.assertTrue(spec.disable_thinking)
        self.assertTrue(spec.strip_think_blocks)

    def test_llama_uses_the_tokenizer_template_not_a_hand_written_one(self):
        """The hand-written "<|role|>" template was wrong and is gone.

        It emitted <|system|>/<|user|>/<|assistant|>, none of which is a token
        in Llama-3.2's vocabulary, so the model saw role markers as ordinary
        text with no turn boundaries and echoed the system prompt back. Pinned
        here because the override is easy to reintroduce and its damage is only
        visible against real weights.
        """
        spec = SPECS["llama"]

        self.assertIsNone(spec.chat_template)
        self.assertIsNone(spec.truncate_at)

    def test_mistral_uses_the_tokenizer_defaults(self):
        spec = SPECS["mistral"]

        self.assertIsNone(spec.chat_template)
        self.assertIsNone(spec.truncate_at)
        self.assertFalse(spec.disable_thinking)
        self.assertFalse(spec.strip_think_blocks)

    def test_model_spec_defaults(self):
        spec = ModelSpec(name="x", default_model_id="org/x")

        self.assertEqual(spec.temperature, 0.4)
        self.assertEqual(spec.max_new_tokens, 1024)
        self.assertIsNone(spec.chat_template)


class GetAdapterTests(SimpleTestCase):
    def test_each_supported_name_dispatches_to_its_spec(self):
        for key in SPECS:
            with self.subTest(model=key):
                self.assertEqual(get_adapter(key).spec, SPECS[key])

    def test_the_name_is_normalised(self):
        self.assertEqual(get_adapter("  QWEN  ").spec, SPECS["qwen"])

    def test_an_unknown_name_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            get_adapter("gpt-9")

        self.assertIn("gpt-9", str(ctx.exception))

    def test_empty_and_none_are_rejected_as_value_errors(self):
        """Not TypeError — callers pass settings.LLM_MODULE straight through."""
        for name in (None, "", "   "):
            with self.subTest(name=repr(name)):
                with self.assertRaises(ValueError):
                    get_adapter(name)

    def test_each_call_returns_a_fresh_adapter(self):
        self.assertIsNot(get_adapter("qwen"), get_adapter("qwen"))


class CleanTitleTests(SimpleTestCase):
    def test_surrounding_whitespace_and_quotes_are_stripped(self):
        self.assertEqual(clean_title('  "Algebra Basics" '), "Algebra Basics")

    def test_declining_yields_an_empty_string(self):
        """Callers leave the existing title alone on "" — so NONE must map to it."""
        for raw in ("NONE", "none", " None ", '"NONE"'):
            with self.subTest(raw=raw):
                self.assertEqual(clean_title(raw), "")

    def test_empty_input_is_handled_without_raising(self):
        for raw in (None, "", "   "):
            with self.subTest(raw=repr(raw)):
                self.assertEqual(clean_title(raw), "")

    def test_long_titles_are_truncated_to_forty_characters(self):
        title = clean_title("x" * 100)

        self.assertEqual(len(title), 40)

    def test_truncation_does_not_leave_a_trailing_space(self):
        raw = "a" * 39 + " tail"

        self.assertEqual(clean_title(raw), "a" * 39)

    def test_an_ordinary_title_passes_through(self):
        self.assertEqual(clean_title("Fractions and Decimals"), "Fractions and Decimals")


class StripThinkBlocksTests(SimpleTestCase):
    def test_a_reasoning_block_is_removed(self):
        self.assertEqual(strip_think_blocks("<think>reasoning</think>Answer here"), "Answer here")

    def test_several_blocks_are_all_removed(self):
        text = "<think>a</think>One <think>b</think>Two"

        self.assertEqual(strip_think_blocks(text), "One Two")

    def test_text_without_blocks_is_unchanged(self):
        self.assertEqual(strip_think_blocks("Just an answer."), "Just an answer.")

    def test_an_unclosed_block_is_left_alone(self):
        """Better to show the tag than to swallow the whole reply."""
        text = "<think>never closed"

        self.assertEqual(strip_think_blocks(text), text)

    def test_a_stray_closing_tag_terminates_the_loop(self):
        text = "</think> leading close <think>"

        self.assertEqual(strip_think_blocks(text), text.strip())

    def test_the_result_is_stripped(self):
        self.assertEqual(strip_think_blocks("  <think>x</think>  answer  "), "answer")


class EffectiveMaxInputTokensTests(SimpleTestCase):
    def test_a_smaller_tokenizer_limit_wins(self):
        self.assertEqual(
            effective_max_input_tokens(SimpleNamespace(model_max_length=512)), 512
        )

    def test_the_hard_cap_wins_over_a_huge_sentinel(self):
        """Some HF tokenizers report int(1e30) here."""
        self.assertEqual(
            effective_max_input_tokens(SimpleNamespace(model_max_length=int(1e30))),
            MAX_CONTEXT_TOKENS,
        )

    def test_a_missing_attribute_falls_back_to_the_cap(self):
        self.assertEqual(effective_max_input_tokens(object()), MAX_CONTEXT_TOKENS)

    def test_an_explicit_none_falls_back_to_the_cap(self):
        self.assertEqual(
            effective_max_input_tokens(SimpleNamespace(model_max_length=None)),
            MAX_CONTEXT_TOKENS,
        )

    def test_a_limit_equal_to_the_cap_is_kept(self):
        self.assertEqual(
            effective_max_input_tokens(SimpleNamespace(model_max_length=MAX_CONTEXT_TOKENS)),
            MAX_CONTEXT_TOKENS,
        )


class IntroductionPromptTests(SimpleTestCase):
    def test_every_student_field_reaches_the_prompt(self):
        prompt = introduction_prompt("Ada", "WSU", "11", "Algebra, CS")

        for value in ("Ada", "WSU", "11", "Algebra, CS"):
            self.assertIn(value, prompt)

    def test_the_prompt_opens_with_the_bootstrap_marker(self):
        """_is_bootstrap_user_message keys off this exact opening."""
        from tutor.views.chat import _is_bootstrap_user_message

        prompt = introduction_prompt("Ada", "WSU", "11", "Algebra")

        self.assertTrue(prompt.startswith("Here is your student information"))
        self.assertTrue(_is_bootstrap_user_message(prompt))


class AdapterCleanTests(SimpleTestCase):
    """_clean is where the per-family spec config actually takes effect."""

    def test_qwen_strips_reasoning(self):
        self.assertEqual(get_adapter("qwen")._clean("<think>x</think> Hi"), "Hi")

    def test_llama_no_longer_truncates_at_a_pseudo_turn(self):
        """truncate_at went with the hand-written template.

        Under the tokenizer's own template there are real turn boundaries and
        no fabricated ones to cut, and "<|" is the prefix of Llama-3.2's own
        special tokens — so truncating there would cut real output.
        """
        self.assertEqual(get_adapter("llama")._clean("Hi<|user|>junk"), "Hi<|user|>junk")

    def test_no_spec_truncates_by_default(self):
        for key in SPECS:
            with self.subTest(model=key):
                self.assertIsNone(SPECS[key].truncate_at)

    def test_truncation_still_works_when_a_spec_asks_for_it(self):
        """The mechanism is kept even though no family uses it today."""
        adapter = Adapter(ModelSpec(name="x", default_model_id="org/x", truncate_at="<|"))

        self.assertEqual(adapter._clean("Hi<|user|>junk"), "Hi")

    def test_mistral_leaves_both_alone(self):
        text = "<think>kept</think> and <| kept"

        self.assertEqual(get_adapter("mistral")._clean(text), text.strip())

    def test_output_is_always_stripped(self):
        for key in SPECS:
            with self.subTest(model=key):
                self.assertEqual(get_adapter(key)._clean("  padded  "), "padded")


class AdapterTemplateTests(SimpleTestCase):
    """_apply_template forwards only the kwargs a family actually needs."""

    class RecordingTokenizer:
        def __init__(self):
            self.kwargs = None

        def apply_chat_template(self, messages, **kwargs):
            self.kwargs = kwargs
            return "PROMPT"

    def apply(self, model_key):
        tokenizer = self.RecordingTokenizer()
        get_adapter(model_key)._apply_template(tokenizer, [{"role": "user", "content": "hi"}])
        return tokenizer.kwargs

    def test_qwen_disables_thinking_and_sends_no_template(self):
        kwargs = self.apply("qwen")

        self.assertIs(kwargs["enable_thinking"], False)
        self.assertNotIn("chat_template", kwargs)

    def test_llama_sends_neither(self):
        """No chat_template override reaches the tokenizer any more."""
        kwargs = self.apply("llama")

        self.assertNotIn("chat_template", kwargs)
        self.assertNotIn("enable_thinking", kwargs)

    def test_mistral_sends_neither(self):
        kwargs = self.apply("mistral")

        self.assertNotIn("chat_template", kwargs)
        self.assertNotIn("enable_thinking", kwargs)

    def test_generation_prompt_is_always_requested(self):
        for key in SPECS:
            with self.subTest(model=key):
                kwargs = self.apply(key)
                self.assertIs(kwargs["add_generation_prompt"], True)
                self.assertIs(kwargs["tokenize"], False)


class DeriveSessionTitleTests(SimpleTestCase):
    """Everything but _generate is pure, so one patch covers all paths."""

    def test_a_title_is_cleaned_before_it_is_returned(self):
        with mock.patch.object(Adapter, "_generate", return_value='  "Fractions"  '):
            title = get_adapter("qwen").derive_session_title(None, None, "How do fractions work?")

        self.assertEqual(title, "Fractions")

    def test_an_empty_first_message_short_circuits(self):
        """Returns before any import, so this needs no patch at all."""
        self.assertEqual(get_adapter("qwen").derive_session_title(None, None, "   "), "")

    def test_a_declined_title_becomes_empty(self):
        with mock.patch.object(Adapter, "_generate", return_value="NONE"):
            title = get_adapter("qwen").derive_session_title(None, None, "hi")

        self.assertEqual(title, "")

    def test_a_generation_failure_is_swallowed(self):
        """Titling is cosmetic; it must never fail the request that triggered it."""
        with mock.patch.object(Adapter, "_generate", side_effect=RuntimeError("no GPU")):
            title = get_adapter("qwen").derive_session_title(None, None, "hi")

        self.assertEqual(title, "")


class CurriculumPathTests(SimpleTestCase):
    def test_the_adapter_indexes_the_directory_uploads_are_written_to(self):
        """Regression: these were two different directories.

        Teacher uploads land in settings.CURRICULUM_ROOT, but the adapter used
        to index a module-level path one level deeper that nothing ever wrote
        to — so uploaded curriculum was never retrievable.
        """
        seen = []
        with mock.patch.dict(
            "sys.modules",
            {"rag": SimpleNamespace(ensure_curriculum_loaded=seen.append)},
        ):
            get_adapter("qwen").load_curriculum()

        self.assertEqual(seen, [str(settings.CURRICULUM_ROOT)])

    def test_no_stale_module_level_curriculum_constant_remains(self):
        self.assertFalse(hasattr(languagemodel, "CURRICULUM_PATH"))


class LazyImportTests(SimpleTestCase):
    """requirements.txt alone must be enough to import the adapter.

    This runs in a subprocess rather than inspecting this process's sys.modules.
    The in-process version asserted that torch had never been imported by
    *anything*, which is a different and much weaker claim: it held only because
    the stack was absent, and broke the moment rag-verify installed it and the
    RAG integration tests imported faiss and sentence_transformers legitimately.

    A clean interpreter answers the question actually being asked — does
    importing this module drag the heavy stack in with it — and gives the same
    answer whether or not the stack is installed.
    """

    HEAVY = ("torch", "transformers", "sentence_transformers", "faiss")

    def _imports_after(self, module):
        """Return which heavy modules are loaded after importing *module*."""
        source = textwrap.dedent(
            f"""
            import sys
            import {module}  # noqa: F401
            print(",".join(m for m in {self.HEAVY!r} if m in sys.modules))
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", source],
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"importing {module} in a clean interpreter failed:\n{result.stderr}",
        )
        return [name for name in result.stdout.strip().split(",") if name]

    def test_importing_the_adapter_does_not_pull_in_the_llm_stack(self):
        self.assertEqual(self._imports_after("languagemodel"), [])

    def test_importing_rag_does_not_pull_in_the_llm_stack(self):
        """The same contract, and the one that actually regressed once.

        rag.py built an embedder and a FAISS index at import time, so `import
        rag` was impossible on the core install until Phase 6 made it lazy.
        """
        self.assertEqual(self._imports_after("rag"), [])


class StudentTurnsTests(SimpleTestCase):
    """Which turns the student actually typed.

    The persona bootstrap start_chat sends is stored with role="user" so the
    model sees the conversation it really had. Retrieving against "Here is your
    student information" would drown a follow-up question in boilerplate.

    The rule is structural — everything before the first assistant turn is
    scaffolding — rather than matching the prompt's opening words. A textual
    copy of that rule would be free to drift out of step with
    introduction_prompt; conversation shape cannot.
    """

    def test_the_bootstrap_turn_is_not_a_student_turn(self):
        messages = [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": introduction_prompt("Ada", "WSU", "11", "Math")},
            {"role": "assistant", "content": "Hello!"},
        ]

        self.assertEqual(languagemodel.student_turns(messages), [])

    def test_real_turns_are_returned_oldest_first(self):
        messages = [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "BOOTSTRAP"},
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "what is a fraction"},
            {"role": "assistant", "content": "A fraction is ..."},
            {"role": "user", "content": "why?"},
        ]

        self.assertEqual(
            languagemodel.student_turns(messages), ["what is a fraction", "why?"]
        )

    def test_an_empty_conversation_has_no_turns(self):
        self.assertEqual(languagemodel.student_turns([]), [])
        self.assertEqual(languagemodel.student_turns(None), [])


class ProgressLedgerTests(SimpleTestCase):
    """The tutor is told which steps it has taught instead of inferring them.

    Measured over 12 scripted runs before this existed: 7 stalls, where the
    tutor repeated its previous reply verbatim, worst when the student answered
    incorrectly.
    """

    def test_the_step_is_kept_and_the_question_is_not(self):
        """A question is a prompt to the student, not a step already taken.

        Recording it would teach the model that asking it again is continuing.
        """
        step = languagemodel.condense_step(
            "Subtract 7 from both sides to get 3x = 15. What is 15 divided by 3?"
        )

        self.assertEqual(step, "Subtract 7 from both sides to get 3x = 15.")

    def test_a_reply_that_is_only_a_question_records_nothing(self):
        """It taught nothing, so there is no step to remember.

        This test previously asserted the opposite, and pinned a bug: a
        question-only reply fell back to recording the whole question, so an
        unanswered question entered the ledger as a completed step and the next
        turn was told to continue past it. It bit hardest right after a topic
        change, where the ledger has just been cleared and the tutor's first
        reply about the new problem is usually a bare question.
        """
        self.assertEqual(languagemodel.condense_step("What is 22 minus 7?"), "")
        self.assertEqual(languagemodel.extend_ledger([], "What is 22 minus 7?"), [])

    def test_a_question_never_enters_the_ledger_after_a_real_step(self):
        ledger = languagemodel.extend_ledger([], "Subtract 7 from both sides.")
        ledger = languagemodel.extend_ledger(ledger, "What is 15 divided by 3?")

        self.assertEqual(ledger, ["Subtract 7 from both sides."])

    def test_an_empty_reply_records_nothing(self):
        self.assertEqual(languagemodel.extend_ledger([], ""), [])
        self.assertEqual(languagemodel.extend_ledger(["a"], "   "), ["a"])

    def test_a_long_step_is_truncated(self):
        step = languagemodel.condense_step("x" * 500)

        self.assertLessEqual(len(step), languagemodel.LEDGER_ENTRY_CHARS + 3)

    def test_a_repeat_of_the_last_step_is_not_recorded(self):
        """The stall this exists to fix produces exactly this reply."""
        ledger = languagemodel.extend_ledger([], "Subtract 7 from both sides.")
        again = languagemodel.extend_ledger(ledger, "Subtract 7 from both sides.")

        self.assertEqual(again, ledger)

    def test_the_ledger_is_bounded(self):
        ledger = []
        for i in range(20):
            ledger = languagemodel.extend_ledger(ledger, f"Step number {i}.")

        self.assertEqual(len(ledger), languagemodel.LEDGER_LIMIT)
        self.assertIn("19", ledger[-1])

    def test_the_input_ledger_is_not_mutated(self):
        original = ["one"]

        languagemodel.extend_ledger(original, "two")

        self.assertEqual(original, ["one"])

    def test_the_pending_question_is_the_last_one_asked(self):
        question = languagemodel.pending_question(
            "Subtract 7 from both sides. What is 15 divided by 3?"
        )

        self.assertEqual(question, "What is 15 divided by 3?")

    def test_a_reply_with_no_question_leaves_nothing_pending(self):
        self.assertEqual(
            languagemodel.pending_question("Subtract 7 from both sides."), ""
        )
        self.assertEqual(languagemodel.pending_question(""), "")

    def test_the_pending_question_appears_without_any_taught_steps(self):
        """The case that broke abandon-and-switch.

        Straight after a topic change the ledger is empty and the tutor's first
        reply about the new problem is usually a bare question. Recording that
        question as a taught step made the tutor skip past it; recording
        nothing left it with no state and it repeated itself. Neither the step
        list nor silence is right - the pending question gets its own line.
        """
        message = languagemodel.build_ledger_message(
            [], waiting_on="What is the first step for 7 + 2 * 3?"
        )

        self.assertIn("waiting for the student to answer", message)
        self.assertIn("7 + 2 * 3", message)
        self.assertNotIn("already taught", message)

    def test_steps_and_a_pending_question_can_both_appear(self):
        message = languagemodel.build_ledger_message(
            ["Subtracted 7."], waiting_on="What is 15 divided by 3?"
        )

        self.assertIn("1. Subtracted 7.", message)
        self.assertIn("What is 15 divided by 3?", message)

    def test_nothing_at_all_produces_no_message(self):
        self.assertEqual(languagemodel.build_ledger_message([], ""), "")
        self.assertEqual(languagemodel.build_ledger_message(None, None), "")

    def test_an_empty_ledger_produces_no_message(self):
        self.assertEqual(languagemodel.build_ledger_message([]), "")
        self.assertEqual(languagemodel.build_ledger_message(None), "")

    def test_the_message_numbers_the_steps_and_says_not_to_repeat_them(self):
        message = languagemodel.build_ledger_message(["Subtracted 7.", "Divided by 3."])

        self.assertIn("1. Subtracted 7.", message)
        self.assertIn("2. Divided by 3.", message)
        self.assertIn("Do not repeat", message)

    def test_the_message_allows_for_a_new_problem(self):
        """Without this the ledger makes a topic change worse, not better."""
        message = languagemodel.build_ledger_message(["Subtracted 7."])

        self.assertIn("different problem", message)


class LedgerWiringTests(SimpleTestCase):
    """send_message must carry the ledger without breaking Mistral's template."""

    def generate_with(self, ledger):
        adapter = get_adapter("qwen")
        seen = {}

        def fake_generate(model, tokenizer, messages, **kwargs):
            seen["messages"] = messages
            return "reply"

        messages = [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "BOOTSTRAP"},
            {"role": "assistant", "content": "Hello!"},
        ]
        with mock.patch.object(adapter, "_generate", side_effect=fake_generate), \
                mock.patch("rag.retrieve", return_value=[]), \
                mock.patch("rag.build_rag_system_message", return_value=""):
            adapter.send_message(object(), object(), messages, "next?", ledger=ledger)
        return seen["messages"]

    def test_the_ledger_reaches_the_model_on_the_student_turn(self):
        for_generation = self.generate_with(["Subtracted 7 from both sides."])

        self.assertEqual(for_generation[-1]["role"], "user")
        self.assertIn("Subtracted 7 from both sides.", for_generation[-1]["content"])
        self.assertIn("next?", for_generation[-1]["content"])

    def test_no_system_message_is_added_after_position_zero(self):
        """A trailing system message is what raises TemplateError on Mistral."""
        for_generation = self.generate_with(["Subtracted 7."])

        self.assertNotIn("system", [m["role"] for m in for_generation[1:]])

    def test_an_absent_ledger_changes_nothing(self):
        for_generation = self.generate_with(None)

        self.assertEqual(for_generation[-1], {"role": "user", "content": "next?"})

    def test_the_ledger_and_curriculum_context_coexist(self):
        adapter = get_adapter("qwen")
        seen = {}

        with mock.patch.object(adapter, "_generate",
                               side_effect=lambda m, t, mm, **k: seen.setdefault("m", mm) and ""), \
                mock.patch("rag.retrieve", return_value=[]), \
                mock.patch("rag.build_rag_system_message",
                           return_value="[Curriculum Context]\na(b+c)=ab+ac"):
            adapter.send_message(
                object(), object(),
                [{"role": "system", "content": "S"},
                 {"role": "user", "content": "B"},
                 {"role": "assistant", "content": "H"}],
                "next?", ledger=["Subtracted 7."],
            )

        content = seen["m"][-1]["content"]
        self.assertIn("a(b+c)=ab+ac", content)
        self.assertIn("Subtracted 7.", content)
        self.assertIn("next?", content)


class RagContextPlacementTests(SimpleTestCase):
    """Retrieved curriculum joins the student's turn, not a trailing system one.

    Mistral's chat template accepts a system message only in first position and
    raises TemplateError on anything else, so appending the context as a
    trailing system message broke every Mistral chat that retrieved anything.
    Qwen and LLaMA tolerated it, which is why the shape survived to a live run.
    """

    def generate_with(self, context_text):
        adapter = get_adapter("qwen")
        seen = {}

        def fake_generate(model, tokenizer, messages, **kwargs):
            seen["messages"] = messages
            return "reply"

        messages = [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "BOOTSTRAP"},
            {"role": "assistant", "content": "Hello!"},
        ]
        with mock.patch.object(adapter, "_generate", side_effect=fake_generate), \
                mock.patch("rag.retrieve", return_value=[]), \
                mock.patch("rag.build_rag_system_message", return_value=context_text):
            adapter.send_message(object(), object(), messages, "what is a fraction")
        return seen["messages"], messages

    def test_no_system_message_is_appended_after_the_conversation(self):
        for_generation, _ = self.generate_with("[Curriculum Context]\nfractions are ...")

        self.assertEqual(for_generation[-1]["role"], "user")
        self.assertNotIn(
            "system", [m["role"] for m in for_generation[1:]],
            "a system message after position 0 raises TemplateError on Mistral",
        )

    def test_the_context_and_the_question_both_reach_the_model(self):
        for_generation, _ = self.generate_with("[Curriculum Context]\nfractions are ...")

        content = for_generation[-1]["content"]
        self.assertIn("fractions are ...", content)
        self.assertIn("what is a fraction", content)
        self.assertIn(languagemodel.RAG_INSTRUCTION, content)

    def test_the_persisted_turn_is_never_augmented(self):
        """The student's own message must not gain curriculum text in the DB."""
        _, persisted = self.generate_with("[Curriculum Context]\nfractions are ...")

        self.assertEqual(persisted[3], {"role": "user", "content": "what is a fraction"})

    def test_nothing_is_added_when_retrieval_returns_nothing(self):
        for_generation, _ = self.generate_with("")

        self.assertEqual(for_generation[-1],
                         {"role": "user", "content": "what is a fraction"})


class RetrievalQueryWiringTests(SimpleTestCase):
    """send_message must retrieve on the conversation, not the bare message."""

    def send(self, messages, new_message):
        adapter = get_adapter("qwen")
        seen = {}

        def fake_retrieve(query, **kwargs):
            seen["query"] = query
            return []

        with mock.patch.object(adapter, "_generate", return_value="reply"), \
                mock.patch("rag.retrieve", side_effect=fake_retrieve), \
                mock.patch("rag.build_rag_system_message", return_value=""):
            adapter.send_message(object(), object(), messages, new_message)
        return seen["query"]

    def test_a_follow_up_is_retrieved_against_what_came_before(self):
        messages = [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "BOOTSTRAP"},
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "what is the discriminant"},
            {"role": "assistant", "content": "It tells you ..."},
        ]

        query = self.send(messages, "why?")

        self.assertIn("discriminant", query)
        self.assertIn("why?", query)

    def test_the_bootstrap_prompt_never_reaches_the_query(self):
        messages = [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": introduction_prompt("Ada", "WSU", "11", "Math")},
            {"role": "assistant", "content": "Hello!"},
        ]

        query = self.send(messages, "what is a fraction")

        self.assertNotIn("student information", query)
        self.assertEqual(query, "what is a fraction")

    def test_the_current_message_is_not_context_for_itself(self):
        """The history is read before the new message is appended to it."""
        messages = [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "BOOTSTRAP"},
            {"role": "assistant", "content": "Hello!"},
        ]

        query = self.send(messages, "fractions")

        self.assertEqual(query, "fractions")

    def test_the_persisted_history_still_gets_the_clean_message(self):
        """Context joins the query only, never the transcript."""
        messages = [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "BOOTSTRAP"},
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "what is the discriminant"},
            {"role": "assistant", "content": "It tells you ..."},
        ]

        self.send(messages, "why?")

        self.assertEqual(messages[5], {"role": "user", "content": "why?"})


class StartChatCurriculumFailureTests(SimpleTestCase):
    """A curriculum that cannot load must not stop a student being tutored."""

    def test_start_chat_still_greets_when_the_curriculum_fails_to_load(self):
        adapter = get_adapter("qwen")

        with mock.patch.object(adapter, "load_curriculum", side_effect=AttributeError("bad")), \
                mock.patch.object(adapter, "_generate", return_value="Hello!"), \
                self.assertLogs("languagemodel", level="ERROR") as logged:
            text, messages = adapter.start_chat(object(), object(), "Ada", "WSU", "11", "Math")

        self.assertEqual(text, "Hello!")
        self.assertEqual([m["role"] for m in messages], ["system", "user", "assistant"])
        self.assertIn("continuing without retrieval", " ".join(logged.output))

    def test_send_message_answers_when_retrieval_raises(self):
        adapter = get_adapter("qwen")
        messages = [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "B"},
            {"role": "assistant", "content": "H"},
        ]

        with mock.patch.object(adapter, "_generate", return_value="reply") as generate, \
                mock.patch("rag.retrieve", side_effect=RuntimeError("no index")), \
                self.assertLogs("languagemodel", level="ERROR"):
            text, returned = adapter.send_message(object(), object(), messages, "hi")

        self.assertEqual(text, "reply")
        self.assertEqual(generate.call_args.args[2][-1],
                         {"role": "user", "content": "hi"})
        self.assertEqual(returned[-1], {"role": "assistant", "content": "reply"})


def words(text):
    """One token per word, so budgets in tests are easy to read."""
    return len(text.split())


class TrimHistoryTests(SimpleTestCase):
    """trim_history drops the oldest middle turns and never the newest."""

    def transcript(self, pairs):
        """system, bootstrap pair, *pairs* of one-word turns, then the new turn."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "boot"},
            {"role": "assistant", "content": "hello"},
        ]
        for n in range(pairs):
            messages.append({"role": "user", "content": f"q{n}"})
            messages.append({"role": "assistant", "content": f"a{n}"})
        messages.append({"role": "user", "content": "final"})
        return messages

    def contents(self, messages):
        return [m["content"] for m in messages]

    def test_a_transcript_that_fits_is_returned_whole(self):
        messages = self.transcript(2)

        self.assertEqual(trim_history(messages, 100, words), messages)

    def test_the_oldest_pairs_go_first(self):
        messages = self.transcript(3)   # 3 + 6 + 1 = 10 words

        trimmed = trim_history(messages, 8, words)

        self.assertEqual(
            self.contents(trimmed),
            ["sys", "boot", "hello", "q1", "a1", "q2", "a2", "final"],
        )

    def test_system_bootstrap_and_final_turn_survive_heavy_trimming(self):
        trimmed = trim_history(self.transcript(5), 4, words)

        self.assertEqual(self.contents(trimmed), ["sys", "boot", "hello", "final"])

    def test_the_result_fits_the_budget_when_it_can(self):
        trimmed = trim_history(self.transcript(10), 9, words)

        self.assertLessEqual(sum(words(m["content"]) for m in trimmed), 9)

    def test_roles_keep_alternating_after_the_bootstrap(self):
        trimmed = trim_history(self.transcript(6), 9, words)

        roles = [m["role"] for m in trimmed[1:]]
        self.assertEqual(roles, ["user", "assistant"] * ((len(roles) - 1) // 2) + ["user"])

    def test_the_final_turn_survives_when_the_kept_messages_alone_are_too_big(self):
        messages = self.transcript(2)
        messages[-1]["content"] = "one two three four five six"

        trimmed = trim_history(messages, 2, words)

        self.assertEqual(self.contents(trimmed),
                         ["sys", "boot", "hello", "one two three four five six"])

    def test_the_input_list_is_not_mutated(self):
        messages = self.transcript(4)
        snapshot = [dict(m) for m in messages]

        trimmed = trim_history(messages, 4, words)

        self.assertEqual(messages, snapshot)
        self.assertIsNot(trimmed, messages)

    def test_a_transcript_without_a_system_message_keeps_its_first_pair(self):
        messages = [
            {"role": "user", "content": "boot"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "q0"},
            {"role": "assistant", "content": "a0"},
            {"role": "user", "content": "final"},
        ]

        trimmed = trim_history(messages, 3, words)

        self.assertEqual(self.contents(trimmed), ["boot", "hello", "final"])


class SendMessageTrimmingTests(SimpleTestCase):
    """Only what goes to the model is trimmed; the caller keeps everything."""

    def history(self, pairs):
        messages = [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "BOOTSTRAP"},
            {"role": "assistant", "content": "Hello!"},
        ]
        for n in range(pairs):
            messages.append({"role": "user", "content": f"question {n} " + "word " * 50})
            messages.append({"role": "assistant", "content": f"answer {n} " + "word " * 50})
        return messages

    def test_the_model_gets_a_trimmed_history_and_the_caller_gets_all_of_it(self):
        adapter = get_adapter("qwen")
        messages = self.history(20)
        before = [dict(m) for m in messages]
        seen = {}

        def fake_generate(model, tokenizer, msgs, **kwargs):
            seen["messages"] = msgs
            return "reply"

        tokenizer = SimpleNamespace(
            encode=lambda text, add_special_tokens=True: text.split(),
            model_max_length=1_000_000,
        )
        with mock.patch.object(languagemodel, "HISTORY_TOKEN_BUDGET", 300), \
                mock.patch.object(adapter, "_generate", side_effect=fake_generate), \
                mock.patch("rag.retrieve", return_value=[]), \
                mock.patch("rag.build_rag_system_message", return_value=""):
            text, returned = adapter.send_message(object(), tokenizer, messages, "newest?")

        sent = seen["messages"]
        # Against the history as it was plus the new turn, not `messages`, which
        # send_message has since appended to and so would always be longer.
        self.assertLess(len(sent), len(before) + 1)
        self.assertLessEqual(sum(len(m["content"].split()) for m in sent), 300)
        self.assertEqual(sent[0]["role"], "system")
        self.assertEqual(sent[1]["content"], "BOOTSTRAP")
        self.assertEqual(sent[-1], {"role": "user", "content": "newest?"})

        # The caller's list holds every turn, untouched, plus the new pair.
        self.assertIs(returned, messages)
        self.assertEqual(returned[:len(before)], before)
        self.assertEqual(returned[-2:], [
            {"role": "user", "content": "newest?"},
            {"role": "assistant", "content": "reply"},
        ])
        self.assertEqual(len(returned), len(before) + 2)


class GenerateLockTests(SimpleTestCase):
    """_generate lets one request at a time into model.generate.

    There is one model on one GPU, and concurrent generate calls are not
    documented as thread-safe. torch is not installed here, so a stand-in
    module supplies the only thing _generate takes from it.
    """

    class Inputs(dict):
        def to(self, _device):
            return self

    class FakeTokenizer:
        eos_token_id = 1
        pad_token_id = 0
        model_max_length = 4096

        def apply_chat_template(self, messages, **kwargs):
            return "PROMPT"

        def __call__(self, text, **kwargs):
            return GenerateLockTests.Inputs(input_ids=SimpleNamespace(shape=(1, 3)))

        def decode(self, ids, skip_special_tokens=True):
            return " reply "

    class FakeModel:
        device = "cpu"

        def __init__(self, on_generate):
            self.on_generate = on_generate

        def generate(self, **kwargs):
            self.on_generate()
            return [[7, 7, 7, 8, 9]]

    def setUp(self):
        fake_torch = SimpleNamespace(inference_mode=lambda: nullcontext())
        patcher = mock.patch.dict(sys.modules, {"torch": fake_torch})
        patcher.start()
        self.addCleanup(patcher.stop)

    def generate(self, model):
        return get_adapter("qwen")._generate(
            model, self.FakeTokenizer(), [{"role": "user", "content": "hi"}]
        )

    def test_the_lock_is_held_while_the_model_generates(self):
        held = []
        model = self.FakeModel(lambda: held.append(languagemodel._GENERATE_LOCK.locked()))

        self.assertEqual(self.generate(model), "reply")

        self.assertEqual(held, [True])
        self.assertFalse(languagemodel._GENERATE_LOCK.locked())

    def test_the_lock_is_released_when_generation_fails(self):
        def explode():
            raise RuntimeError("out of memory")

        with self.assertRaises(RuntimeError):
            self.generate(self.FakeModel(explode))

        self.assertFalse(languagemodel._GENERATE_LOCK.locked())

    def test_two_requests_never_generate_at_the_same_time(self):
        counter = threading.Lock()
        inside = 0
        most = 0
        first_in = threading.Event()
        release = threading.Event()

        def generate_slowly():
            nonlocal inside, most
            with counter:
                inside += 1
                most = max(most, inside)
            first_in.set()
            release.wait(timeout=5)
            with counter:
                inside -= 1

        model = self.FakeModel(generate_slowly)
        results = []
        threads = [
            threading.Thread(target=lambda: results.append(self.generate(model)))
            for _ in range(2)
        ]
        threads[0].start()
        self.assertTrue(first_in.wait(timeout=5))
        threads[1].start()
        # Long enough for the second thread to get into generate if it could.
        threads[1].join(timeout=0.3)
        release.set()
        for thread in threads:
            thread.join(timeout=5)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(results, ["reply", "reply"])
        self.assertEqual(most, 1)
