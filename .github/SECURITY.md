# Security policy

## Reporting a vulnerability

If you find a security problem in scopusflow, please report it privately by
email to pcbernabeu@gmail.com rather than opening a public issue. A short
description of the problem and, where possible, a way to reproduce it is enough
to get started. You can expect an acknowledgement within a few days, and we will
keep you informed as the issue is investigated and resolved.

## A note on API keys

scopusflow never stores your Scopus API key. Retrieval runs through
pybliometrics, which reads the key from its own configuration file
(`~/.config/pybliometrics.cfg`). Keep the key there rather than in scripts or
notebooks, and never paste it into an issue, a pull request or a discussion.
