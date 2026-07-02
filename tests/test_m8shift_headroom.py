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
        transforms = os.path.join(pkg, "transforms")
        os.makedirs(pkg, exist_ok=True)
        os.makedirs(transforms, exist_ok=True)
        with open(os.path.join(pkg, "__init__.py"), "w", encoding="utf-8") as fh:
            fh.write("__version__ = '0.28.0-test'\n")
        with open(os.path.join(transforms, "__init__.py"), "w", encoding="utf-8") as fh:
            fh.write("")
        with open(os.path.join(transforms, "kompress_compressor.py"), "w", encoding="utf-8") as fh:
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

            class KompressConfig:
                pass

            class Result:
                compressed = "offline-ok"
                original_tokens = 100
                compressed_tokens = 20

            class KompressCompressor:
                def __init__(self, config):
                    assert isinstance(config, KompressConfig)

                def compress(self, text, target_ratio, allow_download):
                    assert os.environ["HEADROOM_OFFLINE"] == "1"
                    assert os.environ["HF_HUB_OFFLINE"] == "1"
                    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
                    assert target_ratio == 0.4
                    assert allow_download is False
                    assert isinstance(text, str)
                    assert '"role": "user"' not in text
                    assert "decision: keep offline wrapper" in text
                    assert "m8shift_headroom_mode=report" in text
                    try:
                        socket.create_connection(("example.com", 443), timeout=0.01)
                    except Exception as exc:
                        assert "network disabled" in str(exc)
                    else:
                        raise AssertionError("network was not blocked")
                    return Result()

            def ensure_background_download(model_id):
                raise AssertionError("runtime wrapper must not download")
            """
        )
        result = self._run("decision: keep offline wrapper\n", env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "offline-ok\n")

    def test_kompress_import_error_fails_closed_without_echoing_stdin(self):
        env = self._fake_headroom(
            """
            class KompressConfig:
                pass

            class KompressCompressor:
                def __init__(self, config):
                    raise ImportError("Kompress requires onnxruntime or torch")

            def ensure_background_download(model_id):
                pass
            """
        )
        secret = "token=SECRET123456789"
        result = self._run(secret, env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertNotIn(secret, result.stderr)
        self.assertIn("Kompress compression failed", result.stderr)

    def test_unchanged_result_fails_closed_by_length_fallback(self):
        env = self._fake_headroom(
            """
            class KompressConfig:
                pass

            class KompressCompressor:
                def __init__(self, config):
                    pass

                def compress(self, text, target_ratio, allow_download):
                    return text

            def ensure_background_download(model_id):
                pass
            """
        )
        result = self._run("same text\n", env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("did not reduce compact length", result.stderr)

    def test_kompress_result_compressed_and_token_reduction_are_supported(self):
        env = self._fake_headroom(
            """
            class KompressConfig:
                pass

            class CompressResult:
                compressed = "compact decision trace"
                original_tokens = 100
                compressed_tokens = 20
                compression_ratio = 0.2

            class KompressCompressor:
                def __init__(self, config):
                    pass

                def compress(self, text, target_ratio, allow_download):
                    return CompressResult()

            def ensure_background_download(model_id):
                pass
            """
        )
        result = self._run("x " * 200, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "compact decision trace\n")

    def test_kompress_result_without_token_reduction_fails_closed(self):
        env = self._fake_headroom(
            """
            class KompressConfig:
                pass

            class CompressResult:
                compressed = "compact but not cheaper"
                original_tokens = 100
                compressed_tokens = 100

            class KompressCompressor:
                def __init__(self, config):
                    pass

                def compress(self, text, target_ratio, allow_download):
                    return CompressResult()

            def ensure_background_download(model_id):
                pass
            """
        )
        result = self._run("x " * 200, env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("did not reduce token count", result.stderr)

    def test_conservative_redaction_before_headroom(self):
        env = self._fake_headroom(
            """
            class KompressConfig:
                pass

            class Result:
                compressed = "redacted-ok"
                original_tokens = 100
                compressed_tokens = 20

            class KompressCompressor:
                def __init__(self, config):
                    pass

                def compress(self, text, target_ratio, allow_download):
                    assert "SECRET123456789" not in text
                    assert "[REDACTED]" in text
                    return Result()

            def ensure_background_download(model_id):
                pass
            """
        )
        result = self._run("api_key=SECRET123456789\n", env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "redacted-ok\n")

    def test_preload_helper_contract_is_mockable_for_installer(self):
        env = self._fake_headroom(
            """
            seen = []

            class KompressConfig:
                pass

            class Result:
                compressed = "compact"
                original_tokens = 10
                compressed_tokens = 5

            class KompressCompressor:
                def __init__(self, config):
                    pass

                def compress(self, text, target_ratio, allow_download):
                    return Result()

            def ensure_background_download(model_id):
                assert model_id == "chopratejas/kompress-v2-base"
                seen.append(model_id)
            """
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from headroom.transforms.kompress_compressor import ensure_background_download; "
                    "ensure_background_download(model_id='chopratejas/kompress-v2-base')"
                ),
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_headroom_fails_closed_without_echoing_stdin(self):
        secret = "token=VERY_SECRET_VALUE_SHOULD_NOT_LEAK"
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        result = self._run(secret, env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertNotIn(secret, result.stderr)



if __name__ == "__main__":
    unittest.main()
