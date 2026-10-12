"""Turn free text into an FTS5 query. Agents handle meaning; this just matches words."""

import re

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def fts_query(text: str, mode: str = "AND") -> str | None:
    words = list(dict.fromkeys(w.lower() for w in _WORD.findall(text or "")))[:20]
    if not words:
        return None
    # Quote each word so FTS operators in user text are treated literally; * allows prefixes.
    return f" {mode} ".join(f'"{w}"*' for w in words)
