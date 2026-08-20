"""Verify the exact wheel and source distribution before publication."""

from __future__ import annotations

import argparse
import email
import re
import tarfile
import zipfile
from email.message import Message
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]


class ArtifactError(RuntimeError):
    """A release artifact does not match the reviewed project metadata."""


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _project_identity(root: Path) -> tuple[str, str]:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    name = project.get("name")
    version = project.get("version")
    if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
        raise ArtifactError("pyproject.toml must declare a project name and version")
    classifiers = project.get("classifiers", [])
    if any(str(item).startswith("Development Status ::") for item in classifiers):
        raise ArtifactError("project metadata must not publish a static maturity classifier")
    return name, version


def _wheel_metadata(path: Path) -> bytes:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise ArtifactError(f"{path.name} must contain exactly one METADATA file")
        return archive.read(names[0])


def _sdist_metadata(path: Path) -> bytes:
    with tarfile.open(path, "r:gz") as archive:
        members = [
            member
            for member in archive.getmembers()
            if member.isfile() and member.name.count("/") == 1 and member.name.endswith("/PKG-INFO")
        ]
        if len(members) != 1:
            raise ArtifactError(f"{path.name} must contain exactly one root PKG-INFO file")
        stream = archive.extractfile(members[0])
        if stream is None:
            raise ArtifactError(f"{path.name} PKG-INFO cannot be read")
        return stream.read()


def _verify_metadata(path: Path, payload: bytes, name: str, version: str) -> None:
    metadata: Message = email.message_from_bytes(payload)
    if _canonical_name(metadata.get("Name", "")) != _canonical_name(name):
        raise ArtifactError(f"{path.name} has the wrong package name")
    if metadata.get("Version") != version:
        raise ArtifactError(f"{path.name} has the wrong package version")
    classifiers = metadata.get_all("Classifier", [])
    if any(value.startswith("Development Status ::") for value in classifiers):
        raise ArtifactError(f"{path.name} publishes a static maturity classifier")


def verify_distributions(root: Path = ROOT) -> tuple[Path, Path]:
    """Verify one wheel and one source archive against ``pyproject.toml``."""
    name, version = _project_identity(root)
    dist = root / "dist"
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ArtifactError("dist must contain exactly one wheel and one source distribution")
    _verify_metadata(wheels[0], _wheel_metadata(wheels[0]), name, version)
    _verify_metadata(sdists[0], _sdist_metadata(sdists[0]), name, version)
    return wheels[0], sdists[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        wheel, sdist = verify_distributions(args.root.resolve())
    except (ArtifactError, OSError, KeyError, tarfile.TarError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"release artifact verification failed: {exc}\n")
    print(f"verified {wheel.name} and {sdist.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
