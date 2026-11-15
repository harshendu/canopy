"""Rule suggestions — docs/AGENT_EXECUTION.md §21 Phase 4 (pure).

When the same request-changes note or review finding keeps coming back, the team is teaching
the same lesson by hand. This module groups recurring notes (people's request-changes notes on
gates, reviewers' findings on failed or concerned reviews) by the words they share and offers
each recurring theme as a candidate rule. A session can stage one as a `rule` proposal; a person
accepts it in Reviews (rules stay human-written — §10).

The notes are content (people's and agents' words): they are shown as evidence and never
treated as instructions.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

MIN_OCCURRENCES = 3
MIN_TASKS = 2
SIMILARITY = 0.4  # Jaccard over content words, to join a theme

_STOP = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can", "could", "did", "do",
    "does", "for", "from", "had", "has", "have", "how", "if", "in", "into", "is", "it", "its",
    "just", "more", "most", "must", "need", "needs", "no", "not", "of", "on", "or", "our",
    "please", "should", "so", "some", "still", "such", "than", "that", "the", "their", "them",
    "then", "there", "these", "they", "this", "those", "to", "too", "use", "used", "using",
    "very", "was", "we", "were", "what", "when", "where", "which", "while", "who", "why",
    "will", "with", "without", "would", "you", "your", "also", "again", "here", "like", "make",
    "makes", "made", "add", "added", "adds", "get", "got", "one", "two", "all", "any", "each",
    "other", "only", "same", "see", "seen",
})
_WORD = re.compile(r"[a-z][a-z0-9_-]{2,}")


@dataclass
class NoteRow:
    source: str  # gate | review
    source_id: int
    task_id: int
    task_key: str | None
    text: str
    at: datetime


@dataclass
class Theme:
    key: str
    words: list[str]
    notes: list[NoteRow] = field(default_factory=list)

    @property
    def tasks(self) -> list[str]:
        out: list[str] = []
        for note in self.notes:
            label = note.task_key or f"#{note.task_id}"
            if label not in out:
                out.append(label)
        return out


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def words(text: str) -> frozenset[str]:
    """The content words of a note (lowercase, stop words out, crude stemming)."""
    return frozenset(_stem(w) for w in _WORD.findall(text.lower()) if w not in _STOP)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def slug(parts: Iterable[str]) -> str:
    return "-".join(parts)[:60].strip("-") or "recurring-note"


def themes(notes: Sequence[NoteRow]) -> list[Theme]:
    """Group notes whose content words overlap (greedy, oldest first, against each theme's
    first note) — small, explainable, deterministic."""
    groups: list[tuple[frozenset[str], list[NoteRow]]] = []
    for note in sorted(notes, key=lambda n: (n.at, n.source_id)):
        bag = words(note.text)
        if len(bag) < 2:
            continue
        for anchor, members in groups:
            if _jaccard(anchor, bag) >= SIMILARITY:
                members.append(note)
                break
        else:
            groups.append((bag, [note]))
    out: list[Theme] = []
    for anchor, members in groups:
        counts: dict[str, int] = {}
        for note in members:
            for w in words(note.text):
                counts[w] = counts.get(w, 0) + 1
        common = [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
                  if w in anchor][:3]
        out.append(Theme(key=slug(common), words=common, notes=members))
    return out


def suggest(
    notes: Sequence[NoteRow], existing_rules: Sequence[tuple[str, str, str]] = ()
) -> list[Theme]:
    """Recurring themes — at least MIN_OCCURRENCES notes across MIN_TASKS tasks — that no
    existing rule (key, title, body) already covers, most frequent first."""
    covered = [(key, words(f"{key.replace('-', ' ')} {title} {body}"))
               for key, title, body in existing_rules]
    out: list[Theme] = []
    for theme in themes(notes):
        if len(theme.notes) < MIN_OCCURRENCES or len(theme.tasks) < MIN_TASKS:
            continue
        top = set(theme.words)
        # Covered: a rule with the same key, or one that says the theme's main words already.
        if any(key == theme.key or len(top & rule) >= max(1, len(top) - 1)
               for key, rule in covered):
            continue
        out.append(theme)
    return sorted(out, key=lambda t: (-len(t.notes), t.key))
