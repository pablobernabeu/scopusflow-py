# Security policy

## Reporting a vulnerability

If you find a security problem in scopusflow, please report it privately by
email to pcbernabeu@gmail.com, in preference to opening a public issue. A short
description of the problem and, where possible, a way to reproduce it is enough
to get started. You can expect an acknowledgement within a few days, and we will
keep you informed as the issue is investigated and resolved.

## A note on API keys

scopusflow itself never stores your Scopus API key. Retrieval runs through
pybliometrics, and where the key lives depends on how you use the package.

In a script or notebook, `pybliometrics.init()` reads the key from
pybliometrics' configuration file (`~/.config/pybliometrics.cfg`). On first use
it creates that file and asks for the key, which it then keeps there in plain
text. Keep the key in that file, well away from your scripts and notebooks.

In the app, a key pasted into the key field is held in memory and handed to
pybliometrics for the running process only. It is never written to disk. When
you have no pybliometrics configuration, the app gives pybliometrics a key-less
one in a temporary folder, which it removes when it stops.

Never paste the key into an issue, a pull request or a discussion.
