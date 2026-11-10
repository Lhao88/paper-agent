import re


def rebuild_abstract(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    tokens: dict[int, str] = {}
    for word, positions in index.items():
        for position in positions:
            if position < 0 or (position in tokens and tokens[position] != word):
                raise ValueError("conflicting or invalid abstract position")
            tokens[position] = word
    return " ".join(tokens[position] for position in sorted(tokens)) or None


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().casefold()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        normalized = normalized.removeprefix(prefix)
    return normalized if re.fullmatch(r"10\.\d{4,9}/\S+", normalized) else None
