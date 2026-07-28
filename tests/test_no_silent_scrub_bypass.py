"""Regressions against reporting a failed scrub as a successful one.

Every test here pins the boundary between "scrubbing ran and found nothing"
and "scrubbing could not run". A success-shaped return for the second case
lets unredacted PII/PHI cross the privacy boundary while the caller records a
successful scrub.
"""

from __future__ import annotations

import subprocess
import sys
from importlib import metadata

import pytest
from PIL import Image

import openadapt_privacy
from openadapt_privacy.base import (
    Modality,
    ScrubbingPolicyChanged,
    ScrubbingProvider,
    ScrubbingProviderUnavailable,
)
from openadapt_privacy.config import config
from openadapt_privacy.loaders import Action, Recording, Screenshot, UnscrubbedScreenshot


def _run_in_fresh_interpreter(source: str) -> subprocess.CompletedProcess[str]:
    """Run `source` in a new interpreter and fail loudly on a non-zero exit."""
    completed = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, (
        f"subprocess exited {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    return completed


class _StubScrubber(ScrubbingProvider):
    """Minimal image scrubber that proves redaction actually happened."""

    name: str = "stub"
    capabilities: list[str] = [Modality.TEXT, Modality.PIL_IMAGE]

    def scrub_text(self, text: str, is_separated: bool = False) -> str:
        return text

    def scrub_dict(self, input_dict: dict) -> dict:
        return input_dict.copy()

    def scrub_image(self, image: Image.Image, fill_color: int | None = None) -> Image.Image:
        return Image.new("RGB", image.size, (0, 0, 0))


class _TextStubScrubber(ScrubbingProvider):
    name: str = "text-stub"
    capabilities: list[str] = [Modality.TEXT]
    calls: int = 0

    def scrub_text(self, text: str, is_separated: bool = False) -> str:
        self.calls += 1
        return "<redacted>"

    def scrub_dict(self, input_dict: dict) -> dict:
        return {}


class _UnavailableTextScrubber(_TextStubScrubber):
    def validate_ready(self, modalities: list[str]) -> None:
        raise ScrubbingProviderUnavailable("dependency missing; no scrub was attempted")


class _PolicyMutatingScrubber(_TextStubScrubber):
    def scrub_text(self, text: str, is_separated: bool = False) -> str:
        config.SCRUB_CHAR = "!" if config.SCRUB_CHAR != "!" else "#"
        return super().scrub_text(text, is_separated=is_separated)


class TestPackageRootExports:
    """The documented consumer import must work on a complete install."""

    def test_presidio_provider_importable_from_package_root(self) -> None:
        # Downstream code writes `from openadapt_privacy import
        # PresidioScrubbingProvider` inside `try: ... except ImportError:` and
        # reads the failure as "openadapt-privacy is not installed", then
        # disables scrubbing. The import must therefore succeed whenever the
        # package is installed.
        result = _run_in_fresh_interpreter(
            "from openadapt_privacy import PresidioScrubbingProvider\n"
            "print(PresidioScrubbingProvider.__module__)\n"
        )
        assert result.stdout.strip() == "openadapt_privacy.providers.presidio"

    def test_model_unavailable_error_importable_from_package_root(self) -> None:
        result = _run_in_fresh_interpreter(
            "from openadapt_privacy import PrivacyModelUnavailable\n"
            "print(issubclass(PrivacyModelUnavailable, RuntimeError))\n"
        )
        assert result.stdout.strip() == "True"

    def test_unknown_attribute_still_raises_attribute_error(self) -> None:
        with pytest.raises(AttributeError):
            openadapt_privacy.NotARealSymbol

    def test_reported_version_matches_installed_distribution(self) -> None:
        # A hard-coded literal reported a version the package had not been on
        # for four minor releases; a version claim must come from the install.
        assert openadapt_privacy.__version__ == metadata.version("openadapt-privacy")


class TestProviderDiscovery:
    """An empty provider list must mean "inspected", not "never imported"."""

    def test_text_modality_is_non_empty_in_a_fresh_interpreter(self) -> None:
        # Reading ScrubbingProvider.__subclasses__() without importing the
        # provider modules returned [] for TEXT, which a caller iterating the
        # providers cannot distinguish from "no scrubbing needed".
        result = _run_in_fresh_interpreter(
            "from openadapt_privacy import Modality, ScrubbingProviderFactory\n"
            "providers = ScrubbingProviderFactory.get_for_modality(Modality.TEXT)\n"
            "print(sorted(p.name for p in providers))\n"
        )
        assert "PRESIDIO" in result.stdout


class TestScreenshotScrub:
    """A Screenshot must never look scrubbed while naming unredacted bytes."""

    def test_unloaded_image_with_path_raises(self, tmp_path) -> None:
        original = tmp_path / "screenshot_001.png"
        Image.new("RGB", (4, 4), (255, 0, 0)).save(original)
        screenshot = Screenshot(id=1, action_id=1, timestamp=1.0, path=str(original))

        with pytest.raises(UnscrubbedScreenshot) as excinfo:
            screenshot.scrub(_StubScrubber())

        assert str(original) in str(excinfo.value)

    def test_recording_scrub_raises_rather_than_returning_unscrubbed_paths(self, tmp_path) -> None:
        original = tmp_path / "screenshot_001.png"
        Image.new("RGB", (4, 4), (255, 0, 0)).save(original)
        recording = Recording(
            id=1,
            screenshots=[Screenshot(id=1, action_id=1, timestamp=1.0, path=str(original))],
        )

        with pytest.raises(UnscrubbedScreenshot):
            recording.scrub(_StubScrubber(), scrub_images=True)

    def test_scrubbed_screenshot_does_not_name_the_original_file(self, tmp_path) -> None:
        original = tmp_path / "screenshot_001.png"
        image = Image.new("RGB", (4, 4), (255, 0, 0))
        image.save(original)
        screenshot = Screenshot(id=1, action_id=1, timestamp=1.0, image=image, path=str(original))

        scrubbed = screenshot.scrub(_StubScrubber())

        # The file on disk still holds unredacted pixels; only `image` was
        # redacted. Carrying `path` forward would serialize a scrubbed
        # recording that points at the unscrubbed original.
        assert scrubbed.path is None
        assert scrubbed.image.getpixel((0, 0)) == (0, 0, 0)

    def test_empty_screenshot_is_still_a_no_op(self) -> None:
        screenshot = Screenshot(id=1, action_id=1, timestamp=1.0)

        scrubbed = screenshot.scrub(_StubScrubber())

        assert scrubbed.image is None
        assert scrubbed.path is None

    def test_text_only_scrub_omits_raw_screenshot_content(self, tmp_path) -> None:
        original = tmp_path / "screenshot_001.png"
        image = Image.new("RGB", (4, 4), (255, 0, 0))
        image.save(original)
        recording = Recording(
            task_description="Patient John Smith",
            screenshots=[
                Screenshot(
                    id=1,
                    action_id=1,
                    timestamp=1.0,
                    image=image,
                    path=str(original),
                )
            ],
        )

        scrubbed = recording.scrub(_TextStubScrubber(), scrub_images=False)

        assert scrubbed.screenshots[0].image is None
        assert scrubbed.screenshots[0].path is None
        assert scrubbed.metadata["_openadapt_privacy"]["omitted_modalities"] == [Modality.PIL_IMAGE]


class TestScrubAdmissionAndEvidence:
    def test_dependency_failure_happens_before_source_processing(self) -> None:
        scrubber = _UnavailableTextScrubber()
        recording = Recording(
            task_description="Patient John Smith",
            actions=[Action(id=1, action_type="type", timestamp=1.0, text="secret")],
        )

        with pytest.raises(ScrubbingProviderUnavailable):
            recording.scrub(scrubber, scrub_images=False)

        assert scrubber.calls == 0

    def test_policy_change_during_scrub_discards_the_result(self) -> None:
        original = config.SCRUB_CHAR
        try:
            with pytest.raises(ScrubbingPolicyChanged):
                Recording(task_description="Patient John Smith").scrub(
                    _PolicyMutatingScrubber(), scrub_images=False
                )
        finally:
            config.SCRUB_CHAR = original

    def test_completed_scrub_attaches_policy_and_version_provenance(self) -> None:
        recording = Recording(task_description="Patient John Smith")

        scrubbed = recording.scrub(_TextStubScrubber(), scrub_images=False)

        evidence = scrubbed.metadata["_openadapt_privacy"]
        assert evidence == {
            "schema_version": 1,
            "provider": "text-stub",
            "provider_class": ("tests.test_no_silent_scrub_bypass._TextStubScrubber"),
            "package_version": openadapt_privacy.__version__,
            "policy_sha256": config.policy_digest(),
            "modalities": [Modality.TEXT],
            "status": "completed",
            "omitted_modalities": [Modality.PIL_IMAGE],
        }
        assert "John Smith" not in repr(evidence)
