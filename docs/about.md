# About

## Citing scopusflow

If scopusflow contributes to published work, please cite it.

````python exec="1"
# The version used to be written out by hand in three places on this page, and
# one of them had already fallen a whole minor version behind before anyone
# noticed. All three, and the year, now come from CITATION.cff, so they cannot
# drift apart from each other or from the citation GitHub offers. For a while
# they came from the installed package, until a site built from the development
# version asked readers to cite 0.4.0 while PyPI carried 0.3.0. CITATION.cff
# changes only in the commit tagged for a release, so this page names a version
# that exists. The README's citation is a copy that cannot run code, and
# tests/test_release_metadata.py holds it to CITATION.cff. The docs build runs
# from the repository root, where the file is.
import re
import urllib.parse
from pathlib import Path

cff = Path("CITATION.cff").read_text(encoding="utf-8")
version = re.search(r"^version:\s*[\"']?([^\"'\s]+)", cff, re.MULTILINE).group(1)
year = re.search(r"^date-released:\s*[\"']?(\d{4})", cff, re.MULTILINE).group(1)

bibtex = (
    "@Manual{scopusflow-py,\n"
    "  title  = {scopusflow: A reproducible workflow layer over pybliometrics for {Scopus} searches},\n"
    "  author = {Pablo Bernabeu},\n"
    f"  year   = {{{year}}},\n"
    f"  note   = {{Python package version {version}}},\n"
    "  doi    = {10.5281/zenodo.21252666},\n"
    "  url    = {https://doi.org/10.5281/zenodo.21252666},\n"
    "}"
)

# The download link encodes the very string the fenced block below shows, so the
# two can never disagree. safe="" is deliberate, since the default would leave
# the slashes in the DOI and the URL unescaped.
data_uri = "data:application/x-bibtex;charset=utf-8," + urllib.parse.quote(bibtex, safe="")

print(
    f"> Bernabeu, P. ({year}). scopusflow: A reproducible workflow layer over\n"
    "> pybliometrics for Scopus searches. Python package version "
    f"{version}.\n"
    "> https://doi.org/10.5281/zenodo.21252666\n"
)

# The entry is printed as a real fenced block, so that Material still gives it
# BibTeX highlighting and a copy button of its own. Printing a fence from inside
# a fence is why the enclosing one takes four backticks.
print("```bibtex")
print(bibtex)
print("```")

print(f'\n<p><a download="scopusflow-py.bib" href="{data_uri}">Download .bib</a></p>')
````

The repository also carries a machine-readable
[`CITATION.cff`](https://github.com/pablobernabeu/scopusflow-py/blob/main/CITATION.cff),
which GitHub turns into a ready-made citation through the *Cite this repository*
button, and which reference managers can import directly.

## The developer

[Pablo Bernabeu](https://pablobernabeu.github.io/) is a researcher in the
Department of Education at the University of Oxford, with hands-on experience
of behavioural experiments, EEG, corpus analysis, computational modelling and
statistics. He develops open, reproducible research software in R and Python,
and is a Fellow of the Software Sustainability Institute. scopusflow and its
[R twin](https://pablobernabeu.github.io/scopusflow/) are part of that work,
keeping a search reproducible and its results legible across both languages.
His [ORCID record](https://orcid.org/0000-0003-1083-2460) lists his other work.

## Licence

scopusflow is released under the MIT licence, reproduced in full on the
[licence page](licence.md). Scopus is a trademark of Elsevier, and scopusflow
is an independent client that is not affiliated with or endorsed by Elsevier.

## Versioning and archival

Each release is tagged on GitHub and archived on Zenodo. The concept DOI,
[10.5281/zenodo.21252666](https://doi.org/10.5281/zenodo.21252666), always
resolves to the latest version, so a citation stays current without chasing
version numbers. The citation above names that version. The
[changelog](changelog.md) records what changed in each release, and lists the
changes not yet released under Unreleased. Pages built from a development version
say so in a banner at the top.

## Contributing and support

Bugs and feature requests are welcome on the
[GitHub issues page](https://github.com/pablobernabeu/scopusflow-py/issues),
and the
[contributing guide](https://github.com/pablobernabeu/scopusflow-py/blob/main/.github/CONTRIBUTING.md)
covers the development setup, the offline test suite and the release process.
When reporting a problem, never paste your Scopus API key or any other secret
into an issue. Replace it with a placeholder instead.
