"""Shared plain-text normalizer for free-text write boundaries (PHASE-14B, #762).

Every free-text write normalizes its value before it reaches a facade: Unicode
NFKC normalization, control-character removal, whitespace collapse, and a
maximum length. The helper is pure, small, and reusable by later write
tickets.

This is deliberately NOT an HTML sanitizer. The platform has no HTML parser and
no blanket sanitizer; React's default escaping remains the display rule. See
``docs/design/plain-text-normalization-and-html-sinks.md`` for the no-new-HTML-
sink rule and the one static chart exception.
"""

from __future__ import annotations

import unicodedata

# The default free-text write cap, part of the request contract like the
# explicit ``max_length`` on the request fields themselves. A boundary may pass
# its own tighter cap (the practice name is 120, the pick source is 80).
DEFAULT_MAX_LENGTH = 500

# Control characters that carry word separation are treated as whitespace so
# the collapse below does not glue two words together ("a\\nb" -> "a b"). All
# other Cc characters are removed outright.
_WHITESPACE_CONTROL_CHARS = frozenset({"\t", "\n", "\r", "\f", "\v"})

# Invisible format characters that can make a visually blank value look
# non-empty (zero-width space, bidi controls, BOM, soft hyphen). ZWNJ/ZWJ
# (U+200C/U+200D) are deliberately kept because they carry meaning in Indic
# scripts, and dropping them would alter clinical text.
_DROPPED_FORMAT_CHARS = frozenset(
    "\u00ad\u200b\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2060\u2066\u2067\u2068\u2069\ufeff"
)


def _without_invisible_characters(value: str) -> str:
    return "".join(
        character
        for character in value
        if character in _WHITESPACE_CONTROL_CHARS
        or (unicodedata.category(character) != "Cc" and character not in _DROPPED_FORMAT_CHARS)
    )


def normalize_plain_text(value: str, *, max_length: int = DEFAULT_MAX_LENGTH) -> str:
    """Normalize a free-text write value without changing its meaning.

    ``max_length`` truncates the normalized value. Values shorter than the
    limit are returned unchanged apart from the normalization steps, which are
    idempotent: normalizing an already-normalized value returns it unchanged.
    """
    if max_length < 1:
        raise ValueError("max_length must be at least 1")
    normalized = unicodedata.normalize("NFKC", value)
    collapsed = " ".join(_without_invisible_characters(normalized).split())
    return collapsed[:max_length]


def normalize_optional_plain_text(
    value: str | None, *, max_length: int = DEFAULT_MAX_LENGTH
) -> str | None:
    """Normalize an optional free-text value, leaving ``None`` untouched."""
    if value is None:
        return None
    return normalize_plain_text(value, max_length=max_length)
