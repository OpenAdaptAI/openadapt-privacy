"""Regression checks for the protected-main semantic release path."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_stays_on_declared_one_x_version_line() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r"(?m)^allow_zero_version\s*=\s*false\s*$", pyproject)
    assert re.search(r"(?m)^major_on_zero\s*=\s*true\s*$", pyproject)


def test_release_uses_protected_branch_credential_everywhere() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "token: ${{ secrets.ADMIN_TOKEN }}" in workflow
    assert workflow.count("github_token: ${{ secrets.ADMIN_TOKEN }}") == 2
    assert "secrets.GITHUB_TOKEN" not in workflow


def test_release_checks_the_built_archives_before_publication() -> None:
    test_workflow = (ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
    release_workflow = (ROOT / ".github/workflows/release.yml").read_text(
        encoding="utf-8"
    )
    command = "python scripts/verify_release_artifacts.py"
    assert command in test_workflow
    assert command in release_workflow


def test_project_has_no_static_maturity_classifier() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "Development Status ::" not in pyproject


def test_current_built_archives_match_reviewed_metadata() -> None:
    if not (ROOT / "dist").is_dir():
        return
    subprocess.run(
        [sys.executable, "scripts/verify_release_artifacts.py"],
        cwd=ROOT,
        check=True,
    )
