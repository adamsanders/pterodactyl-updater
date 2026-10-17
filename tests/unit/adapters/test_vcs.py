"""Unit tests for VCS and Git repository infrastructure adapter."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.adapters.vcs import DEFAULT_COMMIT_CODE, resolve_commit_code


class TestVCSAdapter(unittest.TestCase):
    """Test suite for VCS adapter commit code resolution."""

    def setUp(self):
        # Clear env variables that could interfere
        self.env_patcher = patch.dict(
            os.environ,
            {
                "GIT_COMMIT": "",
                "COMMIT_SHA": "",
                "APP_COMMIT": "",
                "GIT_SHA": "",
                "COMMIT_CODE": "",
            },
            clear=False,
        )
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    def test_default_commit_code_constant(self):
        self.assertEqual(len(DEFAULT_COMMIT_CODE), 7)
        self.assertIsInstance(DEFAULT_COMMIT_CODE, str)

    def test_resolve_from_git_commit_env(self):
        with patch.dict(os.environ, {"GIT_COMMIT": "abcdef123456"}):
            self.assertEqual(resolve_commit_code(), "abcdef1")

    def test_resolve_from_commit_sha_env(self):
        with patch.dict(os.environ, {"COMMIT_SHA": "commit 1234567890"}):
            self.assertEqual(resolve_commit_code(), "1234567")

    def test_resolve_from_app_commit_env(self):
        with patch.dict(os.environ, {"APP_COMMIT": "fedcba987654"}):
            self.assertEqual(resolve_commit_code(), "fedcba9")

    def test_resolve_from_git_sha_env(self):
        with patch.dict(os.environ, {"GIT_SHA": "777888999aaa"}):
            self.assertEqual(resolve_commit_code(), "7778889")

    def test_resolve_from_commit_code_env(self):
        with patch.dict(os.environ, {"COMMIT_CODE": "555666777"}):
            self.assertEqual(resolve_commit_code(), "5556667")

    def test_env_ignores_unknown_or_short(self):
        with patch.dict(os.environ, {"GIT_COMMIT": "unknown", "COMMIT_SHA": "123"}):
            # Should not return "unknown" or 3-char "123"
            code = resolve_commit_code(default="custom_def")
            self.assertNotEqual(code, "unknown")
            self.assertNotEqual(code, "123")

    def test_resolve_via_git_subprocess(self):
        with patch("subprocess.check_output", return_value="a1b2c3d4e5f6\n"):
            code = resolve_commit_code()
            self.assertEqual(code, "a1b2c3d")

    def test_resolve_subprocess_failure_falls_through(self):
        with patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "git")):
            # Should not raise exception
            code = resolve_commit_code(default="fallback")
            self.assertIsInstance(code, str)

    def test_resolve_from_native_git_head_ref(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            git_dir = tmppath / ".git"
            git_dir.mkdir(parents=True)
            head_file = git_dir / "HEAD"
            head_file.write_text("ref: refs/heads/main\n", encoding="utf-8")
            ref_file = git_dir / "refs" / "heads" / "main"
            ref_file.parent.mkdir(parents=True)
            ref_file.write_text("0123456789abcdef\n", encoding="utf-8")

            with patch("subprocess.check_output", side_effect=Exception("no git")):
                with patch("app.adapters.vcs.__file__", str(tmppath / "app" / "adapters" / "vcs.py")):
                    code = resolve_commit_code(default="fallback")
                    self.assertEqual(code, "0123456")

    def test_resolve_from_packed_refs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            git_dir = tmppath / ".git"
            git_dir.mkdir(parents=True)
            head_file = git_dir / "HEAD"
            head_file.write_text("ref: refs/heads/release\n", encoding="utf-8")
            packed_file = git_dir / "packed-refs"
            packed_file.write_text(
                "# pack-refs with: peeled-tags\n"
                "9876543210fedcba refs/heads/release\n",
                encoding="utf-8",
            )

            with patch("subprocess.check_output", side_effect=Exception("no git")):
                with patch("app.adapters.vcs.__file__", str(tmppath / "app" / "adapters" / "vcs.py")):
                    code = resolve_commit_code(default="fallback")
                    self.assertEqual(code, "9876543")

    def test_resolve_from_detached_head(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            git_dir = tmppath / ".git"
            git_dir.mkdir(parents=True)
            head_file = git_dir / "HEAD"
            head_file.write_text("fedcba0987654321\n", encoding="utf-8")

            with patch("subprocess.check_output", side_effect=Exception("no git")):
                with patch("app.adapters.vcs.__file__", str(tmppath / "app" / "adapters" / "vcs.py")):
                    code = resolve_commit_code(default="fallback")
                    self.assertEqual(code, "fedcba0")

    def test_resolve_from_worktree_gitdir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            actual_gitdir = tmppath / "real_git"
            actual_gitdir.mkdir(parents=True)
            (actual_gitdir / "HEAD").write_text("abcdef1234567890\n", encoding="utf-8")

            dot_git = tmppath / ".git"
            dot_git.write_text(f"gitdir: {actual_gitdir}\n", encoding="utf-8")

            with patch("subprocess.check_output", side_effect=Exception("no git")):
                with patch("app.adapters.vcs.__file__", str(tmppath / "app" / "adapters" / "vcs.py")):
                    code = resolve_commit_code(default="fallback")
                    self.assertEqual(code, "abcdef1")

    def test_resolve_from_candidate_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            commit_txt = tmppath / "commit.txt"
            commit_txt.write_text("commit aabbccddee\n", encoding="utf-8")

            with patch("subprocess.check_output", side_effect=Exception("no git")):
                with patch("app.adapters.vcs.__file__", str(tmppath / "app" / "adapters" / "vcs.py")):
                    code = resolve_commit_code(default="fallback")
                    self.assertEqual(code, "aabbccd")

    def test_resolve_fallback_to_default_parameter(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("subprocess.check_output", side_effect=Exception("no git")):
                with patch("os.path.isfile", return_value=False):
                    self.assertEqual(resolve_commit_code(default="custom99"), "custom99")
                    self.assertEqual(resolve_commit_code(), DEFAULT_COMMIT_CODE)


if __name__ == "__main__":
    unittest.main()
