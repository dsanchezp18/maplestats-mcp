"""reproduce_code: turn a tool call into an R, Python, Stata, Julia or SAS script."""

MODULE_NAME = "reproduce"
MODULE_DESCRIPTION = (
    "Reproduction code: for a tool call, returns an R, Python, Stata, Julia or SAS snippet "
    "or an Excel Power Query that fetches the same data straight from the source, using "
    "cansim, polars, TidierFiles, Stata's import commands or PROC HTTP, so analysis scripts "
    "stay reproducible; reproduce_workbook returns the rows as a formatted Excel workbook."
)
MODULE_DESCRIPTION_FR = (
    "Code de reproduction : pour un appel d'outil, fournit un extrait R, Python, Stata, "
    "Julia ou SAS, ou une requête Power Query pour Excel, qui récupère les mêmes données "
    "directement à la source (cansim, polars, TidierFiles, commandes "
    "d'importation Stata ou PROC HTTP); reproduce_workbook fournit les lignes dans un classeur Excel "
    "mis en forme."
)
