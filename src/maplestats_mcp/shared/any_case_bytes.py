"""A bytes pattern that finds a search text in any case, accented letters included.

Two sources are searched as raw UTF-8 bytes before any line is decoded (the NHP
licence name index, the Canada Vigilance reactions file), because decoding 37 MB or
more to find a few lines costs more than the scan.
"""

from __future__ import annotations

import re


def any_case_pattern(text: str) -> re.Pattern[bytes]:
    """`text` as UTF-8 bytes, matching any case of every letter.

    re.IGNORECASE on a bytes pattern folds ASCII letters only: "é" and "É" are
    two bytes each, and the second byte differs, so "éruption" never matched
    "Éruption" and "échinacée" never matched "Échinacée". The line was dropped before
    the exact test, which does ignore case (casefold). Each non-ASCII letter is
    spelled out as its lower, upper, title and folded forms, which covers the
    accented letters of English and French terms (é, ç, œ); ASCII keeps
    IGNORECASE. A search written with ASCII letters that casefold makes from one
    letter (ss for ß) is not found by this test. The whole text still narrows the
    scan to its few candidate lines.
    """
    parts: list[bytes] = []
    for char in text:
        if char.isascii():
            parts.append(re.escape(char.encode("utf-8")))
            continue
        forms = {char, char.lower(), char.upper(), char.title(), char.casefold()}
        spelled = sorted(form.encode("utf-8") for form in forms)
        parts.append(b"(?:" + b"|".join(re.escape(one) for one in spelled) + b")")
    return re.compile(b"".join(parts), re.IGNORECASE)
