"""Local hybrid retrieval: lexical, entity, topic, importance and temporal signals."""

import re
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import Character, Knowledge

TOPICS = {
    "relationship": (
        "vertrau",
        "streit",
        "freund",
        "konflikt",
        "beziehung",
        "zwischen euch",
        "zwischen uns",
        "versöhn",
        "verzeih",
        "hass",
        "liebe",
        "enttäusch",
    ),
    "promise": ("versproch", "versprech", "zusage", "morgen", "wiederkomm", "abmach"),
    "meeting": ("begegn", "kennenlern", "getroffen", "traf ", "treffen", "besuch"),
    "loss": ("gestorb", " tot", "tod", "lebendig", "lebt", "verlor", "trauer"),
}


def topics(text: str) -> set[str]:
    lower = text.casefold()
    return {key for key, words in TOPICS.items() if any(word in lower for word in words)}


def retrieve(
    db: Session,
    world_id: str,
    character_id: str,
    query: str,
    recent_text: str = "",
) -> list[Knowledge]:
    rows = list(
        db.scalars(
            select(Knowledge)
            .where(
                Knowledge.world_id == world_id,
                Knowledge.status.in_(
                    ["active", "superseded"]
                    if any(
                        term in query.casefold()
                        for term in ("früher", "damals", "geglaubt", "dachtest")
                    )
                    else ["active"]
                ),
                or_(
                    Knowledge.character_id == character_id,
                    (Knowledge.kind == "fact") & Knowledge.public.is_(True),
                ),
            )
            .order_by(Knowledge.created_at.desc(), Knowledge.id)
        )
    )
    words = set(re.findall(r"\w{3,}", query.casefold()))
    query_topics = topics(query)
    mentioned = {
        character.id
        for character in db.scalars(select(Character).where(Character.world_id == world_id))
        if character.name.casefold() in (query + " " + recent_text).casefold()
    }
    timestamp = datetime.now(UTC)

    def score(entry: Knowledge) -> float:
        entry_words = set(re.findall(r"\w{3,}", entry.content.casefold()))
        created = entry.occurred_at or entry.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        age = max(0, (timestamp - created).total_seconds() / 86400)
        return (
            4 * len(words & entry_words) / max(1, len(words))
            + 3 * len(query_topics & topics(entry.content))
            + (3 if entry.subject_id in mentioned else 0)
            + entry.importance / 100
            + 1 / (1 + age / 30)
        )

    return sorted(rows, key=score, reverse=True)


def compact_content(content: str, query: str, max_chars: int = 1800) -> str:
    """Extract whole original sentences, never synthesize or merge character accounts."""
    sentences = re.split(r"(?<=[.!?])\s+|\n+", content)
    words = set(re.findall(r"\w{3,}", query.casefold()))
    ranked = sorted(
        enumerate(sentences),
        key=lambda pair: (
            len(words & set(re.findall(r"\w{3,}", pair[1].casefold()))),
            -pair[0],
        ),
        reverse=True,
    )
    chosen: list[tuple[int, str]] = []
    length = 0
    for index, sentence in ranked:
        if sentence and length + len(sentence) <= max_chars:
            chosen.append((index, sentence))
            length += len(sentence) + 1
    return "\n".join(sentence for _, sentence in sorted(chosen))
