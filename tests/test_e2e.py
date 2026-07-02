"""End-to-end test against the deterministic mock LLM — no real endpoint,
no key, no browser, finishes in seconds.

    python3 -m unittest tests.test_e2e

Spawns tests/mock_llm.py + src/server.py (worker AND API reader both pointed
at the mock, scrape absent) and drives the real HTTP surface: worker chat,
worker explore (fetch round), API-reader consult (brief -> fetch -> answer),
forward, and the context invariant (repo bodies never in worker history).
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def get_json(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


def post_json(url, obj):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def wait_until(pred, timeout=15, every=0.2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(every)
    return False


class E2ETest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock_port = free_port()
        cls.port = free_port()
        cls.tmp = tempfile.TemporaryDirectory()
        with open(os.path.join(cls.tmp.name, "README.md"), "w") as f:
            f.write("mock repo readme\n")
        cls.mock = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "tests", "mock_llm.py"),
             str(cls.mock_port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("WORKER_LLM_", "READER_LLM_", "COCKPIT_"))}
        base = f"http://127.0.0.1:{cls.mock_port}/v1"
        env.update({
            "WORKER_LLM_BASE_URL": base, "WORKER_LLM_MODEL": "mock",
            "READER_LLM_BASE_URL": base, "READER_LLM_MODEL": "mock",
            "COCKPIT_ENV": os.devnull,          # no .env pickup
            "COCKPIT_SCRIPTS": "/nonexistent",  # scrape absent
            "COCKPIT_PORT": str(cls.port),
            "COCKPIT_REPO": cls.tmp.name,
        })
        cls.srv = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "src", "server.py")], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.url = f"http://127.0.0.1:{cls.port}"
        ok = wait_until(lambda: cls._alive(), timeout=10)
        if not ok:
            cls.tearDownClass()
            raise RuntimeError("cockpit did not come up")

    @classmethod
    def _alive(cls):
        try:
            get_json(cls.url + "/state")
            return True
        except Exception:
            return False

    @classmethod
    def tearDownClass(cls):
        for p in (getattr(cls, "srv", None), getattr(cls, "mock", None)):
            if p:
                p.terminate()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    p.kill()
        cls.tmp.cleanup()

    def state(self):
        return get_json(self.url + "/state")

    def test_1_state_reports_api_reader(self):
        s = self.state()
        self.assertEqual(s["reader_mode"], "api")
        self.assertEqual(s["worker_model"], "mock")

    def test_2_worker_chat(self):
        code, _ = post_json(self.url + "/worker", {"message": "hi"})
        self.assertEqual(code, 202)
        self.assertTrue(wait_until(lambda: any(
            "MOCK-CHAT" in m["content"] for m in self.state()["worker"])))

    def test_3_worker_explore_round_trip(self):
        code, _ = post_json(self.url + "/worker-explore",
                            {"task": "look around", "repo": self.tmp.name})
        self.assertEqual(code, 202)
        self.assertTrue(wait_until(lambda: any(
            "MOCK-ANSWER" in m["content"] for m in self.state()["worker"])))
        # invariant: served repo bodies never join the persistent history
        joined = "\n".join(m["content"] for m in self.state()["worker"])
        self.assertNotIn("mock repo readme", joined)

    def test_4_consult_via_api_reader_and_forward(self):
        before = len(self.state()["worker"])
        code, body = post_json(self.url + "/consult",
                               {"question": "check it", "repo": self.tmp.name})
        self.assertEqual(code, 202)
        self.assertEqual(body.get("reader"), "api")
        self.assertTrue(wait_until(lambda: self.state()["has_answer"]))
        s = self.state()
        self.assertIn("MOCK-ANSWER", s["last_answer"])
        # invariant: consult must not touch worker history
        self.assertEqual(len(s["worker"]), before)
        # forward crosses only the answer text
        code, body = post_json(self.url + "/forward", {})
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertTrue(wait_until(lambda: any(
            "Forwarded" in m["content"] for m in self.state()["worker"])))
        joined = "\n".join(m["content"] for m in self.state()["worker"])
        self.assertNotIn("mock repo readme", joined)

    def test_5_worker_consults_reader_on_explicit_request(self):
        """The one-input UX: telling the worker to ask the reader triggers the
        consult tool loop (worker -> ```consult -> reader run -> [Reader's
        answer] -> worker synthesis), with the invariant intact."""
        code, _ = post_json(self.url + "/worker",
                            {"message": "please ask the reader about the readme",
                             "repo": self.tmp.name})
        self.assertEqual(code, 202)
        self.assertTrue(wait_until(lambda: any(
            "MOCK-SYNTH" in m["content"] for m in self.state()["worker"])))
        joined = "\n".join(m["content"] for m in self.state()["worker"])
        self.assertIn("[Reader's answer]", joined)     # answer text crossed
        self.assertNotIn("mock repo readme", joined)   # repo bodies did not

    def test_6_gone_alias_is_404(self):
        code, _ = post_json(self.url + "/gemma", {"message": "x"})
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
