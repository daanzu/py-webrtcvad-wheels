"""Fast positive/negative tests for the release artifact gate."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from packaging.tags import parse_tag
import yaml

import validate_artifacts as validator


class ArtifactValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dist = self.root / "dist"
        self.expected = self.root / "expected"
        self.dist.mkdir()
        self.expected.mkdir()
        self.runners, self.cibw_version = validator.build_configuration(validator.WORKFLOW)
        # Independent fixtures for the declared supported matrix, including PyPy
        # availability differences. Production code never relies on this count.
        cp = [f"cp3{minor}" for minor in range(10, 15)]
        linux = [f"{py}-{family}_{arch}" for py in cp
                 for family in ("manylinux", "musllinux")
                 for arch in ("x86_64", "i686", "aarch64", "ppc64le")]
        linux += [f"pp311-manylinux_{arch}" for arch in ("x86_64", "i686", "aarch64")]
        self.manifests = {
            "ubuntu-latest": linux,
            "windows-latest": [f"{py}-{arch}" for py in cp for arch in ("win32", "win_amd64")] + ["pp311-win_amd64"],
            "macos-15-intel": [f"{py}-macosx_x86_64" for py in cp + ["pp311"]],
            "macos-15": [f"{py}-macosx_arm64" for py in cp + ["pp311"]],
        }
        for runner, identifiers in self.manifests.items():
            self.write_manifest(runner, identifiers)
            for identifier in identifiers:
                self.write_wheel(identifier)
        self.write_sdist()

    def write_manifest(self, runner, identifiers, version=None):
        (self.expected / f"{runner}.json").write_text(json.dumps({
            "cibuildwheel": version or self.cibw_version, "identifiers": identifiers,
        }))

    def write_wheel(self, identifier, version="2.0.14", platform_override=None):
        py, platform = identifier.split("-", 1)
        abi = py if py.startswith("cp") else "pypy311_pp73"
        if platform.startswith("manylinux_"):
            arch = platform.removeprefix("manylinux_")
            platform = f"manylinux2014_{arch}.manylinux_2_17_{arch}"
        elif platform.startswith("musllinux_"):
            platform = platform.replace("musllinux_", "musllinux_1_2_")
        elif platform.startswith("macosx_"):
            platform = platform.replace("macosx_", "macosx_11_0_")
        filename = f"webrtcvad_wheels-{version}-{py}-{abi}-{platform_override or platform}.whl"
        path = self.dist / filename
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(f"webrtcvad_wheels-{version}.dist-info/METADATA", "Name: webrtcvad-wheels\n")
        return path

    def write_sdist(self, fixtures=("test_webrtcvad.py", "test-audio.raw")):
        path = self.dist / "webrtcvad_wheels-2.0.14.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for fixture in fixtures:
                member = tarfile.TarInfo(f"webrtcvad_wheels-2.0.14/{fixture}")
                archive.addfile(member, io.BytesIO())
        return path

    def validate(self):
        with redirect_stdout(io.StringIO()) as output:
            validator.validate(self.dist, self.expected)
        return output.getvalue()

    def test_complete_matrix(self):
        self.assertEqual(len(list(self.dist.glob("*.whl"))), 66)
        self.assertIn("all 66 expected wheels", self.validate())

    def test_missing_wheel(self):
        next(self.dist.glob("*cp314*win32.whl")).unlink()
        with self.assertRaisesRegex(ValueError, "missing=.*cp314"):
            self.validate()

    def test_missing_target_replaced_with_extra_keeps_count(self):
        next(self.dist.glob("*cp314*win32.whl")).unlink()
        self.write_wheel("cp315-win32")
        with self.assertRaisesRegex(ValueError, "Wheel coverage differs"):
            self.validate()

    def test_duplicate_logical_wheel(self):
        self.write_wheel("cp310-manylinux_x86_64", platform_override="manylinux_2_17_x86_64")
        with self.assertRaisesRegex(ValueError, "unexpected=.*cp310"):
            self.validate()

    def test_wrong_abi(self):
        path = next(self.dist.glob("*cp311-cp311-win32.whl"))
        path.rename(path.with_name(path.name.replace("cp311-cp311", "cp311-cp310")))
        with self.assertRaisesRegex(ValueError, "Unexpected ABI"):
            self.validate()

    def test_wrong_architecture(self):
        path = next(self.dist.glob("*cp310*macosx*arm64.whl"))
        path.rename(path.with_name(path.name.replace("arm64", "universal2")))
        with self.assertRaisesRegex(ValueError, "Wheel coverage differs"):
            self.validate()

    def test_manylinux_aliases_are_one_target(self):
        tags = parse_tag("cp310-cp310-manylinux1_i686.manylinux2014_i686.manylinux_2_5_i686.manylinux_2_17_i686")
        self.assertEqual(validator.wheel_target(tags), ("cp310", "cp310", "manylinux_i686"))

    def test_macos_deployment_aliases(self):
        for py, abi, deployment, arch in (
            ("cp310", "cp310", "10_9", "x86_64"),
            ("cp312", "cp312", "10_13", "x86_64"),
            ("cp314", "cp314", "10_15", "x86_64"),
            ("pp311", "pypy311_pp73", "10_15", "x86_64"),
            ("pp311", "pypy311_pp73", "11_0", "arm64"),
        ):
            with self.subTest(py=py, arch=arch):
                self.assertEqual(
                    validator.wheel_target(parse_tag(f"{py}-{abi}-macosx_{deployment}_{arch}")),
                    (py, abi, f"macosx_{arch}"),
                )

    def test_mixed_compressed_tags_rejected(self):
        for platform in ("manylinux2014_x86_64.musllinux_1_2_x86_64", "macosx_11_0_arm64.macosx_10_15_x86_64"):
            with self.subTest(platform=platform), self.assertRaisesRegex(ValueError, "multiple build targets"):
                validator.wheel_target(parse_tag(f"cp311-cp311-{platform}"))

    def test_invalid_tags_rejected(self):
        for tag in ("cp311-abi3-win32", "cp311-none-win32", "py3-none-any", "pp311-pypy311_pp74-win_amd64", "cp311-cp311-linux_x86_64", "cp311-cp311-manylinux_x86_64", "cp311-cp311-macosx_arm64"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                validator.wheel_target(parse_tag(tag))

    def test_missing_or_extra_manifest(self):
        path = self.expected / "macos-15.json"
        saved = path.read_text()
        path.unlink()
        with self.assertRaisesRegex(ValueError, "Expectation files differ"):
            self.validate()
        path.write_text(saved)
        (self.expected / "extra.json").write_text(saved)
        with self.assertRaisesRegex(ValueError, "Expectation files differ"):
            self.validate()

    def test_empty_duplicate_and_stale_manifests(self):
        for identifiers, version in (([], None), (["cp310-win32", "cp310-win32"], None), (["cp310-win32"], "0.0.0")):
            with self.subTest(identifiers=identifiers, version=version):
                self.write_manifest("windows-latest", identifiers, version)
                with self.assertRaises(ValueError):
                    self.validate()

    def test_mismatched_distribution_version(self):
        path = next(self.dist.glob("*win32.whl"))
        path.rename(path.with_name(path.name.replace("2.0.14", "2.0.15")))
        with self.assertRaisesRegex(ValueError, "version mismatch"):
            self.validate()

    def test_flat_layout_and_unexpected_files(self):
        extra = self.dist / "unexpected"
        extra.mkdir()
        with self.assertRaisesRegex(ValueError, "flattened"):
            self.validate()
        extra.rmdir()
        extra.write_text("unexpected")
        with self.assertRaisesRegex(ValueError, "Unexpected distribution files"):
            self.validate()

    def test_missing_or_multiple_sdists(self):
        path = self.dist / "webrtcvad_wheels-2.0.14.tar.gz"
        shutil.copy(path, self.dist / "webrtcvad_wheels-2.0.15.tar.gz")
        with self.assertRaisesRegex(ValueError, "Expected one sdist"):
            self.validate()
        for sdist in self.dist.glob("*.tar.gz"):
            sdist.unlink()
        with self.assertRaisesRegex(ValueError, "Expected one sdist"):
            self.validate()

    def test_corrupt_wheel_and_missing_metadata(self):
        path = next(self.dist.glob("*.whl"))
        path.write_bytes(b"not a zip")
        with self.assertRaises(zipfile.BadZipFile):
            self.validate()
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("unrelated", "test")
        with self.assertRaisesRegex(ValueError, "Missing wheel metadata"):
            self.validate()

    def test_missing_sdist_fixture(self):
        self.write_sdist(("test_webrtcvad.py",))
        with self.assertRaisesRegex(ValueError, "Missing sdist fixture"):
            self.validate()

    @patch.object(validator.subprocess, "run")
    def test_generator_uses_cibuildwheel_selection(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "cp310-win32\ncp311-win32\n")
        with redirect_stdout(io.StringIO()):
            validator.write_expectations(self.expected, "windows-latest")
        saved = json.loads((self.expected / "windows-latest.json").read_text())
        self.assertEqual(saved["identifiers"], ["cp310-win32", "cp311-win32"])
        self.assertIn("--print-build-identifiers", run.call_args.args[0])
        self.assertNotIn("env", run.call_args.kwargs)  # Inherit actual native build settings.
        for output in ("", "cp310-win32\ncp310-win32\n"):
            run.return_value.stdout = output
            with self.assertRaises(ValueError):
                validator.write_expectations(self.expected, "windows-latest")

    @patch.object(validator, "version", return_value="0.0.0")
    def test_generator_version_must_match_action(self, _version):
        with self.assertRaisesRegex(ValueError, "versions differ"):
            validator.write_expectations(self.expected, "windows-latest")

    def test_publication_requires_validation_and_release_event(self):
        jobs = yaml.safe_load(validator.WORKFLOW.read_text())["jobs"]
        self.assertIn("validate_artifacts", jobs["upload_pypi"]["needs"])
        self.assertEqual(jobs["upload_pypi"]["if"], "(github.event_name == 'release' && github.event.action == 'published') || (github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v'))")
        downloads = [s["with"]["pattern"] for s in jobs["upload_pypi"]["steps"] if s.get("uses", "").startswith("actions/download-artifact@")]
        self.assertEqual(downloads, ["cibw-*"])


if __name__ == "__main__":
    unittest.main()
