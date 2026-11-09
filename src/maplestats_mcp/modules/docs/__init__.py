"""docs_: read this server's own docs:// resources through call_tool.

Not a data source. Tool descriptions send the model to docs:// pages
(docs://cmhc/gotchas, docs://catalogue, ...), but many hosted clients show a
model only search_tools, call_tool and plan_query and never offer MCP
resources, so the model could not open the pages it was told to read. These
two tools list and return the same text the resources serve.
"""

MODULE_NAME = "docs"
MODULE_DESCRIPTION = (
    "Server documentation: list this server's docs:// pages (per-source gotchas, "
    "well-known series and categories, survey methodology, the module catalogue) and "
    "read any of them as text through call_tool, for clients that do not offer MCP "
    "resources."
)
MODULE_DESCRIPTION_FR = (
    "Documentation du serveur : liste des pages docs:// (pièges propres à chaque source, "
    "séries et catégories courantes, méthodologie d'enquête, catalogue des modules) et "
    "lecture de chacune en texte par call_tool, pour les clients qui n'offrent pas les "
    "ressources MCP."
)
