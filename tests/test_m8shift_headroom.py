import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "m8shift-headroom.py")


class TestM8ShiftHeadroomWrapper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="m8shift-headroom-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _fake_headroom(self, body):
        pkg = os.path.join(self.tmp, "headroom")
        os.makedirs(pkg, exist_ok=True)
        with open(os.path.join(pkg, "__init__.py"), "w", encoding="utf-8") as fh:
            fh.write("__version__ = '0.28.0-test'\n")
        with open(os.path.join(pkg, "compress.py"), "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(body))
        env = dict(os.environ)
        env["PYTHONPATH"] = self.tmp + os.pathsep + env.get("PYTHONPATH", "")
        return env

    def _run(self, stdin, env=None):
        return subprocess.run(
            [sys.executable, SCRIPT, "m8shift-transform", "report"],
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_version_surface(self):
        result = subprocess.run([sys.executable, SCRIPT, "--version"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("m8shift-headroom.py 3.41.1", result.stdout)

    def test_wrapper_uses_offline_env_socket_block_and_non_user_messages(self):
        env = self._fake_headroom(
            """
            import os
            import socket

            def compress(messages):
                assert os.environ["HEADROOM_OFFLINE"] == "1"
                assert os.environ["HF_HUB_OFFLINE"] == "1"
                assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
                assert all(row["role"] != "user" for row in messages)
                try:
                    socket.create_connection(("example.com", 443), timeout=0.01)
                except Exception as exc:
                    assert "network disabled" in str(exc)
                else:
                    raise AssertionError("network was not blocked")
                return "offline-ok"
            """
        )
        result = self._run("decision: keep offline wrapper\n", env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "offline-ok\n")

    def test_missing_headroom_fails_closed_without_echoing_stdin(self):
        secret = "token=VERY_SECRET_VALUE_SHOULD_NOT_LEAK"
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        result = self._run(secret, env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertNotIn(secret, result.stderr)

    def test_unchanged_result_fails_closed_by_length_fallback(self):
        env = self._fake_headroom(
            """
            def compress(messages):
                return messages[-1]["content"].split("\\n\\n", 1)[-1]
            """
        )
        result = self._run("same text\n", env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("did not reduce compact length", result.stderr)

    def test_compress_result_messages_and_token_reduction_are_supported(self):
        env = self._fake_headroom(
            """
            class CompressResult:
                def __init__(self):
                    self.messages = [
                        {"role": "system", "content": "ignore"},
                        {"role": "assistant", "content": "compact decision trace"},
                    ]
                    self.tokens_before = 100
                    self.tokens_after = 20
                    self.compression_ratio = 0.2
                    self.transforms_applied = ["kompress"]

            def compress(messages):
                return CompressResult()
            """
        )
        result = self._run("x " * 200, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "compact decision trace\n")

    def test_compress_result_without_token_reduction_fails_closed(self):
        env = self._fake_headroom(
            """
            class CompressResult:
                messages = [{"role": "assistant", "content": "compact but not cheaper"}]
                tokens_before = 100
                tokens_after = 100

            def compress(messages):
                return CompressResult()
            """
        )
        result = self._run("x " * 200, env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("did not reduce token count", result.stderr)

    def test_conservative_redaction_before_headroom(self):
        env = self._fake_headroom(
            """
            def compress(messages):
                content = messages[-1]["content"]
                assert "SECRET123456789" not in content
                assert "[REDACTED]" in content
                return "redacted-ok"
            """
        )
        result = self._run("api_key=SECRET123456789\n", env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "redacted-ok\n")


if __name__ == "__main__":
    unittest.main()
