# ChatGPT app directory package

What OpenAI's plugin portal (platform.openai.com/plugins, "With MCP") takes to
list MapleStats in the ChatGPT app directory. Requirements were read from
OpenAI's [submission](https://developers.openai.com/plugins/deploy/submission),
[review](https://developers.openai.com/plugins/deploy/app-review) and
[packaging](https://developers.openai.com/plugins/build/plugins) pages on
2026-11-07.

| File | What it is |
|---|---|
| `plugin.json` | Listing (`extensions.com.openai.interface`) and review test cases (`extensions.com.openai.review`). No `version` and an empty `demo_recording_url`: the build fills both. |
| `mcp.json` | The hosted server, `streamable-http`, auth `none`. |
| `build_zip.py` | Writes `build/chatgpt/maplestats-chatgpt-<version>.zip`: the two JSON files at the root and `site/assets/icon-512.png` as `assets/logo.png`. |
| `check_test_cases.py` | Runs each test case's tool calls against the live server and fails on any case that would not pass. |
| `DEMO_VIDEO_SCRIPT.md` | Shot list and narration for the review video. |

`tests/test_chatgpt_plugin.py` checks the field limits, the 5 + 3 test cases
and the ZIP layout without the network.

## Steps

1. `uv run python distribution/chatgpt/check_test_cases.py` (all eight PASS).
2. Record the video from `DEMO_VIDEO_SCRIPT.md`; host it unlisted.
3. `uv run python distribution/chatgpt/build_zip.py --demo-url <video URL>`.
4. In the portal: verify the organization's identity (individual) first, then
   upload the ZIP, add the server, and copy the domain-verification token.
5. Set the token as `MAPLE_OPENAI_APPS_CHALLENGE` on the Azure app; check
   `https://mcp.maplestats.danielstats.io/.well-known/openai-apps-challenge`
   returns exactly the token, then finish the challenge in the portal.
6. Scan tools, review the form (the category must be one of the dashboard's;
   `Research` is a guess) and submit.

## Review risks

- The guidelines ask that each model-callable operation be its own tool and
  disallow generic executors. MapleStats exposes `search_tools`, `call_tool`
  and `plan_query`, and `call_tool` runs any of several hundred data tools by
  name. A reviewer may read `call_tool` as a generic executor; be ready to
  explain the design, or to list the data tools directly for this client.
- `openWorldHint` is `false` on `search_tools` and `plan_query` (they read the
  server's own catalogue) and `true` on `call_tool` (public data from outside
  publishers); the submission form asks for a justification of each.
