"""Parse a markdown document into ADR fields (pure, unit-testable).

Maps the first level-1 heading to the title and fuzzily matches level-2 sections
to context / decision / consequences.
"""

from __future__ import annotations

import re

_H1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_H2_SPLIT = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def _sections(text: str) -> dict[str, str]:
    parts = _H2_SPLIT.split(text)
    sections: dict[str, str] = {}
    for i in range(1, len(parts), 2):
        heading = parts[i].strip().lower()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        sections[heading] = body
    return sections


def _match(sections: dict[str, str], *keywords: str) -> str | None:
    for heading, body in sections.items():
        if any(k in heading for k in keywords):
            return body or None
    return None


def parse_markdown_adr(text: str, fallback_title: str) -> dict[str, str | None]:
    title_match = _H1.search(text)
    title = title_match.group(1).strip() if title_match else fallback_title
    sections = _sections(text)
    return {
        "title": title,
        "context": _match(sections, "context", "forces", "background"),
        "decision": _match(sections, "decision", "choice"),
        "consequences": _match(sections, "consequence", "outcome", "result", "tradeoff"),
    }
