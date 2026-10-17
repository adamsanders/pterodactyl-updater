"""VCS and Git repository infrastructure adapter.

Extracts low-level Git repository inspection, environment variable overrides,
and metadata file crawling out of domain configuration into a dedicated adapter.
"""

import os
import subprocess
from typing import Optional

from app.core.config import DEFAULT_COMMIT_CODE


def resolve_commit_code(default: str = DEFAULT_COMMIT_CODE) -> str:
    """Resolves the current Git commit short hash from env, git repository, or metadata files."""
    for env_var in ("GIT_COMMIT", "COMMIT_SHA", "APP_COMMIT", "GIT_SHA", "COMMIT_CODE"):
        val = os.getenv(env_var, "").strip()
        if val and val.lower() != "unknown":
            val = val.replace("commit", "").strip()
            if len(val) >= 7:
                return val[:7]

    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    core_dir = os.path.join(app_dir, "core")

    # 1. Try git rev-parse if git CLI and repository are present
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            timeout=1,
            text=True,
        ).strip()
        if output and output.lower() != "unknown":
            return output[:7]
    except Exception:
        pass

    # 2. Try native parsing of .git directory or worktree gitdir file
    try:
        git_entry = os.path.join(repo_root, ".git")
        git_dir = git_entry
        if os.path.isfile(git_entry):
            with open(git_entry, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content.startswith("gitdir:"):
                raw_gitdir = content[7:].strip()
                git_dir = os.path.abspath(os.path.join(repo_root, raw_gitdir))

        head_path = os.path.join(git_dir, "HEAD")
        if os.path.isfile(head_path):
            with open(head_path, "r", encoding="utf-8") as f:
                ref = f.read().strip()
            if ref.startswith("ref: "):
                ref_rel = ref[5:].strip()
                ref_file = os.path.join(git_dir, *ref_rel.split("/"))
                if os.path.isfile(ref_file):
                    with open(ref_file, "r", encoding="utf-8") as f:
                        sha = f.read().strip()
                        if sha:
                            return sha[:7]
                packed_path = os.path.join(git_dir, "packed-refs")
                if os.path.isfile(packed_path):
                    with open(packed_path, "r", encoding="utf-8") as f:
                        for line in f:
                            line_str = line.strip()
                            if line_str and not line_str.startswith(("#", "^")):
                                parts = line_str.split()
                                if len(parts) == 2 and parts[1] == ref_rel:
                                    return parts[0][:7]
            elif len(ref) >= 7:
                return ref[:7]
    except Exception:
        pass

    # 3. Check commit metadata files (e.g. copied into Docker image or created during release)
    candidate_files = [
        os.path.join(app_dir, "commit.txt"),
        os.path.join(core_dir, "commit.txt"),
        os.path.join(repo_root, ".commit"),
        os.path.join(repo_root, "commit.txt"),
        os.path.join(repo_root, "COMMIT_HASH"),
    ]
    for cfile in candidate_files:
        try:
            if os.path.isfile(cfile):
                with open(cfile, "r", encoding="utf-8") as f:
                    cval = f.read().strip()
                if cval and cval.lower() != "unknown":
                    cval = cval.replace("commit", "").strip()
                    if len(cval) >= 7:
                        return cval[:7]
        except Exception:
            pass

    return default


__all__ = ["DEFAULT_COMMIT_CODE", "resolve_commit_code"]
