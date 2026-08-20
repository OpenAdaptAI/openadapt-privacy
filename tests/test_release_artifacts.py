from __future__ import annotations

import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_release_artifacts.py"
SPEC = importlib.util.spec_from_file_location("verify_release_artifacts", SCRIPT)
assert SPEC and SPEC.loader
artifacts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(artifacts)


def _metadata(*, classifier: str | None = None) -> bytes:
    lines = [
        "Metadata-Version: 2.4",
        "Name: example-package",
        "Version: 1.2.3",
    ]
    if classifier is not None:
        lines.append(f"Classifier: {classifier}")
    return ("\n".join(lines) + "\n\n").encode()


def _write_release(root: Path, *, artifact_classifier: str | None = None) -> None:
    (root / "pyproject.toml").write_text(
        '[project]\nname = "example-package"\nversion = "1.2.3"\nclassifiers = []\n',
        encoding="utf-8",
    )
    dist = root / "dist"
    dist.mkdir()
    payload = _metadata(classifier=artifact_classifier)
    with zipfile.ZipFile(dist / "example_package-1.2.3-py3-none-any.whl", "w") as archive:
        archive.writestr("example_package-1.2.3.dist-info/METADATA", payload)
    with tarfile.open(dist / "example_package-1.2.3.tar.gz", "w:gz") as archive:
        member = tarfile.TarInfo("example_package-1.2.3/PKG-INFO")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))


def test_matching_wheel_and_source_distribution_pass(tmp_path: Path) -> None:
    _write_release(tmp_path)
    wheel, sdist = artifacts.verify_distributions(tmp_path)
    assert wheel.suffix == ".whl"
    assert sdist.name.endswith(".tar.gz")


def test_static_maturity_classifier_in_archive_fails(tmp_path: Path) -> None:
    _write_release(tmp_path, artifact_classifier="Development Status :: 3 - Alpha")
    with pytest.raises(artifacts.ArtifactError, match="static maturity classifier"):
        artifacts.verify_distributions(tmp_path)


def test_extra_release_archive_fails(tmp_path: Path) -> None:
    _write_release(tmp_path)
    (tmp_path / "dist" / "unexpected.whl").touch()
    with pytest.raises(artifacts.ArtifactError, match="exactly one wheel"):
        artifacts.verify_distributions(tmp_path)
