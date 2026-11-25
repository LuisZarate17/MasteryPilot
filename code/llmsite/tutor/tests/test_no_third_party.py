"""The site must not load anything from third-party servers.

Every script, stylesheet, image and font a page pulls in has to come from our
own static files. A CDN reference leaks each visitor's IP and page view to a
third party, and breaks the site on a LAN with no internet.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STATIC_DIR = Path(settings.BASE_DIR) / "static"

# src="..." or href='...', where the value is absolute or protocol-relative.
EXTERNAL_ATTR = re.compile(
    r"""(?P<tag><\s*(?P<name>[a-zA-Z0-9]+)[^>]*?\s)(?P<attr>src|href)\s*=\s*(["'])\s*(?P<url>(?:https?:)?//[^"']*)\4""",
    re.IGNORECASE,
)
EXTERNAL_IMPORT = re.compile(r"""@import\s+(?:url\(\s*)?["']?\s*(?:https?:)?//""", re.IGNORECASE)
STATIC_REF = re.compile(r"""\{%\s*static\s+(["'])(?P<path>[^"']+)\1\s*%\}""")

# Built separately (prebuilt Tailwind), so it may not exist in a checkout that
# has not run the CSS build yet.
NOT_COMMITTED = {"css/app.css"}


def template_files():
    return sorted(p for p in TEMPLATES_DIR.rglob("*") if p.is_file())


def line_of(text, index):
    return text.count("\n", 0, index) + 1


class NoThirdPartyTests(SimpleTestCase):
    def test_templates_found(self):
        self.assertTrue(template_files(), "no templates found; the test would pass vacuously")

    def test_no_external_src_or_href(self):
        problems = []
        for path in template_files():
            text = path.read_text(encoding="utf-8")
            for m in EXTERNAL_ATTR.finditer(text):
                # A plain <a href> is a link for a human to click, not a load.
                if m.group("name").lower() == "a" and m.group("attr").lower() == "href":
                    continue
                problems.append(
                    f"{path.relative_to(TEMPLATES_DIR)}:{line_of(text, m.start('attr'))}: "
                    f"{m.group('attr')}={m.group('url')}"
                )
        self.assertEqual(problems, [], "third-party resources in templates:\n" + "\n".join(problems))

    def test_no_external_css_import(self):
        problems = []
        for path in template_files():
            text = path.read_text(encoding="utf-8")
            for m in EXTERNAL_IMPORT.finditer(text):
                problems.append(f"{path.relative_to(TEMPLATES_DIR)}:{line_of(text, m.start())}")
        self.assertEqual(problems, [], "external @import in templates:\n" + "\n".join(problems))

    def test_referenced_static_files_exist(self):
        refs = 0
        missing = []
        for path in template_files():
            text = path.read_text(encoding="utf-8")
            for m in STATIC_REF.finditer(text):
                rel = m.group("path")
                refs += 1
                if rel in NOT_COMMITTED:
                    continue
                if not (STATIC_DIR / rel).is_file():
                    missing.append(f"{path.relative_to(TEMPLATES_DIR)}:{line_of(text, m.start())}: {rel}")
        self.assertGreater(refs, 0, "no {% static %} references found; the test would pass vacuously")
        self.assertEqual(missing, [], "static files referenced but missing:\n" + "\n".join(missing))


class WhiteNoiseSettingsTests(SimpleTestCase):
    def test_whitenoise_directly_after_security_middleware(self):
        mw = settings.MIDDLEWARE
        security = mw.index("django.middleware.security.SecurityMiddleware")
        self.assertEqual(mw[security + 1], "whitenoise.middleware.WhiteNoiseMiddleware")
