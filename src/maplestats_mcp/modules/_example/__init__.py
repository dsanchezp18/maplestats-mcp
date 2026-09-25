"""Template module — the pattern every new source copies.

Underscore-prefixed on purpose: server.py explicitly skips any
modules/* directory starting with "_" when adding FileSystemProvider
instances, so this demo module never registers a live tool.

A new source module should have this file layout:

    modules/<source>/
      __init__.py      # MODULE_NAME + MODULE_DESCRIPTION (+ _FR)
      constants.py     # BASE_URL, rate limit, cache TTLs
      schemas.py       # typed Pydantic response models
      client.py        # async functions -> typed model (or raise)
      tools.py          # @tool functions, one per client function
      resources.py       # (optional) zero-parameter docs:// resources
      prompts.py          # (optional) guided-workflow prompts
      __tests__/

A source with multiple distinct sub-APIs (see modules/statcan/) splits
into subfolders instead, each with its own constants/schemas/client/
tools — the top-level __init__.py, resources.py, and prompts.py stay
shared across the sub-APIs.
"""

MODULE_NAME = "example"
MODULE_DESCRIPTION = "Template module demonstrating the source module pattern. Not registered live."
MODULE_DESCRIPTION_FR = (
    "Module modèle illustrant le patron des modules source. Non enregistré en direct."
)
