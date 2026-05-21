"""Plain-text extraction from HTML email content.

Mirakl threads frequently contain raw HTML from Outlook, Gmail, Apple Mail,
and operator forward systems. The LLM works better on plain text and the UI
preview is cleaner without markup, so we strip tags and decode entities
before feeding the text downstream.

This is a deliberately small, dependency-free implementation. We do not
need a full HTML parser — we only need to extract human-readable text from
email-style payloads.
"""

from __future__ import annotations

import html
import re

_BLOCK_TAG_RE = re.compile(
    r"<(script|style|head)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def strip_html(text: str) -> str:
    """Return a plain-text version of ``text``.

    - Removes ``<script>``, ``<style>``, and ``<head>`` blocks entirely
      (including their content).
    - Strips all remaining HTML tags.
    - Decodes HTML entities (``&nbsp;``, ``&#160;``, named entities, etc.).
    - Collapses runs of whitespace into single spaces.

    Plain-text input is returned unchanged apart from whitespace normalisation.
    Empty / None input returns an empty string.
    """
    if not text:
        return ""

    without_blocks = _BLOCK_TAG_RE.sub(" ", text)
    without_tags = _TAG_RE.sub(" ", without_blocks)
    decoded = html.unescape(without_tags)
    return _WHITESPACE_RE.sub(" ", decoded).strip()
