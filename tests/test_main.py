import unittest

from main import classify_command


class MainTests(unittest.TestCase):
    def test_exit_commands_are_recognized(self):
        self.assertEqual(classify_command("Sair"), "exit")
        self.assertEqual(classify_command(" TCHAU "), "exit")
        self.assertEqual(classify_command("até logo"), "exit")

    def test_reset_commands_are_recognized(self):
        self.assertEqual(classify_command("limpar conversa"), "reset")
        self.assertEqual(classify_command("Reset"), "reset")

    def test_regular_query_is_not_a_command(self):
        self.assertEqual(classify_command("que horas são?"), "query")
        self.assertEqual(classify_command("abrir o navegador"), "query")


if __name__ == "__main__":
    unittest.main()
