import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return json.load(fh)


class TestManifests(unittest.TestCase):
    def test_plugin_manifest(self):
        m = load(".claude-plugin/plugin.json")
        self.assertEqual(m["name"], "sandbox-audit")
        self.assertIn("version", m)

    def test_marketplace_manifest_lists_plugin(self):
        m = load(".claude-plugin/marketplace.json")
        names = [p["name"] for p in m["plugins"]]
        self.assertIn("sandbox-audit", names)

    def test_hooks_register_session_end(self):
        h = load("hooks/hooks.json")
        self.assertIn("SessionEnd", h["hooks"])
        cmd = h["hooks"]["SessionEnd"][0]["hooks"][0]["command"]
        self.assertIn("session-end.sh", cmd)
        self.assertIn("CLAUDE_PLUGIN_ROOT", cmd)

    def test_skill_exists(self):
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "skills/doctor/SKILL.md")))


if __name__ == "__main__":
    unittest.main()
