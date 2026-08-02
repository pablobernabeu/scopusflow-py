# About

## Citing scopusflow

If scopusflow contributes to published work, please cite it.

````python exec="1"
# The version used to be written out by hand in three places on this page, and
# one of them had already fallen a whole minor version behind before anyone
# noticed. All three now come from the installed package, so they cannot drift
# apart from each other or from the release. Two further copies are beyond the
# reach of this block, because neither file can run code, and both still have to
# be bumped by hand when a release is cut: the extra.version chip in mkdocs.yml
# and the version field in CITATION.cff.
import urllib.parse

from scopusflow import __version__ as version

bibtex = (
    "@Manual{scopusflow-py,\n"
    "  title  = {scopusflow: A reproducible workflow layer over pybliometrics for {Scopus} searches},\n"
    "  author = {Pablo Bernabeu},\n"
    "  year   = {2026},\n"
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
    "> Bernabeu, P. (2026). scopusflow: A reproducible workflow layer over\n"
    "> pybliometrics for Scopus searches. Python package version "
    f"{version}.\n"
    "> https://doi.org/10.5281/zenodo.21252666\n"
)

# The entry is printed as a real fenced block rather than as ready-made HTML, so
# that Material still gives it BibTeX highlighting and a copy button. Printing a
# fence from inside a fence is why the enclosing one takes four backticks.
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
version numbers. The [changelog](changelog.md) records what changed in each
release.

## Contributing and support

Bugs and feature requests are welcome on the
[GitHub issues page](https://github.com/pablobernabeu/scopusflow-py/issues),
and the
[contributing guide](https://github.com/pablobernabeu/scopusflow-py/blob/main/.github/CONTRIBUTING.md)
covers the development setup, the offline test suite and the release process.
When reporting a problem, never paste your Scopus API key or any other secret
into an issue. Replace it with a placeholder instead.
