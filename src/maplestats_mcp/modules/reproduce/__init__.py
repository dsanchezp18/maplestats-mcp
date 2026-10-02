"""reproduce_code: turn a tool call into an R, Python, Stata or Julia script."""

MODULE_NAME = "reproduce"
MODULE_DESCRIPTION = (
    "Reproduction code: for a tool call, returns an R, Python, Stata or Julia snippet "
    "or an Excel Power Query that fetches the same data straight from the source, using "
    "cansim, canivt, polars, TidierFiles or Stata's import commands, so analysis scripts "
    "stay reproducible; reproduce_workbook returns the rows as a formatted Excel workbook."
)
MODULE_DESCRIPTION_FR = (
    "Code de reproduction : pour un appel d'outil, fournit un extrait R, Python, Stata "
    "ou Julia, ou une requête Power Query pour Excel, qui récupère les mêmes données "
    "directement à la source (cansim, canivt, polars, TidierFiles ou commandes "
    "d'importation Stata); reproduce_workbook fournit les lignes dans un classeur Excel "
    "mis en forme."
)
