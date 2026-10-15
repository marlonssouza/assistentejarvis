import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis import memory, persona


def _record(fact_id: str, text: str, aspect: str) -> dict:
    return {"id": fact_id, "text": text, "aspect": aspect}


class PersonaTests(unittest.TestCase):
    def test_build_persona_groups_by_aspect_with_labels(self):
        records = [
            _record("1", "Marcelo", "identity"),
            _record("2", "prefiro respostas curtas", "preference"),
            _record("3", "nunca use jargão", "directive"),
        ]
        text = persona.build_persona(records)
        self.assertIn("PERFIL DO USUÁRIO", text)
        self.assertIn("Identidade: Marcelo", text)
        self.assertIn("Preferências: prefiro respostas curtas", text)
        self.assertIn("Diretrizes: nunca use jargão", text)

    def test_build_persona_is_empty_without_records(self):
        self.assertEqual(persona.build_persona([]), "")

    def test_persona_block_returns_empty_when_disabled(self):
        with patch.object(persona, "PERSONA_ENABLED", False):
            self.assertEqual(persona.persona_block(), "")

    def test_persona_block_uses_store(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = memory.Memory(Path(temp_dir) / "memory.json")
            store.add_fact("meu nome é Marcelo", aspect="identity")
            with (
                patch.object(persona, "PERSONA_ENABLED", True),
                patch.object(persona.memory, "get_store", return_value=store),
            ):
                text = persona.persona_block()
        self.assertIn("Marcelo", text)

    def test_relevant_facts_block_ignores_empty_query(self):
        self.assertEqual(persona.relevant_facts_block(""), "")

    def test_relevant_facts_block_returns_matches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = memory.Memory(Path(temp_dir) / "memory.json")
            store.add_fact("trabalho com Python", aspect="knowledge")
            with patch.object(persona.memory, "get_store", return_value=store):
                text = persona.relevant_facts_block("Python")
        self.assertIn("Python", text)
        self.assertIn("FATOS RELEVANTES", text)


if __name__ == "__main__":
    unittest.main()
