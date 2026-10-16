"""Private payroll identifier comparisons; no source identifier is returned by checks."""

import unicodedata


def normalized_identifier(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()
