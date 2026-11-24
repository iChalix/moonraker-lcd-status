"""Versionierung: Abgleich von __version__ und CHANGELOG, Logik von release.py."""

import importlib.util
import os
import re
import unittest

import moonraker_lcd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_spec = importlib.util.spec_from_file_location(
    "release_script", os.path.join(ROOT, "scripts", "release.py")
)
release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release)


def changelog_text():
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as handle:
        return handle.read()


SAMPLE = """# Changelog

Einleitung.

## [Unreleased]

### Hinzugefuegt
- Neue Funktion

### Behoben
- Ein Fehler

## [1.1.0] - 2026-11-18

Erste Version.

### Hinzugefuegt
- Alles
"""


class ProjectConsistencyTest(unittest.TestCase):
    """Verhindert, dass Version und CHANGELOG auseinanderlaufen."""

    def test_version_is_semver(self):
        release.parse_version(moonraker_lcd.__version__)

    def test_version_matches_latest_changelog_entry(self):
        self.assertEqual(
            moonraker_lcd.__version__,
            release.latest_released(changelog_text()),
            "Bei einem Release wird beides gemeinsam von scripts/release.py geaendert",
        )

    def test_changelog_has_unreleased_section(self):
        self.assertRegex(changelog_text(), r"(?m)^## \[Unreleased\]\s*$")

    def test_released_sections_are_dated(self):
        for line in re.findall(r"(?m)^## \[\d+\.\d+\.\d+\].*$", changelog_text()):
            self.assertRegex(line, r"^## \[\d+\.\d+\.\d+\] - \d{4}-\d{2}-\d{2}$")

    def test_notes_exist_for_current_version(self):
        if moonraker_lcd.__version__ == release.UNRELEASED_VERSION:
            self.skipTest("noch kein Release")
        self.assertTrue(release.notes_for(changelog_text(), moonraker_lcd.__version__))

    def test_describe_starts_with_version(self):
        self.assertTrue(moonraker_lcd.describe().startswith(moonraker_lcd.__version__))


class VersionLogicTest(unittest.TestCase):
    def test_bump(self):
        self.assertEqual(release.bump("1.2.3", "patch"), "1.2.4")
        self.assertEqual(release.bump("1.2.3", "minor"), "1.3.0")
        self.assertEqual(release.bump("1.2.3", "major"), "2.0.0")

    def test_bump_unknown_kind(self):
        with self.assertRaises(release.ReleaseError):
            release.bump("1.2.3", "mega")

    def test_resolve_explicit_version(self):
        self.assertEqual(release.resolve_version("1.4.0", "1.2.3"), "1.4.0")
        self.assertEqual(release.resolve_version("minor", "1.2.3"), "1.3.0")

    def test_resolve_rejects_equal_or_lower(self):
        for bad in ("1.2.3", "1.2.2", "0.9.0"):
            with self.assertRaises(release.ReleaseError, msg=bad):
                release.resolve_version(bad, "1.2.3")

    def test_resolve_compares_numerically_not_as_text(self):
        self.assertEqual(release.resolve_version("1.10.0", "1.9.0"), "1.10.0")

    def test_invalid_versions(self):
        for bad in ("1.2", "v1.2.3", "1.2.3-rc1", "", "abc"):
            with self.assertRaises(release.ReleaseError, msg=bad):
                release.parse_version(bad)

    def test_read_and_set_version(self):
        text = 'x = 1\n__version__ = "1.1.0"\ny = 2\n'
        self.assertEqual(release.read_version(text), "1.1.0")
        self.assertEqual(
            release.set_version(text, "1.2.0"), 'x = 1\n__version__ = "1.2.0"\ny = 2\n'
        )

    def test_missing_version_in_init(self):
        with self.assertRaises(release.ReleaseError):
            release.read_version("nichts = 1\n")
        with self.assertRaises(release.ReleaseError):
            release.set_version("nichts = 1\n", "1.0.0")


class ChangelogLogicTest(unittest.TestCase):
    def test_before_the_first_release(self):
        self.assertEqual(release.latest_released("# C\n\n## [Unreleased]\n- x\n"), "0.0.0")

    def test_latest_released(self):
        self.assertEqual(release.latest_released(SAMPLE), "1.1.0")

    def test_unreleased_notes(self):
        notes = release.unreleased_notes(SAMPLE)
        self.assertIn("Neue Funktion", notes)
        self.assertIn("Ein Fehler", notes)
        self.assertNotIn("Erste Version", notes)

    def test_promote_creates_dated_section_and_new_empty_unreleased(self):
        result = release.promote_unreleased(SAMPLE, "1.2.0", "2026-12-01")
        self.assertRegex(result, r"(?s)## \[Unreleased\]\n\n## \[1\.2\.0\] - 2026-12-01\n\n### Hinzugefuegt")
        self.assertEqual(release.latest_released(result), "1.2.0")
        self.assertIn("Einleitung.", result)
        # die alte Version bleibt unveraendert darunter
        self.assertIn("## [1.1.0] - 2026-11-18", result)
        self.assertIn("Erste Version.", result)

    def test_promoted_unreleased_is_empty_again(self):
        result = release.promote_unreleased(SAMPLE, "1.2.0", "2026-12-01")
        with self.assertRaises(release.ReleaseError):
            release.unreleased_notes(result)

    def test_notes_for_version(self):
        result = release.promote_unreleased(SAMPLE, "1.2.0", "2026-12-01")
        notes = release.notes_for(result, "1.2.0")
        self.assertIn("Neue Funktion", notes)
        self.assertNotIn("Erste Version", notes)
        self.assertNotIn("1.1.0", notes)
        self.assertIn("Erste Version.", release.notes_for(result, "1.1.0"))

    def test_notes_for_unknown_version(self):
        with self.assertRaises(release.ReleaseError):
            release.notes_for(SAMPLE, "9.9.9")

    def test_empty_unreleased_blocks_a_release(self):
        empty = SAMPLE.replace(
            "### Hinzugefuegt\n- Neue Funktion\n\n### Behoben\n- Ein Fehler\n",
            "### Hinzugefuegt\n\n### Behoben\n",
        )
        with self.assertRaises(release.ReleaseError):
            release.promote_unreleased(empty, "1.2.0", "2026-12-01")

    def test_missing_unreleased_section(self):
        with self.assertRaises(release.ReleaseError):
            release.promote_unreleased("# Changelog\n\n## [1.1.0] - 2026-11-18\n- x\n", "1.2.0", "2026-12-01")

    def test_unreleased_as_last_section(self):
        text = "# Changelog\n\n## [Unreleased]\n\n- Nur dies\n"
        result = release.promote_unreleased(text, "0.1.0", "2026-12-01")
        self.assertIn("## [0.1.0] - 2026-12-01", result)
        self.assertIn("- Nur dies", result)

    def test_real_changelog_can_be_promoted(self):
        """Das echte CHANGELOG hat Inhalt unter [Unreleased] - sonst kaeme man nicht zum Release."""
        text = changelog_text()
        try:
            release.unreleased_notes(text)
        except release.ReleaseError:
            self.skipTest("[Unreleased] ist leer (direkt nach einem Release)")
        promoted = release.promote_unreleased(text, "99.0.0", "2099-01-01")
        self.assertEqual(release.latest_released(promoted), "99.0.0")


if __name__ == "__main__":
    unittest.main()
