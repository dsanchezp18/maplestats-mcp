"""check_answer: re-read the figures an answer cites and report what is wrong."""

MODULE_NAME = "answer_check"
MODULE_DESCRIPTION = (
    "Answer check: before replying, the assistant passes the question and the figures it "
    "will cite (StatCan vector or table and coordinate, or a Bank of Canada series); the "
    "server re-reads them and returns only the problems found: wrong value or scale, a "
    "newer period, another geography, unadjusted or flagged data, units, and figures not "
    "published, with the route to get them."
)
MODULE_DESCRIPTION_FR = (
    "Vérification de réponse : avant de répondre, l'assistant transmet la question et les "
    "chiffres qu'il citera (vecteur ou tableau et coordonnée de StatCan, ou série de la "
    "Banque du Canada) ; le serveur les relit et ne renvoie que les problèmes trouvés : "
    "valeur ou échelle erronée, période plus récente, autre géographie, données non "
    "désaisonnalisées ou signalées, unités, et chiffres non publiés, avec la façon de les "
    "obtenir."
)
