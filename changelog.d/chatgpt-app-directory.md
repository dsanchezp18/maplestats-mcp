### Added

- `GET /.well-known/openai-apps-challenge` on the HTTP server answers with the
  token in `MAPLE_OPENAI_APPS_CHALLENGE` as plain text, without a bearer
  token, for OpenAI's plugin domain verification; unset, it answers 404.
- A terms of service page on the website (`terms.html`, English and French),
  linked from the footer.
- `distribution/chatgpt/`: the ChatGPT app directory package (`plugin.json`
  with five positive and three negative review test cases, `mcp.json`), a ZIP
  builder, a live checker for the test cases and the demo video script.
