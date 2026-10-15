import unittest

from jarvis import skills
from jarvis.hands import TOOL_RISK


class SkillsTests(unittest.TestCase):
    def test_payload_lists_groups_with_items(self):
        payload = skills.skills_payload()

        self.assertGreater(payload["total"], 0)
        self.assertTrue(payload["groups"])
        self.assertEqual(
            payload["total"], sum(len(group["items"]) for group in payload["groups"])
        )

    def test_every_skill_has_risk_and_example(self):
        payload = skills.skills_payload()
        for group in payload["groups"]:
            self.assertTrue(group["title"])
            for item in group["items"]:
                self.assertIn(item["risk"], {"safe", "dangerous"})
                self.assertTrue(item["risk_label"])
                self.assertTrue(item["example"])
                self.assertEqual(item["risk"], skills.TOOL_RISK.get(item["tool"]))

    def test_every_skill_points_to_a_known_tool(self):
        payload = skills.skills_payload()
        for group in payload["groups"]:
            for item in group["items"]:
                self.assertIn(item["tool"], skills.TOOL_RISK)


if __name__ == "__main__":
    unittest.main()
