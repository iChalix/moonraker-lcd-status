#!/usr/bin/env python3
"""Schneidet einen Release: Version, CHANGELOG, Commit, Tag, Push, GitHub-Release.

Aufruf (im Projektordner):

    python3 scripts/release.py patch|minor|major     naechste Version berechnen
    python3 scripts/release.py 1.2.0                 Version vorgeben
    python3 scripts/release.py minor --dry-run       nur anzeigen, nichts aendern

Ablauf:

1. Pruefen: sauberer Arbeitsordner, Branch ``main``, nicht hinter ``origin``,
   Tag existiert noch nicht, ``__version__`` und CHANGELOG stimmen ueberein,
   alle Unit-Tests laufen durch.
2. ``[Unreleased]`` im CHANGELOG zu ``[X.Y.Z] - Datum`` machen und
   ``__version__`` in ``moonraker_lcd/__init__.py`` setzen.
3. Nach Rueckfrage: Commit ``Release vX.Y.Z``, annotierter Tag ``vX.Y.Z``,
   Push von ``main`` und Tag, GitHub-Release mit den Eintraegen aus dem
   CHANGELOG (``gh`` muss installiert und angemeldet sein).

Nur die Standardbibliothek. Veroeffentlicht wird erst nach der Rueckfrage;
``--dry-run`` aendert nichts, ``--no-push`` bleibt lokal.
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INIT_FILE = os.path.join("moonraker_lcd", "__init__.py")
CHANGELOG_FILE = "CHANGELOG.md"
BRANCH = "main"
UNRELEASED_VERSION = "0.0.0"

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
INIT_VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)
UNRELEASED_RE = re.compile(r"^## \[Unreleased\]\s*$", re.MULTILINE)
SECTION_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.MULTILINE)


class ReleaseError(Exception):
    """Ein Release ist so nicht moeglich; die Meldung sagt warum."""


# ---------------------------------------------------------------- Versionen


def parse_version(text: str) -> tuple:
    match = VERSION_RE.match(text.strip())
    if not match:
        raise ReleaseError("ungueltige Version %r (erwartet MAJOR.MINOR.PATCH, z. B. 1.2.0)" % text)
    return tuple(int(part) for part in match.groups())


def bump(current: str, kind: str) -> str:
    major, minor, patch = parse_version(current)
    if kind == "major":
        return "%d.0.0" % (major + 1)
    if kind == "minor":
        return "%d.%d.0" % (major, minor + 1)
    if kind == "patch":
        return "%d.%d.%d" % (major, minor, patch + 1)
    raise ReleaseError("unbekannte Art %r (major, minor oder patch)" % kind)


def resolve_version(argument: str, current: str) -> str:
    """``patch``/``minor``/``major`` oder eine explizite Version."""
    if argument in ("major", "minor", "patch"):
        return bump(current, argument)
    version = ".".join(str(part) for part in parse_version(argument))
    if parse_version(version) <= parse_version(current):
        raise ReleaseError(
            "neue Version %s muss groesser sein als die aktuelle %s" % (version, current)
        )
    return version


def read_version(init_text: str) -> str:
    match = INIT_VERSION_RE.search(init_text)
    if not match:
        raise ReleaseError("__version__ nicht in %s gefunden" % INIT_FILE)
    parse_version(match.group(1))
    return match.group(1)


def set_version(init_text: str, version: str) -> str:
    parse_version(version)
    new_text, count = INIT_VERSION_RE.subn('__version__ = "%s"' % version, init_text, count=1)
    if count != 1:
        raise ReleaseError("__version__ nicht in %s gefunden" % INIT_FILE)
    return new_text


# ---------------------------------------------------------------- CHANGELOG


def latest_released(changelog: str) -> str:
    """Zuletzt veroeffentlichte Version; vor dem ersten Release ``0.0.0``."""
    match = SECTION_RE.search(changelog)
    return match.group(1) if match else UNRELEASED_VERSION


def _section_bounds(changelog: str):
    """(Beginn des Inhalts, Ende des Inhalts) von [Unreleased]."""
    match = UNRELEASED_RE.search(changelog)
    if not match:
        raise ReleaseError("Abschnitt '## [Unreleased]' fehlt im CHANGELOG")
    start = match.end()
    following = re.compile(r"^## \[", re.MULTILINE).search(changelog, start)
    end = following.start() if following else len(changelog)
    return start, end


def unreleased_notes(changelog: str) -> str:
    """Inhalt von [Unreleased]; leere Ueberschriften zaehlen nicht als Inhalt."""
    start, end = _section_bounds(changelog)
    body = changelog[start:end].strip()
    has_content = any(
        line.strip() and not line.lstrip().startswith("#") for line in body.splitlines()
    )
    if not has_content:
        raise ReleaseError(
            "[Unreleased] im CHANGELOG ist leer - ohne Eintraege gibt es nichts zu veroeffentlichen"
        )
    return body


def promote_unreleased(changelog: str, version: str, date: str) -> str:
    """[Unreleased] zu [version] - date machen und einen neuen leeren davorsetzen."""
    body = unreleased_notes(changelog)
    start, end = _section_bounds(changelog)
    head = changelog[: UNRELEASED_RE.search(changelog).start()]
    tail = changelog[end:]
    return "%s## [Unreleased]\n\n## [%s] - %s\n\n%s\n\n%s" % (head, version, date, body, tail)


def notes_for(changelog: str, version: str) -> str:
    """Eintraege einer veroeffentlichten Version (fuer GitHub-Release und Tag)."""
    pattern = re.compile(r"^## \[%s\][^\n]*\n" % re.escape(version), re.MULTILINE)
    match = pattern.search(changelog)
    if not match:
        raise ReleaseError("Version %s steht nicht im CHANGELOG" % version)
    following = re.compile(r"^## \[", re.MULTILINE).search(changelog, match.end())
    end = following.start() if following else len(changelog)
    return changelog[match.end() : end].strip()


# ---------------------------------------------------------------- Git


def run(args, cwd=ROOT, check=True):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ReleaseError("%s fehlgeschlagen: %s" % (" ".join(args), detail))
    return result


def git(*args, check=True):
    return run(["git"] + list(args), check=check)


def check_repository(version: str, push: bool) -> None:
    """Alle Voraussetzungen im Git-Klon; wirft ReleaseError mit Begruendung."""
    if git("rev-parse", "--is-inside-work-tree", check=False).stdout.strip() != "true":
        raise ReleaseError("kein Git-Arbeitsordner: %s" % ROOT)

    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != BRANCH:
        raise ReleaseError("Releases nur von '%s', aktuell ist '%s'" % (BRANCH, branch))

    if git("status", "--porcelain").stdout.strip():
        raise ReleaseError("Arbeitsordner nicht sauber - erst committen oder zurueckstellen")

    tag = "v%s" % version
    if git("rev-parse", "-q", "--verify", "refs/tags/%s" % tag, check=False).returncode == 0:
        raise ReleaseError("Tag %s existiert bereits" % tag)

    remotes = git("remote").stdout.split()
    if "origin" not in remotes:
        if push:
            raise ReleaseError("kein Remote 'origin' - mit --no-push lokal arbeiten")
        return

    fetch = git("fetch", "origin", "--tags", check=False)
    if fetch.returncode != 0:
        if push:
            raise ReleaseError("git fetch fehlgeschlagen: %s" % fetch.stderr.strip())
        return
    if git("rev-parse", "-q", "--verify", "refs/remotes/origin/%s" % BRANCH, check=False).returncode == 0:
        behind = git("merge-base", "--is-ancestor", "origin/%s" % BRANCH, "HEAD", check=False)
        if behind.returncode != 0:
            raise ReleaseError(
                "origin/%s hat Commits, die lokal fehlen - erst 'git pull'" % BRANCH
            )
    remote_tag = git("ls-remote", "--tags", "origin", "refs/tags/%s" % tag, check=False).stdout.strip()
    if remote_tag:
        raise ReleaseError("Tag %s existiert bereits auf origin" % tag)


def run_tests() -> None:
    result = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], check=False)
    if result.returncode != 0:
        tail = "\n".join((result.stderr or result.stdout).strip().splitlines()[-12:])
        raise ReleaseError("Tests schlagen fehl, kein Release:\n%s" % tail)


# ---------------------------------------------------------------- Ablauf


def read_file(name: str) -> str:
    with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
        return handle.read()


def write_file(name: str, text: str) -> None:
    with open(os.path.join(ROOT, name), "w", encoding="utf-8") as handle:
        handle.write(text)


def plan(version: str, changelog: str, today: str):
    """Neue Dateiinhalte und Release-Notizen berechnen, ohne etwas zu schreiben."""
    init_text = read_file(INIT_FILE)
    current = read_version(init_text)
    if latest_released(changelog) != current:
        raise ReleaseError(
            "__version__ (%s) und letzte Version im CHANGELOG (%s) stimmen nicht ueberein"
            % (current, latest_released(changelog))
        )
    new_changelog = promote_unreleased(changelog, version, today)
    return set_version(init_text, version), new_changelog, notes_for(new_changelog, version)


def confirm(question: str) -> bool:
    if not sys.stdin.isatty():
        return False
    return input("%s [j/N] " % question).strip().lower() in ("j", "ja", "y", "yes")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("version", help="major, minor, patch oder eine Version wie 1.2.0")
    parser.add_argument("--dry-run", action="store_true", help="nur anzeigen, nichts aendern")
    parser.add_argument("--no-push", action="store_true", help="Commit und Tag nur lokal anlegen")
    parser.add_argument("--no-github", action="store_true", help="kein GitHub-Release anlegen")
    parser.add_argument("--yes", action="store_true", help="Rueckfrage ueberspringen")
    args = parser.parse_args(argv)

    try:
        changelog = read_file(CHANGELOG_FILE)
        current = read_version(read_file(INIT_FILE))
        version = resolve_version(args.version, current)
        tag = "v%s" % version
        push = not args.no_push
        use_github = push and not args.no_github

        check_repository(version, push)
        if use_github and not shutil.which("gh"):
            raise ReleaseError("'gh' nicht gefunden - mit --no-github ohne GitHub-Release")

        new_init, new_changelog, notes = plan(version, changelog, datetime.date.today().isoformat())

        print("Release %s -> %s (Tag %s)" % (current, version, tag))
        print("\n--- Release-Notizen ---\n%s\n-----------------------" % notes)
        steps = ["Tests laufen lassen", "CHANGELOG und __version__ aktualisieren", "Commit und Tag %s" % tag]
        if push:
            steps.append("main und %s nach origin pushen" % tag)
        if use_github:
            steps.append("GitHub-Release %s anlegen" % tag)
        print("Geplant: " + "; ".join(steps))

        if args.dry_run:
            print("\n(--dry-run: nichts geaendert)")
            return 0

        run_tests()

        if not args.yes and not confirm("Jetzt veroeffentlichen?"):
            print("Abgebrochen, nichts geaendert.")
            return 1

        write_file(INIT_FILE, new_init)
        write_file(CHANGELOG_FILE, new_changelog)
        try:
            git("add", INIT_FILE, CHANGELOG_FILE)
            git("commit", "-m", "Release %s" % tag)
        except ReleaseError:
            # Index und Arbeitsordner auf den Stand vor dem Release zuruecksetzen
            git("checkout", "HEAD", "--", INIT_FILE, CHANGELOG_FILE, check=False)
            raise

        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as handle:
            handle.write("Moonraker LCD Status %s\n\n%s\n" % (tag, notes))
            notes_file = handle.name
        try:
            git("tag", "-a", tag, "-F", notes_file)
            print("Commit und Tag %s angelegt." % tag)

            if push:
                git("push", "origin", BRANCH, "refs/tags/%s" % tag)
                print("main und %s gepusht." % tag)
            if use_github:
                with open(notes_file, "w", encoding="utf-8") as handle:
                    handle.write(notes + "\n")
                release = run(
                    ["gh", "release", "create", tag, "--title", tag, "--notes-file", notes_file, "--verify-tag"],
                    check=False,
                )
                if release.returncode != 0:
                    print("GitHub-Release fehlgeschlagen (Tag ist gepusht): %s" % release.stderr.strip())
                    print("Nachholen: gh release create %s --title %s --notes-file <datei>" % (tag, tag))
                    return 1
                print("GitHub-Release: %s" % release.stdout.strip())
        finally:
            os.unlink(notes_file)
    except ReleaseError as exc:
        print("Fehler: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
