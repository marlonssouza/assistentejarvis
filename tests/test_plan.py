import unittest
from types import SimpleNamespace

from jarvis import plan


class IsNoActionTests(unittest.TestCase):
    def test_empty_text_means_no_action(self):
        self.assertTrue(plan.is_no_action(""))
        self.assertTrue(plan.is_no_action("   \n  "))

    def test_marker_alone(self):
        self.assertTrue(plan.is_no_action("NENHUMA AÇÃO"))

    def test_marker_with_punctuation_and_suffix(self):
        self.assertTrue(plan.is_no_action("Nenhuma ação necessária."))
        self.assertTrue(plan.is_no_action("nenhuma acao"))

    def test_real_plan_is_not_no_action(self):
        self.assertFalse(
            plan.is_no_action("1. Abrir o Chrome\n2. Pesquisar por 'futebol'")
        )

    def test_marker_only_counts_when_it_is_the_first_line(self):
        text = "1. Abrir o Chrome\nNenhuma ação é necessária no passo 2"
        self.assertFalse(plan.is_no_action(text))


class FormatPlanTests(unittest.TestCase):
    def test_strips_surrounding_whitespace(self):
        self.assertEqual(plan.format_plan("  1. Fazer algo  \n"), "1. Fazer algo")

    def test_handles_none(self):
        self.assertEqual(plan.format_plan(None), "")


class DescribeCallsTests(unittest.TestCase):
    def test_lists_name_and_args(self):
        calls = [SimpleNamespace(name="run_command", args={"command": "dir"})]
        text = plan.describe_calls(calls)
        self.assertIn("1. run_command", text)
        self.assertIn("command=", text)

    def test_handles_calls_without_args(self):
        calls = [SimpleNamespace(name="get_datetime", args=None)]
        self.assertEqual(plan.describe_calls(calls), "1. get_datetime")

    def test_numbers_multiple_calls(self):
        calls = [
            SimpleNamespace(name="a", args={}),
            SimpleNamespace(name="b", args={}),
        ]
        self.assertEqual(plan.describe_calls(calls), "1. a\n2. b")


class NeedsApprovalTests(unittest.TestCase):
    def test_single_safe_tool_needs_no_plan(self):
        self.assertFalse(plan.needs_approval(["get_datetime"]))

    def test_single_dangerous_tool_needs_a_plan(self):
        self.assertTrue(plan.needs_approval(["run_command"]))

    def test_multiple_calls_need_a_plan(self):
        self.assertTrue(plan.needs_approval(["get_datetime", "get_system_info"]))

    def test_empty_batch_needs_no_plan(self):
        self.assertFalse(plan.needs_approval([]))


if __name__ == "__main__":
    unittest.main()
