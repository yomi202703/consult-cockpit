"""Smoke tests — stdlib unittest, no network, no keychain writes.

    python3 -m unittest discover tests

Covers the pure layers: repo_fetch (path safety, command execution, brief),
env (key-precedence helpers), llm_client (adapter parse + lane resolution with
a stubbed keychain).
"""
import os
import sys
import tempfile
import unittest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

import env as cockpit_env            # noqa: E402
import llm_client                    # noqa: E402
import repo_fetch                    # noqa: E402


class RepoFetchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        with open(os.path.join(self.root, "a.py"), "w") as f:
            f.write("alpha = 1\nbeta = 2\n")
        os.mkdir(os.path.join(self.root, "sub"))
        with open(os.path.join(self.root, "sub", "b.txt"), "w") as f:
            f.write("needle here\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_safe_blocks_escape(self):
        self.assertIsNone(repo_fetch.safe(self.root, "../etc/passwd"))
        self.assertIsNotNone(repo_fetch.safe(self.root, "sub/b.txt"))

    def test_run_commands_read_grep_ls_tree(self):
        out = repo_fetch.run_commands(self.root, [
            "READ a.py", "GREP needle", "LS sub", "TREE"])
        self.assertIn("alpha = 1", out)
        self.assertIn("sub/b.txt:1: needle here", out)
        self.assertIn("### LS sub", out)
        self.assertIn("### TREE", out)

    def test_run_commands_ignores_junk_and_reports_missing(self):
        out = repo_fetch.run_commands(self.root, ["chatter", "READ nope.py"])
        self.assertIn("(not found: nope.py)", out)

    def test_build_brief_contains_protocol_tree_task(self):
        brief = repo_fetch.build_brief(self.root, "find the bug")
        self.assertIn("fenced code block tagged", brief)
        self.assertIn("a.py", brief)
        self.assertIn("find the bug", brief)


class EnvPrecedenceTest(unittest.TestCase):
    def test_from_live_env_distinguishes_injected(self):
        cockpit_env._injected.add("TEST_INJECTED_VAR")
        os.environ["TEST_INJECTED_VAR"] = "from-dotenv"
        os.environ["TEST_LIVE_VAR"] = "explicit"
        try:
            self.assertIsNone(cockpit_env.from_live_env("TEST_INJECTED_VAR"))
            self.assertEqual(cockpit_env.from_live_env("TEST_LIVE_VAR"), "explicit")
            self.assertIsNone(cockpit_env.from_live_env("TEST_ABSENT_VAR"))
        finally:
            os.environ.pop("TEST_INJECTED_VAR", None)
            os.environ.pop("TEST_LIVE_VAR", None)
            cockpit_env._injected.discard("TEST_INJECTED_VAR")

    def test_parse_handles_export_quotes_comments(self):
        parsed = cockpit_env._parse(
            '# comment\nexport A="v1"\nB=\'v2\'\nnoequals\nC=v3\n')
        self.assertEqual(parsed, {"A": "v1", "B": "v2", "C": "v3"})


class AdapterTest(unittest.TestCase):
    def test_openai_parse_line(self):
        p = llm_client.ADAPTERS["openai"]["parse_line"]
        self.assertEqual(p('data: {"choices":[{"delta":{"content":"hi"}}]}'),
                         ("hi", False))
        self.assertEqual(p("data: [DONE]"), (None, True))
        self.assertEqual(p(": ping"), (None, False))
        self.assertEqual(p("data: not-json"), (None, False))

    def test_openai_headers_and_payload(self):
        ad = llm_client.ADAPTERS["openai"]
        self.assertEqual(ad["headers"]("k"), {"Authorization": "Bearer k"})
        self.assertEqual(ad["headers"](""), {})
        body = ad["payload"]("m", [{"role": "user", "content": "x"}], 0.3, 9)
        self.assertEqual(body["model"], "m")
        self.assertTrue(body["stream"])
        self.assertEqual(body["max_tokens"], 9)

    def test_unknown_provider_raises(self):
        cfg = llm_client.LaneConfig("worker", "anthropic", "http://x", "m", "", "none")
        with self.assertRaises(NotImplementedError):
            _ = cfg.adapter


class ResolveLaneTest(unittest.TestCase):
    def setUp(self):
        # stub the keychain so tests never touch the real one
        self._real_get = llm_client.secrets_store.get
        llm_client.secrets_store.get = lambda account: None
        for v in ("TESTLANE_LLM_BASE_URL", "TESTLANE_LLM_MODEL",
                  "TESTLANE_LLM_PROVIDER", "TESTLANE_LLM_API_KEY"):
            os.environ.pop(v, None)

    def tearDown(self):
        llm_client.secrets_store.get = self._real_get
        for v in ("TESTLANE_LLM_BASE_URL", "TESTLANE_LLM_MODEL",
                  "TESTLANE_LLM_PROVIDER", "TESTLANE_LLM_API_KEY"):
            os.environ.pop(v, None)

    def test_unconfigured_lane_is_none(self):
        self.assertIsNone(llm_client.resolve_lane("testlane"))

    def test_configured_lane_defaults_provider_openai(self):
        os.environ["TESTLANE_LLM_BASE_URL"] = "http://h/v1/"
        os.environ["TESTLANE_LLM_MODEL"] = "m1"
        cfg = llm_client.resolve_lane("testlane")
        self.assertEqual(cfg.provider, "openai")
        self.assertEqual(cfg.base_url, "http://h/v1")   # trailing slash stripped
        self.assertEqual(cfg.key_source, "none")

    def test_keychain_beats_dotenv_value(self):
        os.environ["TESTLANE_LLM_BASE_URL"] = "http://h/v1"
        os.environ["TESTLANE_LLM_MODEL"] = "m1"
        # simulate a .env-injected key (not a live env var)
        os.environ["TESTLANE_LLM_API_KEY"] = "dotenv-key"
        cockpit_env._injected.add("TESTLANE_LLM_API_KEY")
        llm_client.secrets_store.get = lambda account: "keychain-key"
        try:
            cfg = llm_client.resolve_lane("testlane")
            self.assertEqual(cfg.key, "keychain-key")
            self.assertEqual(cfg.key_source, "keychain")
        finally:
            cockpit_env._injected.discard("TESTLANE_LLM_API_KEY")


if __name__ == "__main__":
    unittest.main()
