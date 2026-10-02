"""Check that a release's tag, version and dates agree before it is uploaded.

publish.yml runs this on the release event, ahead of the build, so a GitHub release whose
files disagree with it never reaches PyPI. The tag without its leading v names the
version, and __version__, CITATION.cff, the README's citation and the fallback in
mkdocs.yml must all give it. Of these, the README matters most, because it becomes the
release's project description on PyPI, which cannot be changed after the upload.
CITATION.cff's date-released and the newest dated section of CHANGELOG.md must both name
the UTC date on which the GitHub release was published, and the README's citation must
give that date's year.

The check belongs to the release event alone. CONTRIBUTING.md's first release step bumps
__version__ well before the tag exists, and until the tagged commit CITATION.cff and the
changelog go on naming the last release, so between releases these files disagree by
design. tests/test_release_metadata.py covers what holds at every commit.

It uses the standard library only, so it runs before anything is installed:

    python tools/check_release.py --tag v0.4.0 --published-at 2026-10-02T14:03:22Z

Without --published-at it compares the files with today's UTC date, for a run by hand
on the release commit before anything is published. It exits 1 and names every
disagreement it finds.
"""

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DATED_SECTION = re.compile(r"^## \[([^\]]+)\] - (\d{4}-\d{2}-\d{2})[ \t]*$", re.MULTILINE)

DOCS_FALLBACK = re.compile(
    r"^\s+version:\s*!ENV\s*\[\s*SCOPUSFLOW_RELEASED_VERSION\s*,\s*[\"']([^\"']*)[\"']\s*\]",
    re.MULTILINE,
)


def _read(root, *parts):
    return Path(root).joinpath(*parts).read_text(encoding="utf-8")


def _scalar(text, key, where):
    # A top-level YAML scalar, quoted or not. The anchor at the start of the line keeps
    # CITATION.cff's opening cff-version from passing for its version.
    match = re.search(rf"^{re.escape(key)}:[ \t]*[\"']?([^\"'\s#]+)", text, re.MULTILINE)
    if match is None:
        raise ValueError(f"{where} has no {key} field")
    return match.group(1)


def package_version(root=ROOT):
    """The __version__ set in src/scopusflow/__init__.py, where pyproject.toml reads it."""
    text = _read(root, "src", "scopusflow", "__init__.py")
    match = re.search(r"^__version__\s*=\s*[\"']([^\"']+)[\"']", text, re.MULTILINE)
    if match is None:
        raise ValueError("src/scopusflow/__init__.py sets no __version__")
    return match.group(1)


def citation_release(root=ROOT):
    """The version and date-released that CITATION.cff records, as a pair of strings."""
    text = _read(root, "CITATION.cff")
    return (
        _scalar(text, "version", "CITATION.cff"),
        _scalar(text, "date-released", "CITATION.cff"),
    )


def dated_sections(root=ROOT):
    """Every "## [version] - YYYY-MM-DD" heading in CHANGELOG.md, newest first."""
    return DATED_SECTION.findall(_read(root, "CHANGELOG.md"))


def readme_citations(root=ROOT):
    """The version and year of each citation in README.md, as pairs of strings.

    A citation is a line naming a "Python package version". Its year is the first
    four-digit year in brackets on that line, or None where it has none.
    """
    found = []
    for line in _read(root, "README.md").splitlines():
        version = re.search(r"Python package version (\d+(?:\.\d+)*)", line)
        if version:
            year = re.search(r"\((\d{4})\)", line)
            found.append((version.group(1), year.group(1) if year else None))
    return found


def docs_fallback(root=ROOT):
    """The version mkdocs.yml shows in the header when SCOPUSFLOW_RELEASED_VERSION is unset.

    None if mkdocs.yml does not read the variable with a fallback.
    """
    match = DOCS_FALLBACK.search(_read(root, "mkdocs.yml"))
    return match.group(1) if match else None


def release_day(published_at=None):
    """The UTC date of a timestamp such as GitHub's 2026-10-02T14:03:22Z.

    Without a timestamp it is today's UTC date, for a run by hand before a release.
    """
    if published_at is None:
        return datetime.now(timezone.utc).date().isoformat()
    # datetime.fromisoformat() reads a trailing Z only from Python 3.11 on.
    stamp = datetime.fromisoformat(published_at.strip().replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).date().isoformat()


def release_problems(root, tag, published_at):
    """Every disagreement between a release and the files it ships, as messages."""
    problems = []
    if not tag.startswith("v"):
        problems.append(f"The tag {tag} does not have the form v<version>.")
    version = tag[1:] if tag.startswith("v") else tag
    day = release_day(published_at)

    current = package_version(root)
    if current != version:
        problems.append(f"__version__ is {current}, but the tag is {tag}.")

    cited, cited_on = citation_release(root)
    if cited != version:
        problems.append(f"CITATION.cff gives version {cited}, but the tag is {tag}.")
    if cited_on != day:
        problems.append(
            f"CITATION.cff gives date-released {cited_on}, but the release was "
            f"published on {day} (UTC)."
        )

    sections = dated_sections(root)
    if not sections:
        problems.append("CHANGELOG.md has no dated section.")
    elif sections[0] != (version, day):
        newest, newest_on = sections[0]
        problems.append(
            f"The newest dated section of CHANGELOG.md is [{newest}] - {newest_on}, "
            f"but this release is [{version}] - {day}."
        )

    citations = readme_citations(root)
    if not citations:
        problems.append("README.md has no citation naming a Python package version.")
    for readme_version, readme_year in citations:
        if (readme_version, readme_year) != (version, day[:4]):
            problems.append(
                f"README.md cites version {readme_version} ({readme_year}), but this "
                f"release is {version} ({day[:4]})."
            )

    fallback = docs_fallback(root)
    if fallback is None:
        problems.append(
            "mkdocs.yml does not read SCOPUSFLOW_RELEASED_VERSION with a fallback version."
        )
    elif fallback != version:
        problems.append(f"mkdocs.yml falls back on version {fallback}, but the tag is {tag}.")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", required=True, help="the release's tag, such as v0.4.0")
    parser.add_argument(
        "--published-at",
        help="when the release was published, in ISO 8601 as GitHub reports it "
        "(default: now, for a run by hand before publishing)",
    )
    parser.add_argument(
        "--root", default=ROOT, help="the repository root (default: the parent of tools/)"
    )
    args = parser.parse_args(argv)
    try:
        problems = release_problems(args.root, args.tag, args.published_at)
    except (OSError, ValueError) as exc:
        problems = [str(exc)]
    if problems:
        for problem in problems:
            print(f"check_release: {problem}", file=sys.stderr)
        return 1
    print(
        f"check_release: {args.tag} agrees with __version__, CITATION.cff, CHANGELOG.md, "
        f"README.md and mkdocs.yml, dated {release_day(args.published_at)}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
