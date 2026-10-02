"""Release metadata: nothing presents a version as released before it is.

The changelog, CITATION.cff, the README citation, the About page and the documentation's
header all named 0.4.0 as released while PyPI carried 0.3.0. A reader who installed from
PyPI and followed the home page met an AttributeError. These tests read the files around
the package and skip where the package is tested apart from its repository. The readers
and the release-day check come from tools/check_release.py, which the publish workflow
runs when a release is published.
"""

import importlib.util
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

import scopusflow

ROOT = Path(__file__).resolve().parents[1]


def _in_repository():
    if not (ROOT / "mkdocs.yml").exists():
        pytest.skip("the repository files are not part of an installed distribution")


def _checker():
    # Skip only outside the repository, since inside it a missing checker is a failure.
    _in_repository()
    path = ROOT / "tools" / "check_release.py"
    spec = importlib.util.spec_from_file_location("check_release", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The tests in this group read the repository's own files, and each holds at every
# commit. Between releases the files name the last release, and the commit tagged for a
# release moves them all at once.


def test_the_checker_reads_the_version_the_package_sets():
    assert _checker().package_version(ROOT) == scopusflow.__version__


def test_the_citation_names_the_newest_dated_changelog_section():
    checker = _checker()
    assert checker.citation_release(ROOT) == checker.dated_sections(ROOT)[0]


def test_the_readme_cites_the_version_and_year_citation_cff_names():
    # The README is PyPI's project description, so a release uploads its citation as
    # written. The year goes stale as easily as the version once a release falls in a
    # new year.
    checker = _checker()
    version, released_on = checker.citation_release(ROOT)
    assert checker.readme_citations(ROOT) == [(version, released_on[:4])]


def test_the_changelog_keeps_unreleased_changes_in_one_section_at_the_top():
    # Every change since the last release goes into one [Unreleased] section above the
    # dated ones, whose compare link starts at the newest release. Two branches that
    # each opened an [Unreleased] section would otherwise merge into two of them.
    checker = _checker()
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## \[([^\]]+)\]", text, re.MULTILINE)
    assert headings.count("Unreleased") <= 1
    if "Unreleased" in headings:
        assert headings[0] == "Unreleased"
    link = re.search(r"^\[Unreleased\]: \S+/compare/v(\S+?)\.\.\.HEAD$", text, re.MULTILINE)
    assert link, "the [Unreleased] link should compare the newest release with HEAD"
    assert link.group(1) == checker.dated_sections(ROOT)[0][0]


def test_versions_presented_as_released_are_tagged():
    # The test pins the defect itself, a dated changelog section and a citation for a
    # version with no tag, no GitHub release and no upload. The tags record what was
    # released. A shallow clone, which is what CI checks out, carries none, so the test
    # skips there and runs in a full clone, where the release steps in CONTRIBUTING.md
    # are taken.
    checker = _checker()
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    try:
        listed = subprocess.run(
            ["git", "-C", str(ROOT), "tag", "--list", "v*"],
            capture_output=True, text=True, check=True,
        ).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git cannot list the tags here")
    if not listed:
        pytest.skip("no release tags in this checkout (a shallow clone fetches none)")
    tagged = {tag[1:] for tag in listed}
    presented = [(version, "CHANGELOG.md") for version, _ in checker.dated_sections(ROOT)]
    presented.append((checker.citation_release(ROOT)[0], "CITATION.cff"))
    assert [
        f"{where} presents {version} as released, but no v{version} tag exists"
        for version, where in presented
        if version not in tagged
    ] == []


def test_the_docs_header_names_the_release_the_tags_record():
    # The header's version chip was typed into mkdocs.yml by hand and ran ahead of PyPI.
    # docs.yml now exports the newest v* tag, and __version__ when it is ahead of that
    # tag. The fallback serves a local build and names the release CITATION.cff cites.
    checker = _checker()
    config = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    fallback = checker.docs_fallback(ROOT)
    assert fallback is not None, "extra.version should read SCOPUSFLOW_RELEASED_VERSION"
    assert fallback == checker.citation_release(ROOT)[0]
    assert re.search(
        r'^\s+dev_version:\s*!ENV\s*\[\s*SCOPUSFLOW_DEV_VERSION\s*,\s*""\s*\]\s*$',
        config, re.MULTILINE,
    ), "extra.dev_version should read SCOPUSFLOW_DEV_VERSION and be empty without it"


def test_the_banner_appears_only_on_a_development_build():
    jinja2 = pytest.importorskip("jinja2")
    _in_repository()
    template = (ROOT / "overrides" / "main.html").read_text(encoding="utf-8")
    # Like mkdocs-material's base.html, the stub draws the banner whenever the announce
    # block renders anything at all, whitespace included.
    base = (
        '{% if self.announce() %}<aside class="md-banner">'
        "{% block announce %}{% endblock %}</aside>{% endif %}"
    )
    env = jinja2.Environment(
        loader=jinja2.DictLoader({"base.html": base, "main.html": template})
    )
    page = env.get_template("main.html")

    def render(dev_version):
        extra = {"version": "0.3.0", "dev_version": dev_version}
        return page.render(config={"extra": extra})

    assert " ".join(render("0.4.0").split()) == (
        '<aside class="md-banner">These pages document the development version 0.4.0. '
        "The release on PyPI is 0.3.0.</aside>"
    )
    assert render("") == ""
    assert render(None) == ""


def test_the_about_page_cites_the_release_citation_cff_records(tmp_path, monkeypatch, capsys):
    # The page printed the installed __version__, so a site built from a development
    # checkout asked readers to cite a version PyPI did not carry. It now cites what
    # CITATION.cff records, which changes only in the commit tagged for a release.
    _in_repository()
    cff = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    cff = re.sub(r"^version:.*$", "version: 9.8.7", cff, flags=re.MULTILINE)
    cff = re.sub(r"^date-released:.*$", 'date-released: "2031-05-06"', cff, flags=re.MULTILINE)
    (tmp_path / "CITATION.cff").write_text(cff, encoding="utf-8")

    page = (ROOT / "docs" / "about.md").read_text(encoding="utf-8")
    block = re.search(r'^````python exec="1"\n(.*?)^````$', page, re.MULTILINE | re.DOTALL)
    assert block, "docs/about.md should build its citation in an executed block"
    # The docs build runs the block from the repository root, where CITATION.cff sits.
    monkeypatch.chdir(tmp_path)
    exec(compile(block.group(1), "docs/about.md", "exec"), {})
    out = capsys.readouterr().out

    assert "Bernabeu, P. (2031)." in out
    assert "Python package version 9.8.7." in out
    assert "note   = {Python package version 9.8.7}," in out
    assert "year   = {2031}," in out


# The release-day check publish.yml runs, on synthetic trees shaped like a release.


def _release_tree(tmp_path, version="1.2.0", cited="1.2.0", cited_on="2031-05-06",
                  section="## [1.2.0] - 2031-05-06", readme=("1.2.0", "2031"),
                  fallback="1.2.0"):
    package = tmp_path / "src" / "scopusflow"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    # cff-version comes first, as in the real file, so a reader that matched "version"
    # anywhere on a line would pick up the format's version in place of the package's.
    (tmp_path / "CITATION.cff").write_text(
        f'cff-version: 1.2.0\ntitle: "scopusflow"\nversion: {cited}\n'
        f'date-released: "{cited_on}"\n',
        encoding="utf-8",
    )
    (tmp_path / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## [Unreleased]\n\n{section}\n\n### Fixed\n\n- A fix.\n\n"
        "## [1.1.0] - 2031-01-10\n\n### Added\n\n- A feature.\n",
        encoding="utf-8",
    )
    readme_version, readme_year = readme
    (tmp_path / "README.md").write_text(
        "# scopusflow\n\n## Citation\n\n"
        f"> Bernabeu, P. ({readme_year}). scopusflow: A workflow layer. Python package "
        f"version {readme_version}. https://doi.org/10.5281/zenodo.21252666\n",
        encoding="utf-8",
    )
    (tmp_path / "mkdocs.yml").write_text(
        f'extra:\n  version: !ENV [SCOPUSFLOW_RELEASED_VERSION, "{fallback}"]\n'
        '  dev_version: !ENV [SCOPUSFLOW_DEV_VERSION, ""]\n',
        encoding="utf-8",
    )
    return tmp_path


def test_release_check_passes_a_release_whose_metadata_agree(tmp_path, capsys):
    checker = _checker()
    tree = _release_tree(tmp_path)
    assert checker.release_problems(tree, "v1.2.0", "2031-05-06T14:03:22Z") == []
    argv = ["--root", str(tree), "--tag", "v1.2.0", "--published-at", "2031-05-06T14:03:22Z"]
    assert checker.main(argv) == 0
    assert "v1.2.0" in capsys.readouterr().out


def test_release_check_reports_a_tag_the_files_do_not_name(tmp_path):
    problems = _checker().release_problems(
        _release_tree(tmp_path), "v1.3.0", "2031-05-06T14:03:22Z"
    )
    assert len(problems) == 5
    assert "__version__ is 1.2.0" in problems[0]
    assert "CITATION.cff gives version 1.2.0" in problems[1]
    assert "CHANGELOG.md" in problems[2]
    assert "README.md cites version 1.2.0 (2031)" in problems[3]
    assert "mkdocs.yml falls back on version 1.2.0" in problems[4]


def test_release_check_reports_a_citation_left_on_the_last_release(tmp_path):
    tree = _release_tree(tmp_path, cited="1.1.0", cited_on="2031-01-10")
    problems = _checker().release_problems(tree, "v1.2.0", "2031-05-06T14:03:22Z")
    assert len(problems) == 2
    assert all(p.startswith("CITATION.cff") for p in problems)


def test_release_check_reports_a_readme_citation_left_on_the_last_release(tmp_path):
    # The README becomes the release's description on PyPI, where a stale citation
    # would stay for good, since an uploaded file cannot be replaced.
    checker = _checker()
    stale = _release_tree(tmp_path / "stale", readme=("1.1.0", "2031"))
    assert checker.release_problems(stale, "v1.2.0", "2031-05-06T14:03:22Z") == [
        "README.md cites version 1.1.0 (2031), but this release is 1.2.0 (2031)."
    ]
    # The first release of a new year keeps last year's citation if only the version
    # is changed.
    last_year = _release_tree(tmp_path / "last-year", readme=("1.2.0", "2030"))
    assert checker.release_problems(last_year, "v1.2.0", "2031-05-06T14:03:22Z") == [
        "README.md cites version 1.2.0 (2030), but this release is 1.2.0 (2031)."
    ]


def test_release_check_reports_a_docs_fallback_left_on_the_last_release(tmp_path):
    problems = _checker().release_problems(
        _release_tree(tmp_path, fallback="1.1.0"), "v1.2.0", "2031-05-06T14:03:22Z"
    )
    assert problems == ["mkdocs.yml falls back on version 1.1.0, but the tag is v1.2.0."]


def test_release_check_reports_a_changelog_section_never_dated(tmp_path):
    # [Unreleased] was not renamed, so the newest dated section is the last release's.
    tree = _release_tree(tmp_path, section="")
    problems = _checker().release_problems(tree, "v1.2.0", "2031-05-06T14:03:22Z")
    assert problems == [
        "The newest dated section of CHANGELOG.md is [1.1.0] - 2031-01-10, "
        "but this release is [1.2.0] - 2031-05-06."
    ]


def test_release_check_dates_the_release_by_its_utc_day(tmp_path):
    checker = _checker()
    tree = _release_tree(tmp_path)
    assert checker.release_problems(tree, "v1.2.0", "2031-05-06T23:59:59Z") == []
    # Half past midnight in a UTC+1 summer is still the previous day in UTC.
    assert checker.release_problems(tree, "v1.2.0", "2031-05-07T00:30:00+01:00") == []
    late = checker.release_problems(tree, "v1.2.0", "2031-05-07T00:00:01Z")
    assert len(late) == 2
    assert all("2031-05-07" in p for p in late)


def test_release_check_dates_a_local_run_by_today_in_utc():
    # Run by hand before a release is published, the check compares with today.
    checker = _checker()
    before = datetime.now(timezone.utc).date().isoformat()
    day = checker.release_day(None)
    after = datetime.now(timezone.utc).date().isoformat()
    assert day in {before, after}


def test_release_check_needs_no_timestamp_when_run_by_hand(tmp_path):
    checker = _checker()
    today = checker.release_day(None)
    tree = _release_tree(
        tmp_path, cited_on=today, section=f"## [1.2.0] - {today}", readme=("1.2.0", today[:4])
    )
    assert checker.main(["--root", str(tree), "--tag", "v1.2.0"]) == 0


def test_release_check_refuses_a_tag_without_the_v_prefix(tmp_path):
    problems = _checker().release_problems(
        _release_tree(tmp_path), "1.2.0", "2031-05-06T14:03:22Z"
    )
    assert problems == ["The tag 1.2.0 does not have the form v<version>."]


def test_release_check_exits_non_zero_and_names_each_problem(tmp_path, capsys):
    tree = _release_tree(tmp_path, cited="1.1.0", cited_on="2031-01-10")
    argv = ["--root", str(tree), "--tag", "v1.2.0", "--published-at", "2031-05-06T14:03:22Z"]
    assert _checker().main(argv) == 1
    err = capsys.readouterr().err
    assert err.count("check_release: CITATION.cff") == 2
