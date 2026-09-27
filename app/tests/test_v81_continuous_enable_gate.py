import json, importlib, os, tempfile, unittest
from pathlib import Path
from unittest import mock

run_continuous = importlib.import_module("run_continuous")
from pfai.continuous_gate import is_continuous_enabled, continuous_gate_status, ENV_NAME


class TestContinuousEnableGate(unittest.TestCase):
    def _write_config(self, d, enabled):
        cfg = {
            "memory": {"path": "data/pfai_memory.sqlite3"},
            "model": {"provider": "echo"},
            "continuous_training": {"enabled": enabled},
        }
        path = Path(d) / "config.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        return str(path)

    def test_disabled_by_default_field_missing(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = {"memory": {"path": "x"}, "model": {"provider": "echo"}}
            path = Path(d) / "config.json"
            path.write_text(json.dumps(cfg), encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop(ENV_NAME, None)
                self.assertFalse(run_continuous.is_enabled(str(path)))

    def test_disabled_when_explicitly_false(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write_config(d, False)
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop(ENV_NAME, None)
                self.assertFalse(run_continuous.is_enabled(path))

    def test_enabled_when_explicitly_true(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write_config(d, True)
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop(ENV_NAME, None)
                self.assertTrue(run_continuous.is_enabled(path))

    def test_env_force_disable_overrides_config_true(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write_config(d, True)
            with mock.patch.dict(os.environ, {ENV_NAME: "false"}):
                self.assertFalse(is_continuous_enabled(path))
                self.assertFalse(run_continuous.is_enabled(path))

    def test_env_force_enable_overrides_config_false(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write_config(d, False)
            with mock.patch.dict(os.environ, {ENV_NAME: "true"}):
                self.assertTrue(is_continuous_enabled(path))

    def test_gate_status_reports_safety_invariants(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write_config(d, True)
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop(ENV_NAME, None)
                status = continuous_gate_status(path)
                self.assertTrue(status["enabled"])
                self.assertFalse(status["auto_promote"])
                self.assertTrue(status["require_human_approval"])


if __name__ == "__main__":
    unittest.main()
