"""French versions of reproduce_code's notes, for lang="fr".

Notes are written in English where they are made (builders, the probe,
the client, the CFIA, PHAC and IP Horizons builders); this table turns
each one into French at the end. A pattern holds the English note with its
variable parts as named groups, so a note that names a URL, a count or a
column still translates. A template is a format string, or a function of
the groups when part of the note is optional. tests/test_reproduce_counts.py
checks that every note the builders write has an entry here.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from maplestats_mcp.shared.i18n import french_text, normalize_lang

Template = str | Callable[[dict[str, str]], str]


def _counts_by(prefix: str, groups: dict[str, str], key: str, word: str) -> str:
    tail = f" et ses {word} par {groups[key]}" if groups.get(key) else ""
    return f"{prefix}{tail}."


_NOTES: list[tuple[str, Template]] = [
    (
        r"The full table is downloaded; filter it to the rows the tool returned\.",
        (
            "Le tableau complet est téléchargé ; filtrez-le pour ne garder que les lignes "
            "renvoyées par l'outil."
        ),
    ),
    (
        r"WDS returns one object per vector; values are under vectorDataPoint\.",
        "WDS renvoie un objet par vecteur ; les valeurs se trouvent sous vectorDataPoint.",
    ),
    (
        r"Fetched through WDS, which serves the same vector as JSON\.",
        "Récupéré par WDS, qui fournit le même vecteur en JSON.",
    ),
    (
        (
            r"StatCan's SDMX service answers in SDMX-ML \(XML\); the script makes one row per "
            r"observation, with the series key and attributes as columns\."
        ),
        (
            "Le service SDMX de Statistique Canada répond en SDMX-ML (XML) ; le script produit "
            "une ligne par observation, avec la clé et les attributs de la série en colonnes."
        ),
    ),
    (
        (
            r"The tool keeps at most (?P<series>\d+) series and the newest (?P<rows>\d+) "
            r"observations per series; the script keeps every row StatCan returns\."
        ),
        (
            "L'outil garde au plus {series} séries et les {rows} observations les plus récentes "
            "de chaque série ; le script garde toutes les lignes renvoyées par Statistique "
            "Canada."
        ),
    ),
    (
        (
            r"The URL's \$limit=(?P<limit>\S+) matches the tool; raise it \(SODA allows 50,000 per "
            r"request\) or page with \$offset for every row\."
        ),
        (
            "Le $limit={limit} de l'URL est celui de l'outil ; augmentez-le (SODA en permet "
            "50 000 par requête) ou paginez avec $offset pour obtenir toutes les lignes."
        ),
    ),
    (
        r"Each observation holds one \{'v': value\} object per series, keyed by series name\.",
        (
            "Chaque observation contient un objet {{'v': valeur}} par série, indexé par le nom "
            "de la série."
        ),
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
            "Si le ZIP ne contient pas de CSV, lisez le fichier à largeur fixe avec les fichiers "
            "de commandes Stata .dct/.do ou SPSS/SAS que Statistique Canada fournit dans le même "
            "ZIP."
        ),
    ),
    (
        r"The R version reads the Beyond 20/20 file with canivt, which keeps dimension labels\.",
        (
            "La version R lit le fichier Beyond 20/20 avec canivt, qui conserve les libellés "
            "des dimensions."
        ),
    ),
    (
        (
            r"(?P<release>\d{4}) tables have no full-table CSV; an SDMX ZIP is at (?P<url>\S+) for "
            r"non-R languages\."
        ),
        (
            "Les tableaux de {release} n'ont pas de CSV complet ; un ZIP SDMX se trouve à {url} "
            "pour les langages autres que R."
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
            "ignorée."
        ),
    ),
    (
        r"Counts are rounded to 5; '--' marks a suppressed count of 1 to 4\.",
        "Les comptes sont arrondis à 5 près ; « -- » indique un compte supprimé de 1 à 4.",
    ),
    (
        (
            r"The tool then summed these rows to period=(?P<period>\S+) and "
            r"group_by=(?P<group>.+); the script returns the rows\."
        ),
        (
            "L'outil a ensuite additionné ces lignes selon period={period} et group_by={group} ; "
            "le script renvoie les lignes."
        ),
    ),
    (
        (
            r"This source answers only inside a browser session \(the request carries (?P<tokens>.+) "
            r"tokens from an earlier page\), so a script cannot replay it\. Cite the URL and "
            r"retrieval date, or keep the tool's output as the raw input\."
        ),
        (
            "Cette source ne répond que dans une session de navigateur (la requête transmet les "
            "jetons {tokens} obtenus d'une page précédente) ; un script ne peut donc pas la "
            "rejouer. Citez l'URL et la date de consultation, ou conservez la sortie de l'outil "
            "comme donnée brute."
        ),
    ),
    (
        (
            r"The tool paged through (?P<pages>\d+) requests to this endpoint; the script fetches "
            r"the first page\. Raise its limit or add an offset loop for every row\."
        ),
        (
            "L'outil a parcouru {pages} pages de ce point d'accès ; le script récupère la "
            "première. Augmentez sa limite ou ajoutez une boucle sur offset pour obtenir toutes "
            "les lignes."
        ),
    ),
    (
        (
            r"Replaying the request failed: the source did not answer in time; call reproduce_code "
            r"again\."
        ),
        (
            "La requête n'a pas pu être rejouée : la source n'a pas répondu à temps ; appelez "
            "reproduce_code de nouveau."
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
        "La source renvoie du JSON encodé deux fois ; décodez le texte une seconde fois.",
    ),
    (
        r"The response is (?P<what>.+); read it by hand\.",
        "La réponse est {what} ; lisez-la manuellement.",
    ),
    (
        (
            r"GTFS-Realtime protocol buffers: decode with gtfs-realtime-bindings \(Python\) or "
            r"RProtoBuf and the GTFS-RT \.proto \(R\)\."
        ),
        (
            "Données GTFS-Realtime en Protocol Buffers : décodez-les avec gtfs-realtime-bindings "
            "(Python) ou avec RProtoBuf et le fichier .proto de GTFS-RT (R)."
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
            "La page contient {count} tableaux ; le script lit le plus grand (no {index}). "
            "Changez l'indice pour en lire un autre."
        ),
    ),
    (
        (
            r"This is a web page the tool parses, not a data table, so a download does not "
            r"reproduce the result\. Cite the URL and retrieval date, or keep the tool's output as "
            r"the raw input\."
        ),
        (
            "Il s'agit d'une page Web que l'outil analyse, pas d'un tableau de données ; un "
            "téléchargement ne reproduit donc pas le résultat. Citez l'URL et la date de "
            "consultation, ou conservez la sortie de l'outil comme donnée brute."
        ),
    ),
    (
        r"The file opens with (?P<count>\d+) title line\(s\) above its header; skipped\.",
        (
            "Le fichier commence par {count} ligne(s) de titre au-dessus de l'en-tête ; elles "
            "sont ignorées."
        ),
    ),
    (
        r"The data ends at the first blank line; the notes below it are dropped\.",
        "Les données s'arrêtent à la première ligne vide ; les notes qui suivent sont écartées.",
    ),
    (
        r"Fixed-width or free text: read it with read_fwf \(R\) or by column positions\.",
        (
            "Texte à largeur fixe ou libre : lisez-le avec read_fwf (R) ou selon la position "
            "des colonnes."
        ),
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
            "L'outil a appliqué lui-même ces arguments après le téléchargement ; le script "
            "renvoie donc la réponse non filtrée : {arguments}."
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
            "Pas de script {languages} : Power Query ne peut pas répéter les étapes de cette "
            "source (elles s'exécutent en Python ou en R dans les autres scripts, ou le "
            "téléchargement n'est pas un tableau)."
        ),
    ),
    (
        r"No (?P<languages>.+) script: this language cannot read the source\.",
        "Pas de script {languages} : ce langage ne peut pas lire la source.",
    ),
    (
        r"The script unzips the archive; pick the data file inside it\.",
        "Le script décompresse l'archive ; choisissez le fichier de données qu'elle contient.",
    ),
    # CFIA (cfia.py)
    (
        (
            r"The tool returned (?P<rows>\d+) rows \((?P<span>[^)]*)\); the scripts parse all year "
            r"tables on the page and repeat its year range, disease match \(folded for case, "
            r"accents and apostrophes, with the abbreviations and other names in "
            r"constants\.DISEASES\), order(?: and totals by (?P<totals>.+))?\."
        ),
        lambda g: _counts_by(
            f"L'outil a renvoyé {g['rows']} lignes ({g['span']}) ; les scripts analysent tous "
            "les tableaux annuels de la page et répètent sa plage d'années, sa correspondance "
            "des maladies (sans égard à la casse, aux accents ni aux apostrophes, avec les "
            "abréviations et autres noms de constants.DISEASES), son ordre",
            g,
            "totals",
            "totaux",
        ),
    ),
    (
        (
            r"Canada\.ca terms allow non-commercial reproduction that credits the title, the "
            r"author \(Canadian Food Inspection Agency\) and the source URL; each script's header "
            r"and output name them\."
        ),
        (
            "Les conditions d'utilisation de Canada.ca permettent la reproduction non "
            "commerciale qui mentionne le titre, l'auteur (Agence canadienne d'inspection des "
            "aliments) et l'URL de la source ; l'en-tête et la sortie de chaque script les "
            "indiquent."
        ),
    ),
    (
        (
            r"The tool returned (?P<rows>\d+) detections \((?P<herds>\d+) herds\) from "
            r"(?P<pages>\d+) disease page\(s\); the scripts parse the same pages as the tool does "
            r"\(herd counts such as 'Elk \(3 herds\)', day and month read with the row's year, "
            r"provinces named in the location, BSE's age\) and repeat its filters, order"
            r"(?: and counts by (?P<counts>.+))?\."
        ),
        lambda g: _counts_by(
            f"L'outil a renvoyé {g['rows']} détections ({g['herds']} troupeaux) tirées de "
            f"{g['pages']} page(s) de maladie ; les scripts analysent les mêmes pages que "
            "l'outil (nombre de troupeaux comme 'Elk (3 herds)', jour et mois lus avec l'année "
            "de la ligne, provinces nommées dans le lieu, âge pour l'ESB) et répètent ses "
            "filtres, son ordre",
            g,
            "counts",
            "comptes",
        ),
    ),
    (
        r"Province codes are one text column, comma-separated \('AB,SK'\), in every language\.",
        (
            "Les codes de province forment une seule colonne de texte, séparés par des virgules "
            "('AB,SK'), dans tous les langages."
        ),
    ),
    (
        (
            r"Dates, years, herds and provinces come from the English pages and labels from the "
            r"French pages, as the tool does, because the French pages hold data errors\."
        ),
        (
            "Les dates, les années, les troupeaux et les provinces viennent des pages anglaises, "
            "et les libellés, des pages françaises, comme dans l'outil, parce que les pages "
            "françaises contiennent des erreurs de données."
        ),
    ),
    (
        (
            r"The tool matched (?P<matched>\d+) premises and returned (?P<returned>\d+); the "
            r"scripts parse the investigations-and-orders table as the tool does \(hidden padding "
            r"digits, quarantine and released markers, premises type, WOAH class, control zone and "
            r"order\) and repeat its filters, newest-first order, counts by (?P<counts>\S+) and "
            r"limit of (?P<limit>\d+), and read the status-by-province table\."
        ),
        (
            "L'outil a trouvé {matched} lieux et en a renvoyé {returned} ; les scripts analysent "
            "le tableau des enquêtes et des ordonnances comme l'outil (chiffres de remplissage "
            "masqués, marqueurs de quarantaine et de levée, type de lieu, catégorie de l'OMSA, "
            "zone de contrôle et ordonnance), répètent ses filtres, son tri du plus récent au "
            "plus ancien, ses comptes par {counts} et sa limite de {limit}, et lisent le tableau "
            "de la situation par province."
        ),
    ),
    (
        (
            r"Dates and statuses come from the English page and labels from the French page, "
            r"joined by premises id, as the tool does, because the French page gives six premises "
            r"another detection date\."
        ),
        (
            "Les dates et les statuts viennent de la page anglaise, et les libellés, de la page "
            "française, joints par identifiant de lieu, comme dans l'outil, parce que la page "
            "française donne une autre date de détection pour six lieux."
        ),
    ),
    # PHAC Health Infobase (phac_infobase.py)
    (
        (
            r"The tool returned (?P<returned>\d+) of (?P<matching>\d+) matching rows "
            r"\((?P<total>\d+) in the file\); the scripts repeat its filters, province match, date "
            r"bounds, ordering and limit, so they keep the same rows\."
        ),
        (
            "L'outil a renvoyé {returned} des {matching} lignes correspondantes ({total} dans le "
            "fichier) ; les scripts répètent ses filtres, sa correspondance des provinces, ses "
            "bornes de dates, son tri et sa limite, et gardent donc les mêmes lignes."
        ),
    ),
    (
        (
            r"The scripts read the whole file as the tool does and print its summary \(rows, date "
            r"coverage, places\)\."
        ),
        (
            "Les scripts lisent le fichier entier comme l'outil et en affichent le résumé "
            "(lignes, période couverte, lieux)."
        ),
    ),
    (
        (
            r"Cells are read as text, as the tool reads them, and compared ignoring case, accents "
            r"and apostrophe style; Python repeats the tool's rules exactly, R \(stringi\) and "
            r"Julia \(Unicode\.normalize\) fold accents the same way for Latin text\."
        ),
        (
            "Les cellules sont lues comme du texte, comme dans l'outil, et comparées sans égard "
            "à la casse, aux accents ni au style d'apostrophe ; Python reproduit exactement les "
            "règles de l'outil, et R (stringi) et Julia (Unicode.normalize) retirent les accents "
            "de la même façon pour l'alphabet latin."
        ),
    ),
    (
        (
            r"Suppression markers stay as published; the scripts list PHAC's markers and their "
            r"meaning\. Numbers become numeric only after the tool's steps, in columns with no "
            r"marker\."
        ),
        (
            "Les marqueurs de suppression restent tels que publiés ; les scripts listent les "
            "marqueurs de l'ASPC et leur sens. Les nombres ne deviennent numériques qu'après les "
            "étapes de l'outil, dans les colonnes sans marqueur."
        ),
    ),
    (
        (
            r"R takes the ZIP's only CSV when there is one, since the French member name is stored "
            r"in code page 437 without the UTF-8 flag; Python and Julia decode the names as the "
            r"tool does and match the member name\."
        ),
        (
            "R prend le CSV du ZIP quand il est seul, car le nom français du fichier est stocké "
            "dans la page de codes 437 sans l'indicateur UTF-8 ; Python et Julia décodent les "
            "noms comme l'outil et retrouvent le fichier par son nom."
        ),
    ),
    (
        (
            r"phac_infobase_list_datasets reads MapleStats' curated catalogue of Health Infobase "
            r"files, not a source download, so there is nothing to fetch\. Reproduce "
            r"phac_infobase_query or phac_infobase_describe_dataset with one of these dataset ids "
            r"for a script that downloads and reads its file\."
        ),
        (
            "phac_infobase_list_datasets lit le catalogue des fichiers de l'Infobase de la santé "
            "établi par MapleStats, pas un téléchargement de la source ; il n'y a donc rien à "
            "récupérer. Reproduisez phac_infobase_query ou phac_infobase_describe_dataset avec "
            "l'un de ces identifiants de jeu de données pour obtenir un script qui télécharge et "
            "lit son fichier."
        ),
    ),
    (
        r"Files listed \((?P<count>\d+)\): (?P<files>.*)\.",
        lambda g: (
            f"Fichiers listés ({g['count']}) : {'aucun' if g['files'] == 'none' else g['files']}."
        ),
    ),
    # IP Horizons (ip_horizons.py)
    (
        (
            r"`data` holds the patent; `parties` its owners, inventors, applicants and agents"
            r"(?P<classes>; `classes` its IPC classes)?\."
        ),
        lambda g: (
            "`data` contient le brevet ; `parties`, ses titulaires, inventeurs, demandeurs et "
            "agents" + (" ; `classes`, ses classes CIB." if g.get("classes") else ".")
        ),
    ),
    (
        r"Name and title filters are case-insensitive substrings, as in the tool\.",
        (
            "Les filtres sur le nom et le titre cherchent des sous-chaînes sans égard à la "
            "casse, comme dans l'outil."
        ),
    ),
    (
        r"The party and IPC tables are large \(up to 2\.6 GB unzipped\); expect minutes\.",
        (
            "Les tableaux des parties et des classes CIB sont volumineux (jusqu'à 2,6 Go "
            "décompressés) ; comptez quelques minutes."
        ),
    ),
    (
        (
            r"opic-cipo\.ca omits its intermediate certificate\. Windows fetches it automatically; "
            r"on Linux or macOS, R, Stata and Julia need RapidSSL TLS RSA CA G1 "
            r"\((?P<url>\S+)\) in the system trust store\."
        ),
        (
            "opic-cipo.ca omet son certificat intermédiaire. Windows le récupère "
            "automatiquement ; sous Linux ou macOS, R, Stata et Julia ont besoin du certificat "
            "RapidSSL TLS RSA CA G1 ({url}) dans le magasin de certificats du système."
        ),
    ),
]

_COMPILED = [(re.compile(pattern), template) for pattern, template in _NOTES]


def translate(text: str) -> str | None:
    """The French for an English note, or None when no pattern matches."""
    for pattern, template in _COMPILED:
        match = pattern.fullmatch(text)
        if match:
            groups = {k: v or "" for k, v in match.groupdict().items()}
            return template.format(**groups) if isinstance(template, str) else template(groups)
    return None


def note(text: str, lang: str) -> str:
    """The note in French when lang is "fr" and a translation exists."""
    if normalize_lang(lang) != "fr":
        return text
    french = translate(text)
    # The templates are typed with ordinary spaces; French spacing is added here.
    return text if french is None else french_text(french)
