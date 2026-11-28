"""Chat page accessibility, keyboard use, mobile height and error display.

The project has no JavaScript test runner, so these read the template (and the
built stylesheet) as text and assert on it, the way test_session_titles.py
does. They stop the markup and script that screen-reader and keyboard users
rely on from being dropped in a later edit.
"""

import re
from pathlib import Path

from .base import MasteryPilotTestCase

TUTOR = Path(__file__).resolve().parents[1]
CHAT_HTML = TUTOR / "templates" / "chat.html"
APP_CSS = TUTOR.parent / "static" / "css" / "app.css"


def function_body(source, signature):
    """Source of one JS function, from its signature to the next top-level function."""
    start = source.index(signature)
    match = re.search(r"\n  (?:async )?function \w+\(", source[start + len(signature):])
    end = start + len(signature) + match.start() if match else len(source)
    return source[start:end]


class ChatPageTestCase(MasteryPilotTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = CHAT_HTML.read_text(encoding="utf-8")
        cls.css = APP_CSS.read_text(encoding="utf-8")


class ScreenReaderMarkupTests(ChatPageTestCase):
    def test_the_chat_log_is_a_polite_labelled_log(self):
        tag = re.search(r'<div id="chatLog"[^>]*>', self.source).group(0)

        self.assertIn('role="log"', tag)
        self.assertIn('aria-live="polite"', tag)
        self.assertIn('aria-label="Conversation"', tag)

    def test_the_message_input_has_a_label(self):
        self.assertIn(
            '<label for="chatInput" class="sr-only">Message to your tutor</label>',
            self.source,
        )
        self.assertIn('<input id="chatInput"', self.source)

    def test_the_typing_alert_is_a_status_region(self):
        tag = re.search(r'<div id="typing-alert-div"[^>]*>', self.source).group(0)

        self.assertIn('role="status"', tag)

    def test_the_quiz_modal_is_a_dialog_named_by_its_heading(self):
        tag = re.search(r'<div id="quizFeedbackModal"[^>]*>', self.source).group(0)

        self.assertIn('role="dialog"', tag)
        self.assertIn('aria-modal="true"', tag)
        labelled_by = re.search(r'aria-labelledby="([^"]+)"', tag).group(1)
        self.assertRegex(self.source, rf'<h3 id="{re.escape(labelled_by)}"[^>]*>Quiz Results</h3>')

    def test_the_quiz_result_glyphs_are_hidden_from_screen_readers(self):
        body = function_body(self.source, "function showQuizFeedbackModal(")

        self.assertIn("<span aria-hidden='true' class='inline-block h-6 w-6 bg-brand-600", body)
        self.assertIn("<span aria-hidden='true' class='inline-block h-6 w-6 bg-red-500", body)

    def test_loading_history_marks_the_log_busy_and_clears_it_in_finally(self):
        body = function_body(self.source, "async function loadSessionMessages(")

        self.assertIn('chatLog.setAttribute("aria-busy", "true");', body)
        self.assertLess(
            body.index('"aria-busy", "true"'), body.index('chatLog.innerHTML = ""')
        )
        finally_block = body[body.index("} finally {"):]
        self.assertIn('chatLog.setAttribute("aria-busy", "false");', finally_block)


class SessionListKeyboardTests(ChatPageTestCase):
    def setUp(self):
        self.item = function_body(self.source, "function renderSessionListItem(")

    def test_rename_and_delete_buttons_are_labelled_buttons(self):
        self.assertIn('type="button" class="rename-btn', self.item)
        self.assertIn('aria-label="Rename this chat" title="Rename this chat">✏️</button>', self.item)
        self.assertIn('type="button" class="delete-btn', self.item)
        self.assertIn('aria-label="Delete this chat" title="Delete this chat">🗑️</button>', self.item)

    def test_the_session_title_is_a_real_button_that_keeps_the_title_span(self):
        self.assertIn('<button type="button" class="session-open flex-1 text-left', self.item)
        self.assertIn("focus-visible:ring-2 focus-visible:ring-brand-500", self.item)
        self.assertRegex(
            self.item,
            r'<button type="button" class="session-open[^>]*><span class="session-title">'
            r"\$\{escapeHtml\(session\.title\)\}</span></button>",
        )

    def test_the_session_li_opens_the_chat_once_for_clicks_on_the_button(self):
        # The button has no handler of its own: its clicks bubble to the li.
        self.assertEqual(self.item.count("loadSessionMessages(session.id)"), 1)
        self.assertEqual(self.item.count("addEventListener"), 1)

    def test_the_open_chat_is_marked_with_aria_current(self):
        marker = function_body(self.source, "function markActiveSession(")
        loader = function_body(self.source, "async function loadSessionMessages(")

        self.assertIn('setAttribute("aria-current", "true")', marker)
        self.assertIn('removeAttribute("aria-current")', marker)
        self.assertIn("markActiveSession(sessionId);", loader)


class QuizModalFocusTests(ChatPageTestCase):
    def test_escape_closes_the_modal_through_the_shared_close_function(self):
        self.assertIn('e.key === "Escape"', self.source)
        self.assertIn(
            'closeQuizFeedback.addEventListener("click", closeQuizFeedbackModal);', self.source
        )
        keydown = self.source[self.source.index('document.addEventListener("keydown"'):]
        self.assertIn("closeQuizFeedbackModal();", keydown.split('e.key !== "Tab"')[0])

    def test_tab_is_kept_inside_the_modal(self):
        keydown = self.source[self.source.index('document.addEventListener("keydown"'):]

        self.assertIn('e.key !== "Tab"', keydown)
        self.assertIn("e.shiftKey && document.activeElement === first", keydown)
        self.assertIn("last.focus();", keydown)

    def test_opening_focuses_close_and_closing_restores_focus(self):
        opening = function_body(self.source, "function showQuizFeedbackModal(")
        closing = function_body(self.source, "function closeQuizFeedbackModal(")

        self.assertIn("quizModalOpener = document.activeElement;", opening)
        self.assertIn("closeQuizFeedback.focus();", opening)
        self.assertIn("document.contains(opener)", closing)
        self.assertIn("(canFocusOpener ? opener : chatInput).focus();", closing)


class MobileHeightTests(ChatPageTestCase):
    def test_the_chat_section_uses_dvh_where_the_browser_knows_it(self):
        self.assertIn("h-[calc(100vh-7.5rem)]", self.source)
        self.assertIn("supports-[height:100dvh]:h-[calc(100dvh-7.5rem)]", self.source)

    def test_the_built_stylesheet_has_the_dvh_rule_inside_supports(self):
        self.assertRegex(
            self.css,
            r"@supports \(height:100dvh\)\{[^}]*height:calc\(100dvh - 7\.5rem\)",
        )

    def test_the_built_stylesheet_has_the_screen_reader_and_notice_classes(self):
        for name in ("sr-only", "bg-amber-50", "border-amber-300", "text-amber-900"):
            with self.subTest(name=name):
                self.assertRegex(self.css, rf"\.{re.escape(name)}\{{")


class FailureDisplayTests(ChatPageTestCase):
    def test_a_model_error_is_shown_as_a_notice_not_a_tutor_bubble(self):
        self.assertIn(
            'appendNotice(data.model_text || "The tutor could not answer. Please try again.")',
            self.source,
        )

    def test_no_failure_is_dressed_up_as_a_tutor_message(self):
        self.assertNotIn('appendMessage("model", "Error', self.source)
        self.assertNotIn('showQuizFeedbackModal("Error', self.source)

    def test_failed_replies_still_restore_the_students_message(self):
        submit = self.source[
            self.source.index('chatForm.addEventListener("submit"'):
            self.source.index("// --- Quiz parsing helpers ---")
        ]

        self.assertIn("if (data.error) restoreMessage();", submit)
        self.assertIn("appendNotice(await describeFailure(res));", submit)
        self.assertIn("appendNotice(describeNetworkError(err));", submit)
        self.assertEqual(submit.count("restoreMessage();"), 3)

    def test_the_notice_is_amber_and_set_as_text(self):
        body = function_body(self.source, "function appendNotice(")

        self.assertIn('div.className = "chat-notice', body)
        for name in ("bg-amber-50", "border-amber-300", "text-amber-900"):
            self.assertIn(name, body)
        self.assertIn("document.createTextNode(", body)
        self.assertNotIn("innerHTML", body)
        self.assertIn('glyph.setAttribute("aria-hidden", "true");', body)

    def test_describe_failure_never_puts_raw_text_on_the_page_as_html(self):
        body = function_body(self.source, "async function describeFailure(")

        self.assertNotIn("innerHTML", body)
        self.assertIn('startsWith("<")', body)
        self.assertIn("body.length <= 300", body)
        self.assertIn("The tutor could not answer (error ${res.status}). Please try again.", body)

    def test_a_network_failure_gets_a_plain_message(self):
        body = function_body(self.source, "function describeNetworkError(")

        self.assertIn("Could not reach the server. Check your connection and try again.", body)

    def test_quiz_grading_failures_show_the_friendly_message_in_the_modal(self):
        grading = self.source[
            self.source.index("submitQuizBtn.addEventListener"):
            self.source.index("// Build a quizAttempt shaped like")
        ]

        self.assertIn("showQuizFeedbackModal(await describeFailure(res));", grading)
        self.assertIn("showQuizFeedbackModal(describeNetworkError(err));", grading)

    def test_loading_a_chat_reports_failures_as_notices(self):
        body = function_body(self.source, "async function loadSessionMessages(")

        self.assertIn("appendNotice(await describeFailure(initRes));", body)
        self.assertIn("appendNotice(describeNetworkError(err));", body)


class SlowReplyTests(ChatPageTestCase):
    def test_the_typing_alert_admits_a_slow_reply_after_twenty_seconds(self):
        body = function_body(self.source, "function showTypingAlert(")

        self.assertIn("Still working on it. Replies can take a minute or two.", body)
        self.assertIn("}, 20000);", body)

    def test_removing_the_typing_alert_stops_the_timer(self):
        body = function_body(self.source, "function removeTypingAlert(")

        self.assertIn("clearTimeout(slowReplyTimer);", body)

    def test_a_slow_reply_is_never_aborted(self):
        self.assertNotIn("AbortController", self.source)
