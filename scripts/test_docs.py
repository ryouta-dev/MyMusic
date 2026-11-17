"""Regression check for the documentation handoff package."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILES = ['README.md', 'docs/01-product.md', 'docs/02-architecture.md',
         'docs/03-sources-decisions.md', 'docs/04-agent-handoff.md']

class DocumentationTests(unittest.TestCase):
    def test_documents_are_complete_utf8(self):
        for name in FILES:
            with self.subTest(document=name):
                text = (ROOT / name).read_text(encoding='utf-8-sig')
                self.assertTrue(text.startswith('# '))
                self.assertGreater(len(text), 500)
                for marker in ('\ufffd', 'TODO', 'Lorem ipsum', '[74 lines', '[60 lines'):
                    self.assertNotIn(marker, text)

    def test_local_links_resolve(self):
        for name in FILES:
            path = ROOT / name
            for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', path.read_text(encoding='utf-8-sig')):
                if not target.startswith(('https://', 'http://', '#')):
                    with self.subTest(document=name, link=target):
                        self.assertTrue((path.parent / target.split('#')[0]).is_file())

if __name__ == '__main__':
    unittest.main()
