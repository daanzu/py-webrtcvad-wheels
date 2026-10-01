"""Check the complete wheel matrix before publishing downloaded distributions.

Expectations come from cibuildwheel's selection on each native build runner,
not from the wheels produced. Policy/deployment version aliases are normalized;
this checks Python/ABI/platform/architecture coverage, not minimum OS policy.
"""

import argparse
from collections import Counter
from importlib.metadata import version
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import zipfile

from packaging.utils import parse_sdist_filename, parse_wheel_filename
import yaml


WORKFLOW = Path(__file__).resolve().parents[1] / "workflows" / "build.yml"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def build_configuration(workflow):
    job = yaml.safe_load(workflow.read_text())["jobs"]["build_wheels"]
    runners = job["strategy"]["matrix"]["os"]
    actions = [step["uses"] for step in job["steps"]
               if step.get("uses", "").startswith("pypa/cibuildwheel@")]
    require(len(actions) == 1, "Expected one pinned cibuildwheel action")
    ref = actions[0].split("@", 1)[1]
    require(re.fullmatch(r"v\d+\.\d+\.\d+", ref), "Pin cibuildwheel to an exact version")
    require(len(runners) == len(set(runners)), "Duplicate build runners")
    return runners, ref[1:]


def expected_abi(interpreter):
    if re.fullmatch(r"cp3\d+", interpreter):
        return interpreter
    # PyPy 3.11 in cibuildwheel 3.3.1 uses the PyPy 7.3 ABI on all platforms.
    # A new PyPy target/ABI needs explicit review rather than a wildcard match.
    require(interpreter == "pp311", f"Unsupported interpreter: {interpreter}")
    return "pypy311_pp73"


def build_target(identifier):
    interpreter, platform = identifier.split("-", 1)
    require(re.fullmatch(r"(manylinux|musllinux|macosx)_[a-z0-9_]+|win32|win_amd64", platform),
            f"Unsupported build platform: {platform}")
    return interpreter, expected_abi(interpreter), platform


def wheel_target(tags):
    targets = set()
    for tag in tags:
        platform = tag.platform
        if platform not in ("win32", "win_amd64"):
            match = re.fullmatch(
                r"(manylinux)(?:1|2010|2014|_\d+_\d+)_([a-z0-9_]+)"
                r"|(musllinux|macosx)_\d+_\d+_([a-z0-9_]+)", platform)
            require(match is not None, f"Unsupported wheel platform: {tag}")
            family, arch, other_family, other_arch = match.groups()
            platform = f"{family or other_family}_{arch or other_arch}"
        require(tag.abi == expected_abi(tag.interpreter), f"Unexpected ABI: {tag}")
        target = build_target(f"{tag.interpreter}-{platform}")
        targets.add(target)
    require(len(targets) == 1, f"Wheel tags cover multiple build targets: {sorted(targets)}")
    return targets.pop()


def write_expectations(directory, runner, workflow=WORKFLOW):
    runners, cibw_version = build_configuration(workflow)
    require(runner in runners, f"Unknown build runner: {runner}")
    require(version("cibuildwheel") == cibw_version, "cibuildwheel action and expectation generator versions differ")
    # Inherit the same CIBW_* environment and native architecture as the build.
    result = subprocess.run([sys.executable, "-m", "cibuildwheel", "--print-build-identifiers"],
                            check=True, text=True, stdout=subprocess.PIPE)
    identifiers = result.stdout.split()
    require(identifiers, f"No build targets selected for {runner}")
    require(len(identifiers) == len(set(identifiers)), f"Duplicate build targets for {runner}")
    for identifier in identifiers:
        build_target(identifier)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{runner}.json").write_text(json.dumps({
        "cibuildwheel": cibw_version, "identifiers": sorted(identifiers)
    }, indent=2) + "\n")
    print(f"Expected {len(identifiers)} wheels for {runner}")


def read_expectations(directory, workflow=WORKFLOW):
    runners, cibw_version = build_configuration(workflow)
    wanted = {f"{runner}.json" for runner in runners}
    actual = {path.name for path in directory.iterdir()}
    require(actual == wanted, f"Expectation files differ: missing={sorted(wanted - actual)}, unexpected={sorted(actual - wanted)}")
    expected = Counter()
    for name in sorted(wanted):
        manifest = json.loads((directory / name).read_text())
        require(manifest["cibuildwheel"] == cibw_version, f"Stale cibuildwheel version in {name}")
        identifiers = manifest["identifiers"]
        require(isinstance(identifiers, list) and identifiers, f"Empty or invalid expectation manifest: {name}")
        expected.update(build_target(identifier) for identifier in identifiers)
    require(all(count == 1 for count in expected.values()), "Duplicate expected build targets")
    return expected


def validate(dist, expectations, workflow=WORKFLOW):
    expected = read_expectations(expectations, workflow)
    files = list(dist.iterdir())
    wheels = sorted(dist.glob("*.whl"))
    sdists = list(dist.glob("*.tar.gz"))
    require(all(path.is_file() for path in files), "Artifacts must be flattened into dist/")
    require(len(sdists) == 1, f"Expected one sdist, found {len(sdists)}")
    require(len(files) == len(wheels) + len(sdists), "Unexpected distribution files")
    project, release_version = parse_sdist_filename(sdists[0].name)
    require(project == "webrtcvad-wheels", f"Unexpected distribution: {project}")
    actual = Counter()
    for wheel in wheels:
        name, wheel_version, build, tags = parse_wheel_filename(wheel.name)
        require((name, wheel_version) == (project, release_version), f"Distribution name/version mismatch: {wheel.name}")
        require(not build, f"Unexpected wheel build tag: {wheel.name}")
        actual[wheel_target(tags)] += 1
        with zipfile.ZipFile(wheel) as archive:
            require(archive.testzip() is None, f"Corrupt wheel: {wheel.name}")
            require(any(name.endswith(".dist-info/METADATA") for name in archive.namelist()),
                    f"Missing wheel metadata: {wheel.name}")
    missing, unexpected = expected - actual, actual - expected
    require(actual == expected, f"Wheel coverage differs: missing={dict(missing)}, unexpected={dict(unexpected)}")
    with tarfile.open(sdists[0]) as archive:
        names = archive.getnames()
        for fixture in ("test_webrtcvad.py", "test-audio.raw"):
            require(any(name.endswith(f"/{fixture}") for name in names), f"Missing sdist fixture: {fixture}")
    print(f"Validated all {sum(expected.values())} expected wheels and one sdist in flat dist/ layout")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-expectations", metavar="RUNNER")
    parser.add_argument("--expectations", type=Path, default=Path("wheel-expectations"))
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    args = parser.parse_args()
    if args.write_expectations:
        write_expectations(args.expectations, args.write_expectations)
    else:
        validate(args.dist, args.expectations)


if __name__ == "__main__":
    main()
