"""Dependency contract for the default PHI scrubber."""

from __future__ import annotations

from pathlib import Path

import tomllib


def test_presidio_extra_does_not_install_transformers() -> None:
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    dependencies = project["project"]["optional-dependencies"]["presidio"]
    normalized = {
        dependency.split("[", 1)[0].split("<", 1)[0].split(">", 1)[0] for dependency in dependencies
    }
    assert "spacy-transformers" not in normalized
    assert "transformers" not in normalized
    provider_source = (root / "openadapt_privacy/providers/presidio.py").read_text()
    assert "spacy_transformers" not in provider_source
