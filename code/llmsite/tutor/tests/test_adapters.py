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

from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import textwrap
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
