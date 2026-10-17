import os
import unittest
from unittest.mock import patch

from app.adapters.vcs import resolve_commit_code
from app.core.config import APP_VERSION, COMMIT_CODE, get_commit_code


class TestAppVersionAndCommit(unittest.TestCase):

  def test_app_version_defined_and_formatted(self):
    self.assertIsInstance(APP_VERSION, str)
    self.assertEqual(APP_VERSION, "1.31.0")
    # Check semver pattern (e.g. 1.1.0)
    parts = APP_VERSION.split(".")
    self.assertGreaterEqual(len(parts), 2)
    self.assertTrue(parts[0].isdigit())

  def test_commit_code_defined_and_formatted(self):
    self.assertIsInstance(COMMIT_CODE, str)
    self.assertTrue(len(COMMIT_CODE) > 0)
    self.assertLessEqual(len(COMMIT_CODE), 7)
    self.assertNotEqual(COMMIT_CODE, "unknown")

  def test_get_commit_code_matches_commit_code(self):
    self.assertEqual(get_commit_code(), COMMIT_CODE)

  def test_resolve_commit_code_env_override(self):
    with patch.dict(os.environ, {"GIT_COMMIT": "abcdef123456"}):
      resolved = resolve_commit_code()
      self.assertEqual(resolved, "abcdef1")

  def test_resolve_commit_code_ignores_unknown_env(self):
    with patch.dict(os.environ, {"GIT_COMMIT": "unknown"}):
      resolved = resolve_commit_code()
      self.assertNotEqual(resolved, "unknown")
      self.assertGreaterEqual(len(resolved), 7)

  def test_resolve_commit_code_from_file_and_fallback(self):
    with patch.dict(os.environ, {"GIT_COMMIT": ""}, clear=True), \
         patch("subprocess.check_output", side_effect=Exception("no git")), \
         patch("os.path.isfile", return_value=False):
      resolved = resolve_commit_code()
      self.assertNotEqual(resolved, "unknown")
      self.assertGreaterEqual(len(resolved), 7)

  def test_config_import_purely_in_memory_no_side_effects(self):
    import builtins
    import importlib
    import sys

    original_open = builtins.open

    def guarded_open(file, *args, **kwargs):
      fname = str(file).lower()
      if ".git" in fname or "commit" in fname:
        raise AssertionError(f"Disk read for git/commit metadata during import: {fname}")
      return original_open(file, *args, **kwargs)

    with patch("subprocess.check_output", side_effect=AssertionError("subprocess called at import")), \
         patch("builtins.open", side_effect=guarded_open):
      mod = importlib.reload(sys.modules["app.core.config"])
      self.assertIsNotNone(mod)


if __name__ == "__main__":
  unittest.main()
