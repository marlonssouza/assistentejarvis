import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis import policies


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _write(self, name: str, content: str) -> Path:
        path = self.dir / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_front_matter_is_parsed(self):
        self._write(
            "email.md",
            "---\ntitle: E-mail importante\ndescription: O que é urgente\n---\n"
            "Sempre sinalize clientes.",
        )
        loaded = policies.list_policies(self.dir)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].title, "E-mail importante")
        self.assertEqual(loaded[0].description, "O que é urgente")
        self.assertIn("clientes", loaded[0].body)

    def test_heading_and_first_line_are_used_without_front_matter(self):
        self._write("estilo.md", "# Como respondo\nDireto e curto\n\nSem rodeios.\n")
        policy = policies.list_policies(self.dir)[0]
        self.assertEqual(policy.title, "Como respondo")
        self.assertEqual(policy.description, "Direto e curto")
        self.assertNotIn("# Como respondo", policy.body)

    def test_missing_directory_returns_empty(self):
        self.assertEqual(policies.list_policies(self.dir / "nao-existe"), [])

    def test_non_markdown_files_are_ignored(self):
        self._write("notas.txt", "texto qualquer")
        self.assertEqual(policies.list_policies(self.dir), [])

    def test_match_ranks_relevant_policy_first(self):
        self._write(
            "email.md",
            "---\ntitle: E-mail\ndescription: urgente cliente\n---\nTriage.\n",
        )
        self._write(
            "codigo.md",
            "---\ntitle: Código\ndescription: revisão\n---\nCommits pequenos.\n",
        )
        matches = policies.match_policies("me ajuda com e-mail urgente", directory=self.dir)
        self.assertEqual(matches[0].name, "email")

    def test_match_without_query_returns_first_limits(self):
        self._write("a.md", "---\ntitle: A\n---\nconteúdo a\n")
        self._write("b.md", "---\ntitle: B\n---\nconteúdo b\n")
        self.assertEqual([p.name for p in policies.match_policies("", limit=1, directory=self.dir)], ["a"])

    def test_policies_block_is_empty_without_matches_or_files(self):
        with patch.object(policies, "SKILLS_DIR", self.dir):
            self.assertEqual(policies.policies_block("qualquer", limit=3), "")

    def test_policies_block_includes_title(self):
        self._write("email.md", "---\ntitle: E-mail importante\ndescription: urgente\n---\nCorpo.\n")
        with patch.object(policies, "SKILLS_DIR", self.dir):
            block = policies.policies_block("e-mail urgente", limit=3)
        self.assertIn("E-mail importante", block)
        self.assertIn("POLÍTICAS", block)


if __name__ == "__main__":
    unittest.main()
