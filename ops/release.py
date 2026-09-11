"""Release helper shared by CI and developers.

    python ops/release.py current            -> prints the version in pyproject.toml
    python ops/release.py prepare 0.3.0      -> bumps the version and turns [Unreleased] into [0.3.0] - today
    python ops/release.py notes 0.3.0        -> prints the CHANGELOG section of that version (release body)
"""

import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
PACKAGE_INIT = ROOT / "app" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
SECTION = re.compile(r"^## \[(?P<name>[^\]]+)\]", re.MULTILINE)


def current_version() -> str:
    match = re.search(r'^version = "([^"]+)"', PYPROJECT.read_text(), re.MULTILINE)
    if not match:
        raise SystemExit("version not found in pyproject.toml")
    return match.group(1)


def _parse(version: str) -> tuple[int, int, int]:
    match = SEMVER.match(version)
    if not match:
        raise SystemExit(f"'{version}' is not a semantic version (X.Y.Z)")
    return tuple(int(part) for part in match.groups())


def section(changelog: str, name: str) -> str:
    """Body of `## [name]` up to the next `## [` heading."""
    headings = list(SECTION.finditer(changelog))
    for index, heading in enumerate(headings):
        if heading.group("name") == name:
            end = headings[index + 1].start() if index + 1 < len(headings) else len(changelog)
            body = changelog[heading.end():end]
            return body.split("\n", 1)[1].strip() if "\n" in body else ""
    raise SystemExit(f"CHANGELOG.md has no section [{name}]")


def prepare(version: str, today: date | None = None) -> None:
    if _parse(version) <= _parse(current_version()):
        raise SystemExit(f"{version} must be greater than the current version {current_version()}")
    changelog = CHANGELOG.read_text()
    unreleased = section(changelog, "Unreleased")
    if not unreleased:
        raise SystemExit("[Unreleased] is empty: write the release notes in CHANGELOG.md first")
    released_on = (today or date.today()).isoformat()
    head, _, rest = changelog.partition("## [Unreleased]\n")
    next_heading = SECTION.search(rest)
    tail = rest[next_heading.start():] if next_heading else ""
    # The notes move under the new version heading; [Unreleased] stays, empty, on top.
    CHANGELOG.write_text(f"{head}## [Unreleased]\n\n## [{version}] - {released_on}\n\n{unreleased}\n\n{tail}")
    PYPROJECT.write_text(re.sub(r'^version = "[^"]+"', f'version = "{version}"', PYPROJECT.read_text(), count=1, flags=re.MULTILINE))
    PACKAGE_INIT.write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', PACKAGE_INIT.read_text(), count=1))
    print(f"Prepared {version}")


def main(argv: list[str]) -> None:
    if len(argv) >= 2 and argv[1] == "current":
        print(current_version())
    elif len(argv) == 3 and argv[1] == "prepare":
        prepare(argv[2])
    elif len(argv) == 3 and argv[1] == "notes":
        print(section(CHANGELOG.read_text(), argv[2]))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
