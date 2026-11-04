"""Conservative source-to-slot binding, never semantic guessing or automatic remapping."""

import json
import re
from decimal import Decimal
from typing import NoReturn

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .event_schemas import StateValue
from .models import Character, Location, Relationship, World
from .schemas import Attribute

NUMBER = r"[+-]?(?:\d+(?:[.,]\d+)?|\.\d+)"
UNCERTAIN = re.compile(
    r"\b(?:nicht|nie|niemals|kein\w*|not|never|soll\w*|würde\w*|möchte\w*|vielleicht|falls|"
    r"will|would|might|should|höchstens|mindestens|maximum|minimum|unter|über)\b",
    re.IGNORECASE,
)


def reject(detail: str) -> NoReturn:
    raise HTTPException(422, detail)


def phrase(value: str) -> str:
    return r"(?<!\w)" + re.escape(value.casefold()) + r"(?!\w)"


def explicit_number(quote: str, label_end: int, old: StateValue, new: float) -> None:
    if "?" in quote or UNCERTAIN.search(quote):
        reject("Numerische Änderung ist unklar, verneint oder nur beabsichtigt.")
    suffix = quote.casefold()[label_end:].strip().rstrip(".!; ")
    transition = re.search(
        rf"(?:\b(?:von|from)\s+)?(?P<old>{NUMBER})\s*(?:auf|to|->|→)\s*"
        rf"(?P<new>{NUMBER})\s*$",
        suffix,
    )
    assignment = re.search(
        rf"(?:\b(?:auf|to|beträgt|ist(?:\s+(?:jetzt|nun))?|is(?:\s+now)?)\b|[=:])"
        rf"\s*(?P<new>{NUMBER})\s*$",
        suffix,
    )
    match = transition or assignment
    if match is None:
        reject("Numerischer Zielwert benötigt eine ausdrückliche Zuweisung im Quellenzitat.")
    if Decimal(match["new"].replace(",", ".")) != Decimal(str(new)):
        reject("Vorgeschlagener Zahlenwert stimmt nicht mit dem Quellenbeleg überein.")
    if transition and (
        isinstance(old, bool)
        or not isinstance(old, (int, float))
        or Decimal(transition["old"].replace(",", ".")) != Decimal(str(old))
    ):
        reject("Genannter Ausgangswert stimmt nicht mit dem bestehenden Attribut überein.")
    prefix = suffix[: match.start()]
    if not re.fullmatch(
        r"\s*(?:(?:steigt|sinkt|wächst|fällt|ändert sich|erhöht sich|verringert sich|"
        r"rises|increases|decreases|changes)\s+)?",
        prefix,
    ):
        reject("Mehrdeutiger Zahlenbeleg: nur ausdrückliche einzelne Zuweisungen übernehmen.")


def owner_pattern(recipient: Character | Location | World, own_speech: bool) -> str:
    pronoun = "mein" if own_speech else "dein"
    return (
        rf"(?:{pronoun}(?:e[rmns]?)?|{re.escape(recipient.name.casefold())}(?:['\u2019]?s)?)"
        r"\s+"
    )


def literal_values(value: StateValue, text: str, field: str) -> None:
    literal = json.dumps(value, ensure_ascii=False) if isinstance(value, list) else str(value)
    if not re.fullmatch(
        r"\s*(?:[:=]|ist|is)\s*" + re.escape(literal.casefold()) + r"\s*[.!]?\s*",
        text.casefold(),
    ):
        reject(f"Neuer Wert für '{field}' ist nicht wörtlich belegt.")


def state_binding(
    row: Character | Location | World,
    values: dict[str, StateValue],
    quote: str,
    own_speech: bool,
    value_quotes: dict[str, str],
) -> None:
    if set(value_quotes) - set(values):
        reject("Zustandszitate dürfen nur die vorgeschlagenen Zustandsfelder referenzieren.")
    for key, value in values.items():
        if key not in row.state:
            reject(
                f"Unbekanntes Zustandsfeld '{key}'. Extraktion darf keine Ersatzfelder anlegen; "
                "bestehende Beziehung/Attribute referenzieren oder das Feld zuerst "
                "im Editor anlegen."
            )
        evidence = value_quotes.get(key, quote if len(values) == 1 else "")
        if not evidence.strip() or evidence not in quote:
            reject("Jedes Zustandsfeld benötigt ein eigenes wörtliches Quellenzitat.")
        text = evidence.casefold()
        old = row.state[key]
        old_type = (
            float if isinstance(old, (int, float)) and not isinstance(old, bool) else type(old)
        )
        new_type = (
            float
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            else type(value)
        )
        if old_type != new_type:
            reject(f"Extraktion darf den Datentyp von Zustandsfeld '{key}' nicht ändern.")
        label = phrase(key)
        if row.id.casefold() not in text:
            label = owner_pattern(row, own_speech) + label
        matches = list(re.finditer(label, text))
        if len(matches) != 1:
            reject(f"Zustandsfeld '{key}' benötigt einen eindeutigen wörtlichen Quellenbeleg.")
        if row.id.casefold() not in text and text[: matches[0].start()].strip():
            reject("Zustandszitat muss eine einzelne ausdrückliche Zuweisung enthalten.")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            explicit_number(evidence, matches[0].end(), old, value)
        else:
            literal_values(value, text[matches[0].end() :], key)


