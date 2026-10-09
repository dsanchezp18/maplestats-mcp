# Security policy

## Reporting a vulnerability

Please report a vulnerability privately, not in a public issue.

Use GitHub's private vulnerability reporting:
[report a vulnerability](https://github.com/dsanchezp18/maplestats-mcp/security/advisories/new)
(the repository's Security tab, then "Report a vulnerability"). The report
reaches the maintainer only, and a fix can be prepared before the details
are public.

Please include:

- what you found and which part is affected (the server, a tool, the
  hosted endpoint, or the website);
- the steps or the exact tool call that shows it;
- the version (`maplestats-mcp --version`, or the version on the website's
  footer) and whether you ran it locally or used the hosted server.

You can expect an acknowledgement within a few days. This is a one-person
open source project, so there is no formal response-time guarantee, but a
confirmed vulnerability is fixed ahead of other work and credited in the
[changelog](CHANGELOG.md) unless you prefer otherwise.

## Scope

In scope: the code in this repository, the hosted server at
`maplestats-mcp.onrender.com`, and the website.

Out of scope: the publishers' own sites and APIs (Statistics Canada, the
Bank of Canada and the others). A problem in one of those belongs with its
publisher. A wrong or stale number returned by a tool is a bug, not a
vulnerability: use the
[bug report form](https://github.com/dsanchezp18/maplestats-mcp/issues/new/choose).

## Supported versions

Only the latest release receives fixes.

## What the server does with your requests

The hosted server receives your agent's tool calls. See the
[FAQ](https://maplestats.danielstats.io/faq.html#queries) for what
is and is not kept. For full privacy, run the server locally.
