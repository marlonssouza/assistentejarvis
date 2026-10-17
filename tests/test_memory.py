import asyncio
import json
import threading
import time
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from jarvis.memory import Memory


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "memory.json"

    def test_messages_persist_across_instances(self):
        first = Memory(self.path)
        first.add_message("user", "oi")
        first.add_message("model", "olá")

        second = Memory(self.path)
        self.assertEqual(
            second.messages(),
            [{"role": "user", "text": "oi"}, {"role": "model", "text": "olá"}],
        )

    def test_facts_are_deduplicated(self):
        store = Memory(self.path)
        self.assertTrue(store.add_fact("gosta de café"))
        self.assertFalse(store.add_fact("gosta de café"))
        self.assertEqual(store.facts(), ["gosta de café"])

    def test_clear_messages_keeps_facts(self):
        store = Memory(self.path)
        store.add_message("user", "oi")
        store.add_fact("fato")
        store.clear_messages()
        self.assertEqual(store.messages(), [])
        self.assertEqual(store.facts(), ["fato"])

    def test_corrupted_file_starts_empty(self):
        self.path.write_text("não é json", encoding="utf-8")
        store = Memory(self.path)
        self.assertEqual(store.messages(), [])
        self.assertEqual(store.facts(), [])

    def test_legacy_string_facts_are_migrated(self):
        self.path.write_text(
            json.dumps({"messages": [], "facts": ["gosta de café"]}),
            encoding="utf-8",
        )
        store = Memory(self.path)
        self.assertEqual(store.facts(), ["gosta de café"])
        record = store.records()[0]
        self.assertEqual(record["aspect"], "knowledge")
        self.assertEqual(record["source"], "legacy")
        self.assertTrue(record["id"])

    def test_aspect_is_inferred_when_not_given(self):
        store = Memory(self.path)
        store.add_fact("prefiro respostas curtas")
        self.assertEqual(store.records()[0]["aspect"], "preference")

    def test_explicit_aspect_is_kept(self):
        store = Memory(self.path)
        store.add_fact("objetivo do trimestre", aspect="goal", source="user")
        record = store.records()[0]
        self.assertEqual(record["aspect"], "goal")
        self.assertEqual(record["source"], "user")
        self.assertTrue(record["created_at"])

    def test_supersession_preserves_history(self):
        store = Memory(self.path)
        store.add_fact("meu nome é Marcelo", aspect="identity")
        old_id = store.records()[0]["id"]

        self.assertTrue(
            store.add_fact(
                "meu nome é Marcelo Santos", aspect="identity", supersedes=old_id
            )
        )
        self.assertEqual(store.facts(), ["meu nome é Marcelo Santos"])

        everything = store.records(include_superseded=True)
        self.assertEqual(len(everything), 2)
        superseded = [record for record in everything if record["superseded_by"]]
        self.assertEqual(len(superseded), 1)
        self.assertEqual(superseded[0]["id"], old_id)
        self.assertTrue(superseded[0]["superseded_at"])

    def test_supersede_creates_new_active_fact(self):
        store = Memory(self.path)
        store.add_fact("moro em São Paulo")
        old_id = store.records()[0]["id"]
        store.supersede(old_id, "moro no Rio de Janeiro")

        reloaded = Memory(self.path)
        self.assertEqual(reloaded.facts(), ["moro no Rio de Janeiro"])
        self.assertEqual(len(reloaded.records(include_superseded=True)), 2)

    def test_supersede_unknown_id_returns_false(self):
        store = Memory(self.path)
        self.assertFalse(store.supersede("inexistente", "novo fato"))

    def test_search_facts_ranks_by_relevance(self):
        store = Memory(self.path)
        store.add_fact("eu trabalho com Python")
        store.add_fact("meu cachorro se chama Rex")

        results = store.search_facts("você lembra de Python?")
        self.assertEqual(results[0]["text"], "eu trabalho com Python")

    def test_search_facts_empty_query_returns_recent_first(self):
        store = Memory(self.path)
        store.add_fact("primeiro")
        store.add_fact("segundo")
        results = store.search_facts("")
        self.assertEqual(results[0]["text"], "segundo")

    def test_remove_fact(self):
        store = Memory(self.path)
        store.add_fact("descartável")
        fact_id = store.records()[0]["id"]
        self.assertTrue(store.remove_fact(fact_id))
        self.assertFalse(store.remove_fact(fact_id))
        self.assertEqual(store.facts(), [])

    def test_concurrent_writes_preserve_all_facts_and_valid_json(self):
        store = Memory(self.path)
        barrier = threading.Barrier(12)

        def add_fact(index):
            barrier.wait()
            store.add_fact(f"fato concorrente {index}")

        with ThreadPoolExecutor(max_workers=12) as executor:
            list(executor.map(add_fact, range(12)))

        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(saved["facts"]), 12)
        self.assertEqual(len(store.facts()), 12)

    def test_failed_atomic_replace_preserves_previous_file_and_cleans_temp(self):
        store = Memory(self.path)
        store.add_fact("persistido")
        previous_content = self.path.read_bytes()

        with patch("jarvis.memory.os.replace", side_effect=OSError("replace failed")):
            store.add_fact("não persistido")

        self.assertEqual(self.path.read_bytes(), previous_content)
        self.assertEqual(list(self.path.parent.glob(".memory.json.*.tmp")), [])
        self.assertEqual(Memory(self.path).facts(), ["persistido"])


class AsyncMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_async_serializes_memory_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Memory(Path(directory) / "memory.json")
            active = 0
            max_active = 0
            state_lock = threading.Lock()

            def operation():
                nonlocal active, max_active
                with state_lock:
                    active += 1
                    max_active = max(max_active, active)
                time.sleep(0.02)
                with state_lock:
                    active -= 1

            await asyncio.gather(
                *(store.run_async(operation) for _ in range(5))
            )

        self.assertEqual(max_active, 1)


if __name__ == "__main__":
    unittest.main()
