"""French versions of reproduce_code's notes, for lang="fr".

Notes are written in English where they are made (builders, the probe,
the client); this table turns each one into French at the end. A pattern
holds the English note with its variable parts as named groups, so a note
that names a URL, a count or a column still translates. A note with no
entry here (the CFIA and PHAC page-specific notes) stays in English.
"""

from __future__ import annotations

import re

_NOTES: list[tuple[str, str]] = [
    (
        r"The full table is downloaded; filter it to the rows the tool returned\.",
        (
            "Le tableau complet est téléchargé ; filtrez-le pour garder les lignes que l'outil a "
            "renvoyées."
        ),
    ),
    (
        r"WDS returns one object per vector; values are under vectorDataPoint\.",
        "WDS renvoie un objet par vecteur ; les valeurs sont sous vectorDataPoint.",
    ),
    (
        r"Fetched through WDS, which serves the same vector as JSON\.",
        "Récupéré par WDS, qui sert le même vecteur en JSON.",
    ),
    (
        (
            r"StatCan's SDMX service answers in SDMX-ML \(XML\); the script makes one row per "
            r"observation, with the series key and attributes as columns\."
        ),
        (
            "Le service SDMX de StatCan répond en SDMX-ML (XML) ; le script fait une ligne par "
            "observation, avec la clé et les attributs de la série en colonnes."
        ),
    ),
    (
        (
            r"The tool keeps at most (?P<series>\d+) series and the newest (?P<rows>\d+) "
            r"observations per series; the script keeps every row StatCan returns\."
        ),
        (
            "L'outil garde au plus {series} séries et les {rows} observations les plus récentes "
            "par série ; le script garde toutes les lignes que StatCan renvoie."
        ),
    ),
    (
        (
            r"The URL's \$limit=(?P<limit>\S+) matches the tool; raise it \(SODA allows 50,000 per "
            r"request\) or page with \$offset for every row\."
        ),
        (
            "Le $limit={limit} de l'URL est celui de l'outil ; augmentez-le (SODA en permet 50 000 "
            "par requête) ou paginez avec $offset pour obtenir toutes les lignes."
        ),
    ),
    (
        r"Each observation holds one \{'v': value\} object per series, keyed by series name\.",
        "Chaque observation contient un objet {{'v': valeur}} par série, sous le nom de la série.",
    ),
    (
        (
            r"Use the survey's weight variable \(see statcan_pumf_get_codebook\); unweighted counts "
            r"describe the sample, not the population\."
        ),
        (
            "Utilisez la variable de pondération de l'enquête (voir statcan_pumf_get_codebook) ; "
            "les comptes non pondérés décrivent l'échantillon, pas la population."
        ),
    ),
    (
        (
            r"Where the ZIP has no CSV, read the fixed-width file with the Stata \.dct/\.do or "
            r"SPSS/SAS command files StatCan ships in the same ZIP\."
        ),
        (
            "Si le ZIP n'a pas de CSV, lisez le fichier à largeur fixe avec les fichiers de "
            "commandes Stata .dct/.do ou SPSS/SAS que StatCan fournit dans le même ZIP."
        ),
    ),
    (
        r"The R version reads the Beyond 20/20 file with canivt, which keeps dimension labels\.",
        (
            "La version R lit le fichier Beyond 20/20 avec canivt, qui garde les libellés des "
            "dimensions."
        ),
    ),
    (
        (
            r"(?P<release>\d{4}) tables have no full-table CSV; an SDMX ZIP is at (?P<url>\S+) for "
            r"non-R languages\."
        ),
        (
            "Les tableaux de {release} n'ont pas de CSV complet ; un ZIP SDMX est à {url} pour les "
            "langages autres que R."
        ),
    ),
    (
        r"Date bounds compare (?P<column>.+) as ISO text \(YYYY-MM-DD\)\.",
        "Les bornes de dates comparent {column} comme texte ISO (AAAA-MM-JJ).",
    ),
    (
        r"Each 'Table' sheet has a title row above its header, hence the skipped row\.",
        (
            "Chaque feuille « Table » a une ligne de titre au-dessus de l'en-tête, d'où la ligne "
            "sautée."
        ),
    ),
    (
        r"Counts are rounded to 5; '--' marks a suppressed count of 1 to 4\.",
        "Les comptes sont arrondis à 5 ; « -- » marque un compte supprimé de 1 à 4.",
    ),
    (
        (
            r"The tool then summed these rows to period=(?P<period>\S+) and "
            r"group_by=(?P<group>.+); the script returns the rows\."
        ),
        (
            "L'outil a ensuite additionné ces lignes avec period={period} et group_by={group} ; le "
            "script renvoie les lignes."
        ),
    ),
    (
        (
            r"This source answers only inside a browser session \(the request carries (?P<tokens>.+) "
            r"tokens from an earlier page\), so a script cannot replay it\. Cite the URL and "
            r"retrieval date, or keep the tool's output as the raw input\."
        ),
        (
            "Cette source ne répond que dans une session de navigateur (la requête porte des jetons "
            "{tokens} d'une page précédente) ; un script ne peut donc pas la rejouer. Citez l'URL "
            "et la date de récupération, ou gardez la sortie de l'outil comme donnée brute."
        ),
    ),
    (
        (
            r"The tool paged through (?P<pages>\d+) requests to this endpoint; the script fetches "
            r"the first page\. Raise its limit or add an offset loop for every row\."
        ),
        (
            "L'outil a parcouru {pages} pages de ce point d'accès ; le script récupère la première. "
            "Augmentez sa limite ou ajoutez une boucle sur offset pour toutes les lignes."
        ),
    ),
    (
        (
            r"Replaying the request failed: the source did not answer in time; call reproduce_code "
            r"again\."
        ),
        (
            "La requête n'a pas pu être rejouée : la source n'a pas répondu à temps ; rappelez "
            "reproduce_code."
        ),
    ),
    (
        (
            r"Replaying the request failed: the source refused it \((?P<error>.+)\); it may need a "
            r"browser session\."
        ),
        (
            "La requête n'a pas pu être rejouée : la source l'a refusée ({error}) ; elle exige "
            "peut-être une session de navigateur."
        ),
    ),
    (
        r"The source returns JSON encoded twice; decode the text once more\.",
        "La source renvoie du JSON encodé deux fois ; décodez le texte une fois de plus.",
    ),
    (
        r"The response is (?P<what>.+); read it by hand\.",
        "La réponse est {what} ; lisez-la à la main.",
    ),
    (
        (
            r"GTFS-Realtime protocol buffers: decode with gtfs-realtime-bindings \(Python\) or "
            r"RProtoBuf and the GTFS-RT \.proto \(R\)\."
        ),
        (
            "Tampons de protocole GTFS-Realtime : décodez-les avec gtfs-realtime-bindings (Python) "
            "ou RProtoBuf et le .proto GTFS-RT (R)."
        ),
    ),
    (
        r"XML \(such as SDMX-ML\): read it with xml2 in R or lxml in Python\.",
        "XML (comme SDMX-ML) : lisez-le avec xml2 en R ou lxml en Python.",
    ),
    (
        (
            r"The page has (?P<count>\d+) tables; the script reads the largest \(number "
            r"(?P<index>\d+)\)\. Change the index for another\."
        ),
        (
            "La page a {count} tableaux ; le script lit le plus grand (numéro {index}). Changez "
            "l'indice pour un autre."
        ),
    ),
    (
        (
            r"This is a web page the tool parses, not a data table, so a download does not "
            r"reproduce the result\. Cite the URL and retrieval date, or keep the tool's output as "
            r"the raw input\."
        ),
        (
            "C'est une page Web que l'outil analyse, pas un tableau de données ; un téléchargement "
            "ne reproduit donc pas le résultat. Citez l'URL et la date de récupération, ou gardez "
            "la sortie de l'outil comme donnée brute."
        ),
    ),
    (
        r"The file opens with (?P<count>\d+) title line\(s\) above its header; skipped\.",
        (
            "Le fichier commence par {count} ligne(s) de titre au-dessus de l'en-tête ; elles sont "
            "sautées."
        ),
    ),
    (
        r"The data ends at the first blank line; the notes below it are dropped\.",
        "Les données s'arrêtent à la première ligne vide ; les notes qui suivent sont écartées.",
    ),
    (
        r"Fixed-width or free text: read it with read_fwf \(R\) or by column positions\.",
        "Texte à largeur fixe ou libre : lisez-le avec read_fwf (R) ou par positions de colonnes.",
    ),
    (
        (
            r"This tool only lists download links \(it checks each file with HEAD\)\. Reproduce the "
            r"tool that reads the file you pick, or download its URL\."
        ),
        (
            "Cet outil ne fait que lister des liens de téléchargement (il vérifie chaque fichier "
            "avec HEAD). Reproduisez l'outil qui lit le fichier choisi, ou téléchargez son URL."
        ),
    ),
    (
        (
            r"This tool reads MapleStats' own registry or cache, not a source download, so there "
            r"is nothing to fetch\."
        ),
        (
            "Cet outil lit le registre ou le cache de MapleStats, pas un téléchargement de la "
            "source ; il n'y a donc rien à récupérer."
        ),
    ),
    (
        (
            r"The tool applied these arguments itself after downloading, so the script returns "
            r"the unfiltered response: (?P<arguments>.+)\."
        ),
        (
            "L'outil a appliqué lui-même ces arguments après le téléchargement ; le script renvoie "
            "donc la réponse non filtrée : {arguments}."
        ),
    ),
    (
        r"No (?P<languages>.+) script: Beyond 20/20 files are read only by canivt \(R\)\.",
        "Pas de script {languages} : seul canivt (R) lit les fichiers Beyond 20/20.",
    ),
    (
        r"No (?P<languages>.+) script: Julia has no maintained HTML table reader\.",
        "Pas de script {languages} : Julia n'a pas de lecteur de tableaux HTML maintenu.",
    ),
    (
        r"No (?P<languages>.+) script: Julia has no maintained RSS/Atom reader\.",
        "Pas de script {languages} : Julia n'a pas de lecteur RSS/Atom maintenu.",
    ),
    (
        (
            r"No (?P<languages>.+) script: Power Query cannot repeat this source's steps \(they run "
            r"in Python or R in the other scripts, or the download is not a table\)\."
        ),
        (
            "Pas de script {languages} : Power Query ne peut pas répéter les étapes de cette source "
            "(elles s'exécutent en Python ou en R dans les autres scripts, ou le téléchargement "
            "n'est pas un tableau)."
        ),
    ),
    (
        r"No (?P<languages>.+) script: this language cannot read the source\.",
        "Pas de script {languages} : ce langage ne peut pas lire la source.",
    ),
    (
        r"The script unzips the archive; pick the data file inside it\.",
        "Le script décompresse l'archive ; choisissez-y le fichier de données.",
    ),
]

_COMPILED = [(re.compile(pattern), template) for pattern, template in _NOTES]


def note(text: str, lang: str) -> str:
    """The note in French when lang is "fr" and a translation exists."""
    if lang != "fr":
        return text
    for pattern, template in _COMPILED:
        match = pattern.fullmatch(text)
        if match:
            return template.format(**match.groupdict())
    return text