def relationship_binding(
    db: Session,
    relationship: Relationship,
    recipient: Character,
    target_id: str | None,
    attributes: list[Attribute],
    attribute_quotes: dict[str, str],
    quote: str,
    own_speech: bool,
) -> None:
    if target_id != relationship.target_id:
        reject(f"Beziehungsoperation benötigt target_id '{relationship.target_id}'.")
    target = db.get(Character, relationship.target_id)
    if target is None or target.world_id != relationship.world_id:
        reject("Zielcharakter der Beziehung fehlt.")
    if set(attribute_quotes) - {attribute.name for attribute in attributes}:
        reject(
            "attribute_quotes-Schlüssel müssen exakt den Attributnamen entsprechen: "
            + ", ".join(attribute.name for attribute in attributes)
            + ". Bei nur einem Attribut attribute_quotes weglassen oder {} verwenden."
        )
    existing = {attribute["name"]: attribute for attribute in relationship.attributes}
    for attribute in attributes:
        evidence = attribute_quotes.get(attribute.name, quote if len(attributes) == 1 else "")
        if not evidence.strip() or evidence not in quote:
            reject("Jedes Beziehungsattribut benötigt ein eigenes wörtliches Quellenzitat.")
        text = evidence.casefold()
        if relationship.id.casefold() in text:
            labels = list(re.finditer(phrase(attribute.name), text))
        else:
            same_name = [
                row
                for row in db.scalars(
                    select(Character).where(Character.world_id == target.world_id)
                )
                if row.name.casefold() == target.name.casefold()
            ]
            candidates = [
                row
                for row in db.scalars(
                    select(Relationship).where(
                        Relationship.world_id == relationship.world_id,
                        Relationship.source_id == recipient.id,
                        Relationship.target_id == target.id,
                    )
                )
                if any(a["name"].casefold() == attribute.name.casefold() for a in row.attributes)
            ]
            if len(same_name) != 1 or len(candidates) != 1:
                reject("Mehrdeutige Beziehung: im Quellenzitat die konkrete Beziehungs-ID angeben.")
            # A local grammatical target binding prevents accidentally using an incoming view.
            labels = list(
                re.finditer(
                    owner_pattern(recipient, own_speech)
                    + phrase(attribute.name)
                    + r"\s+(?:zu|in|gegenüber|towards|for|to)\s+"
                    + phrase(target.name),
                    text,
                )
            )
        if len(labels) != 1:
            reject(
                f"Quellenbeleg muss '{attribute.name} zu {target.name}' "
                "oder die Beziehungs-ID mit Attributnamen eindeutig benennen."
            )
        prefix = text[: labels[0].start()].strip()
        if prefix and not re.fullmatch(re.escape(relationship.id) + r"[\s:/]*", prefix):
            reject("Attributzitat muss eine einzelne ausdrückliche Zuweisung enthalten.")
        if attribute.type == "number":
            if isinstance(attribute.value, bool) or not isinstance(attribute.value, (int, float)):
                reject("Numerisches Beziehungsattribut benötigt einen Zahlenwert.")
            explicit_number(
                evidence, labels[0].end(), existing[attribute.name]["value"], attribute.value
            )
        else:
            literal_values(attribute.value, text[labels[0].end() :], attribute.name)


def reject_relationship_state_aliases(db: Session, recipient: Character, quote: str) -> None:
    text = quote.casefold()
    for relationship in db.scalars(
        select(Relationship).where(
            Relationship.world_id == recipient.world_id,
            Relationship.source_id == recipient.id,
        )
    ):
        target = db.get(Character, relationship.target_id)
        if (
            target
            and any(
                re.search(phrase(attribute["name"]), text) for attribute in relationship.attributes
            )
            and (re.search(phrase(target.name), text) or target.id.casefold() in text)
        ):
            reject(
                "Quelle beschreibt ein bestehendes Beziehungsattribut. "
                "Eine state-Operation wäre mehrdeutig; relationship mit bestehender ID verwenden."
            )
