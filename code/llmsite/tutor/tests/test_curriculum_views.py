"""The dashboard's curriculum library, and its coupling to the search index.

Uploading or deleting a document has to reach the retrieval index. Without
that, a teacher deletes a file, watches it disappear from the dashboard, and
the tutor carries on quoting it — the failure being that the two views of the
same library disagree and only one of them is visible.

CURRICULUM_ROOT is overridden to a temporary directory throughout. The real one
is inside the repository, and a delete test pointed at it would remove real
files.
"""

import os
import shutil
import tempfile
from unittest import mock

from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

import rag

from .base import MasteryPilotTestCase


class CurriculumInvalidationTests(MasteryPilotTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="curriculum-views-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

        self.invalidations = []
        rag.default_index.invalidate = lambda: self.invalidations.append("invalidate")
        # Drop the instance attribute rather than reassigning, so the class
        # method is reachable again afterwards.
        self.addCleanup(rag.default_index.__dict__.pop, "invalidate", None)

        # The rebuild after a change needs an embedder, which the test run has
        # not got; the real one is exercised in test_rag.
        patcher = mock.patch.object(rag, "ensure_curriculum_loaded")
        self.rebuild = patcher.start()
        self.addCleanup(patcher.stop)

        self.client.force_login(self.make_admin())

    def post(self, name, data):
        with override_settings(CURRICULUM_ROOT=self.tmp):
            return self.client.post(reverse(name), data)

    def write(self, name, content="content"):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path

    def test_deleting_a_document_invalidates_the_index(self):
        path = self.write("doomed.txt")

        self.post("curriculum_delete", {"filename": "doomed.txt"})

        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.invalidations, ["invalidate"])

    def test_uploading_a_document_invalidates_the_index(self):
        upload = SimpleUploadedFile("new.txt", b"Fractions divide a whole.", content_type="text/plain")

        self.post("upload_curriculum", {"title": "Fractions", "file": upload})

        self.assertTrue(os.path.exists(os.path.join(self.tmp, "new.txt")))
        self.assertEqual(self.invalidations, ["invalidate"])

    def test_deleting_something_that_is_not_there_changes_nothing(self):
        self.post("curriculum_delete", {"filename": "never_existed.txt"})

        self.assertEqual(self.invalidations, [])

    def test_a_rejected_upload_does_not_invalidate(self):
        """Nothing reached the corpus, so nothing needs reindexing."""
        upload = SimpleUploadedFile("script.exe", b"MZ", content_type="application/octet-stream")

        self.post("upload_curriculum", {"title": "bad", "file": upload})

        self.assertEqual(self.invalidations, [])

    def upload(self, name, content_type, content=b"Fractions divide a whole."):
        self.post(
            "upload_curriculum",
            {"title": "t", "file": SimpleUploadedFile(name, content, content_type=content_type)},
        )
        return os.path.exists(os.path.join(self.tmp, name))

    def test_every_indexable_format_can_be_uploaded(self):
        """rag knew how to read these long before the dashboard would accept them.

        md, docx and json had working, tested extractors that no upload could
        ever reach — the only way in was copying a file onto the server by hand.
        """
        cases = [
            ("a.txt", "text/plain"),
            ("b.md", "text/markdown"),
            ("c.json", "application/json"),
            ("d.pdf", "application/pdf"),
            ("e.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ]
        for name, content_type in cases:
            with self.subTest(name=name):
                self.assertTrue(self.upload(name, content_type))

    def test_every_uploadable_extension_has_an_extractor(self):
        """The two lists have to agree, or an upload is accepted and never read."""
        from tutor.views.curriculum import ALLOWED_UPLOAD_TYPES

        uploadable = {f".{ext}" for ext in ALLOWED_UPLOAD_TYPES}

        self.assertTrue(uploadable <= set(rag.EXTRACTORS), uploadable - set(rag.EXTRACTORS))

    def test_browser_content_type_variants_are_accepted(self):
        """Firefox sends octet-stream for .md; Chrome sends text/markdown or nothing."""
        for content_type in ("text/markdown", "text/plain", "application/octet-stream", ""):
            with self.subTest(content_type=content_type):
                self.assertTrue(self.upload(f"n{len(content_type)}.md", content_type))

    def test_a_charset_parameter_does_not_defeat_the_check(self):
        self.assertTrue(self.upload("charset.txt", "text/plain; charset=utf-8"))

    def test_an_unsupported_extension_is_still_refused(self):
        self.assertFalse(self.upload("macro.xlsm", "application/vnd.ms-excel.sheet.macroEnabled.12"))

    def test_a_content_type_implausible_for_its_extension_is_refused(self):
        self.assertFalse(self.upload("claims.pdf", "text/plain"))

    def test_a_failure_to_invalidate_does_not_break_the_upload(self):
        """The RAG stack is optional; the dashboard has to work without it."""
        def explode():
            raise ImportError("no faiss here")

        rag.default_index.invalidate = explode
        upload = SimpleUploadedFile("new.txt", b"content", content_type="text/plain")

        response = self.post("upload_curriculum", {"title": "t", "file": upload})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "new.txt")))

    def levels_and_texts(self, response):
        return [(m.level_tag, str(m)) for m in get_messages(response.wsgi_request)]

    def test_uploading_a_document_rebuilds_the_index_for_the_curriculum_root(self):
        upload = SimpleUploadedFile("new.txt", b"Fractions divide a whole.", content_type="text/plain")

        self.post("upload_curriculum", {"title": "Fractions", "file": upload})

        self.rebuild.assert_called_once_with(self.tmp)

    def test_deleting_a_document_rebuilds_the_index_for_the_curriculum_root(self):
        self.write("doomed.txt")

        self.post("curriculum_delete", {"filename": "doomed.txt"})

        self.rebuild.assert_called_once_with(self.tmp)

    def test_a_rejected_upload_does_not_rebuild(self):
        upload = SimpleUploadedFile("script.exe", b"MZ", content_type="application/octet-stream")

        self.post("upload_curriculum", {"title": "bad", "file": upload})

        self.rebuild.assert_not_called()

    def test_a_failed_rebuild_does_not_fail_the_upload_and_says_so(self):
        self.rebuild.side_effect = RuntimeError("embedder would not load")
        upload = SimpleUploadedFile("new.txt", b"content", content_type="text/plain")

        with self.assertLogs("tutor.views.curriculum", level="WARNING"):
            response = self.post("upload_curriculum", {"title": "t", "file": upload})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "new.txt")))
        found = self.levels_and_texts(response)
        self.assertEqual([level for level, _ in found], ["success", "warning"])
        self.assertEqual(found[0][1], "Uploaded new.txt.")
        self.assertIn("search index could not be updated", found[1][1])

    def test_a_failed_rebuild_does_not_fail_the_delete_and_says_so(self):
        path = self.write("doomed.txt")
        self.rebuild.side_effect = RuntimeError("embedder would not load")

        with self.assertLogs("tutor.views.curriculum", level="WARNING"):
            response = self.post("curriculum_delete", {"filename": "doomed.txt"})

        self.assertEqual(response.status_code, 302)
        self.assertFalse(os.path.exists(path))
        self.assertEqual([level for level, _ in self.levels_and_texts(response)], ["warning"])

    def test_a_good_rebuild_adds_no_warning(self):
        upload = SimpleUploadedFile("new.txt", b"content", content_type="text/plain")

        response = self.post("upload_curriculum", {"title": "t", "file": upload})

        self.assertEqual([level for level, _ in self.levels_and_texts(response)], ["success"])
