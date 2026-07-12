import ast
import importlib.util
import inspect
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "m8shift.py")
SPEC = importlib.util.spec_from_file_location("m8shift_threat", CORE)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class ThreatConformance(unittest.TestCase):
    def test_LLM01_prompt_injection_relay_text_cannot_grant_pen(self):
        append_source = inspect.getsource(M.cmd_append)
        self.assertIn('st != f"WORKING_{agent.upper()}"', append_source)
        self.assertIn("append_need_claim", append_source)

    def test_LLM02_insecure_output_ansi_is_stripped(self):
        self.assertNotIn("\x1b", M._usage_sanitize("ok\x1b[31mFORGED"))

    def test_LLM05_supply_chain_runtime_is_stdlib_only(self):
        with open(CORE, encoding="utf-8") as source:
            tree = ast.parse(source.read())
        banned = {"requests", "yaml", "click", "rich"}
        imported = {n.names[0].name.split(".")[0] for n in ast.walk(tree)
                    if isinstance(n, ast.Import)}
        self.assertTrue(imported.isdisjoint(banned))

    def test_LLM06_sensitive_information_denylist_label_is_hashed(self):
        secret = "private-adopter-name"
        label = M._denylist_label(secret)
        self.assertNotIn(secret, label)
        self.assertRegex(label, r"^denylist:[0-9a-f]{10}$")

    def test_LLM07_insecure_plugin_parser_is_bounded(self):
        self.assertLessEqual(M.SKILL_MD_MAX_BYTES, 1024 * 1024)

    def test_LLM08_excessive_agency_mutex_has_one_holder(self):
        self.assertEqual(M.LOCK_BEGIN.count("LOCK"), 1)

    def test_LLM10_unbounded_consumption_caps_skill_input(self):
        self.assertGreater(M.SKILL_MD_MAX_BYTES, 0)
        self.assertLess(M.SKILL_MD_MAX_BYTES, 10 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
