"""App version file and the build script's version prompts."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import src.app_version as V

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import generate_executable as G  # noqa: E402


class NextVersionTest(unittest.TestCase):
    def test_bumps_minor_as_integer(self):
        self.assertEqual(V.next_version(None), "1.0")
        self.assertEqual(V.next_version("1.0"), "1.1")
        self.assertEqual(V.next_version("1.9"), "1.10")
        self.assertEqual(V.next_version("2.10"), "2.11")
        self.assertEqual(V.next_version("garbage"), "1.0")


class ReadVersionTest(unittest.TestCase):
    def _read(self, content):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "version.json"
            if content is not None:
                path.write_text(content, encoding="utf-8")
            with mock.patch.object(V, "version_file_path", return_value=path):
                return V.read_version_info()

    def test_missing_or_broken_file_is_dev(self):
        self.assertEqual(self._read(None)["version"], "dev")
        self.assertEqual(self._read("{not json")["version"], "dev")

    def test_reads_version(self):
        info = self._read('{"version": "1.3", "released_at": "2026-10-07 14:22:05"}')
        self.assertEqual(info, {"version": "1.3", "released_at": "2026-10-07 14:22:05"})


class BuildScriptVersionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.repo_config, self.dist_config = root / "config", root / "dist_config"
        self.repo_config.mkdir()
        patcher = mock.patch.object(G, "CONFIG_FOLDER", self.repo_config)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def _set_repo_version(self, version):
        (self.repo_config / "version.json").write_text(
            json.dumps({"version": version, "released_at": "x"}), encoding="utf-8")

    def _build(self, *answers):
        with mock.patch("builtins.input", side_effect=list(answers)), \
                mock.patch("builtins.print"):
            env = G._prompt_build_type()
            version = G._choose_version(env)
            G._write_version_file(self.dist_config, version, env)
        return version

    def _repo_version(self):
        return json.loads((self.repo_config / "version.json").read_text(encoding="utf-8"))

    def test_test_build_keeps_number_and_record(self):
        self._set_repo_version("1.4")
        self.assertEqual(self._build(""), "1.4")  # Enter = test
        self.assertEqual(self._repo_version()["released_at"], "x")  # untouched
        self.assertTrue((self.dist_config / "version.json").exists())

    def test_production_bump_writes_both_copies(self):
        self._set_repo_version("1.9")
        self.assertEqual(self._build("p", "y"), "1.10")
        self.assertEqual(self._repo_version()["version"], "1.10")
        shipped = json.loads((self.dist_config / "version.json").read_text(encoding="utf-8"))
        self.assertEqual(shipped, self._repo_version())

    def test_production_defaults_to_no_bump(self):
        self._set_repo_version("1.2")
        self.assertEqual(self._build("p", ""), "1.2")

    def test_first_production_release_is_1_0(self):
        self.assertEqual(self._build("p", "y"), "1.0")
        self.assertEqual(self._repo_version()["version"], "1.0")


if __name__ == "__main__":
    unittest.main()
