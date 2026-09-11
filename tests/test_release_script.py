from datetime import date

import pytest

from ops import release


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.2.0"\n')
    (tmp_path / "app" / "__init__.py").write_text('__version__ = "0.2.0"\n')
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\nIntro.\n\n## [Unreleased]\n\n### Added\n- Nueva cosa.\n\n## [0.2.0] - 2026-09-11\n\n### Fixed\n- Algo.\n"
    )
    monkeypatch.setattr(release, "PYPROJECT", tmp_path / "pyproject.toml")
    monkeypatch.setattr(release, "PACKAGE_INIT", tmp_path / "app" / "__init__.py")
    monkeypatch.setattr(release, "CHANGELOG", tmp_path / "CHANGELOG.md")
    return tmp_path


def test_prepare_moves_unreleased_notes_under_the_new_version(repo):
    release.prepare("0.3.0", today=date(2026, 10, 1))

    changelog = (repo / "CHANGELOG.md").read_text()
    assert changelog == (
        "# Changelog\n\nIntro.\n\n## [Unreleased]\n\n## [0.3.0] - 2026-10-01\n\n### Added\n- Nueva cosa.\n\n"
        "## [0.2.0] - 2026-09-11\n\n### Fixed\n- Algo.\n"
    )
    assert release.current_version() == "0.3.0"
    assert '__version__ = "0.3.0"' in (repo / "app" / "__init__.py").read_text()
    assert release.section(changelog, "0.3.0") == "### Added\n- Nueva cosa."


def test_prepare_refuses_empty_notes_or_older_versions(repo):
    with pytest.raises(SystemExit, match="greater"):
        release.prepare("0.1.9")
    release.prepare("0.3.0")
    with pytest.raises(SystemExit, match="empty"):
        release.prepare("0.4.0")


def test_real_changelog_has_notes_for_the_current_version():
    notes = release.section(release.CHANGELOG.read_text(), release.current_version())
    assert "Reserva con seña" in notes
