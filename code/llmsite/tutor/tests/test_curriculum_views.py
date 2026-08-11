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

    def test_a_failure_to_invalidate_does_not_break_the_upload(self):
        """The RAG stack is optional; the dashboard has to work without it."""
        def explode():
            raise ImportError("no faiss here")

        rag.default_index.invalidate = explode
        upload = SimpleUploadedFile("new.txt", b"content", content_type="text/plain")

        response = self.post("upload_curriculum", {"title": "t", "file": upload})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "new.txt")))
