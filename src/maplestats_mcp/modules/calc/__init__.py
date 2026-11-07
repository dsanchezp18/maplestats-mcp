"""calc_: arithmetic across official series, computed by MapleStats with the formula shown.

Not a data source: every input is read through the StatCan WDS and Bank of
Canada Valet clients (their caches, rate limits and typed errors), and the
period arithmetic is shared/transform.py's. The tools exist because a
ratio of two series, a ranking across places, a compound growth rate and a
count of changes are where assistants slip when they do the arithmetic
themselves: misaligned periods, a forgotten scale factor (thousands), a
monthly series divided by an annual one, a growth rate taken over the wrong
number of years.
"""

MODULE_NAME = "calc"
MODULE_DESCRIPTION = (
    "Calculations across series: the ratio of two StatCan or Bank of Canada series aligned "
    "on period, a ranking of places for one period, compound annual growth between two "
    "periods, and the count of changes over a window (rate moves), each with the formula, "
    "the unit and every input's citation; mismatched frequencies or units are refused."
)
MODULE_DESCRIPTION_FR = (
    "Calculs entre séries : rapport de deux séries de Statistique Canada ou de la Banque du "
    "Canada alignées par période, classement de lieux pour une période, taux de croissance "
    "annuel composé entre deux périodes et nombre de variations sur une fenêtre (décisions "
    "de taux), chacun avec la formule, l'unité et la citation de chaque série ; les "
    "fréquences ou unités incompatibles sont refusées."
)
