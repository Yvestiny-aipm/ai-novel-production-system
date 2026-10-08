"""Frozen book-level character facts. Previous-scene state cannot override this."""
from __future__ import annotations
import re

CHARACTER_CANON_VERSION = 1
CHARACTER_CANON_RULE = "character_canon_v1"
CHARACTER_CANON_REASON = "character_canon_conflict"
PRONOUN_LOOKAHEAD = 80
PRONOUN_LOOKBACK = 80
SUBJECT_HE = re.compile(r"(?:^|(?<=[.!?,;:\n—–-])\s*)He\b")
FEMALE_PRONOUNS = frozenset({"she"})
GENERIC_MALE_NOUNS = (
    "man", "men", "old man", "boy", "gentleman", "fellow", "guy", "lad",
)
MALE_OTHERS = ("Old Chen", "the lamp keeper", "the night watchman")
OBJECT_HIM = (
    " him", "ask him", "let him", "stop him", "tell him", "give him",
    "to him", "at him", "for him", "with him", "of him", "on him",
)
OBJECT_NAME_PREFIXES = ("in front of ", "sent ", "took ", "led ", "to ", "toward ")
NAME_INTRODUCERS = ("found ", "saw ", "met ", "called ", "named ", "reached ")
TITLE_ROLES = tuple(sorted((
    "night watchman", "lamp keeper", "archivist", "attendant", "registrar",
    "inspector", "watchman", "curator", "steward", "officer", "keeper",
    "warden", "clerk", "guard",
), key=len, reverse=True))
HANDOFF_MARKERS = ("handed it over", "handed it", "handed over", "gave it to", "passed it")
ENTRANCE_TIME_MARKERS = (
    "when she came in", "as she entered", "when she entered", "as she came in",
    "when she walked in", "came in", "walked in",
)
CLOSING_QUOTES = frozenset('"“”\'')
DIALOGUE_SAID_HE = re.compile(r'["”\']\s*he said', re.IGNORECASE)
NAME_STOPWORDS = frozenset({
    "The", "She", "He", "Then", "When", "After", "Before", "And", "But", "That",
    "This", "There", "Here", "Now", "Later", "Suddenly", "Still", "Only", "Even",
    "Also", "So", "If", "As", "While", "Once", "Just", "Maybe", "Perhaps",
    "Meanwhile", "Finally", "Next", "Last", "First", "Her", "His", "They",
})
PROPER_NAME = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b")


def character_canon_snapshot(*, version: int = CHARACTER_CANON_VERSION) -> dict:
    return {
        "canon_version": version,
        "rule": CHARACTER_CANON_RULE,
        "characters": [
            {
                "name": "Lin Zhao",
                "gender": "female",
                "pronoun": "she",
                "kinship": {"Lin Lan": "younger sister"},
            },
            {
                "name": "Lin Lan",
                "gender": "female",
                "pronoun": "she",
                "relation": "Lin Zhao's younger sister",
            },
        ],
        "male_others": list(MALE_OTHERS),
    }


def _female_characters(snapshot: dict) -> list[dict]:
    return [
        item for item in snapshot.get("characters") or []
        if item.get("gender") == "female"
        and str(item.get("pronoun") or "").lower() in FEMALE_PRONOUNS
        and item.get("name")
    ]


def character_canon_instruction(snapshot: dict | None = None) -> str:
    snap = snapshot or character_canon_snapshot()
    females = _female_characters(snap)
    female_names = [item["name"] for item in females]
    parts = ["Pronouns and kinship follow context_pack.character_canon. Do not reverse them."]
    for person in females:
        name = person["name"]
        parts.append(f"{name} is female. Use she. Do not use He to continue {name}.")
        for other, relation in (person.get("kinship") or {}).items():
            if relation == "younger sister":
                parts.append(
                    f"{other} is {name}'s younger sister. Do not write older sister. "
                    f"Do not call {other} your older sister when addressing {name}."
                )
    named_males = [
        name for name in (snap.get("male_others") or [])
        if name not in GENERIC_MALE_NOUNS
    ]
    if named_males and female_names:
        for male in named_males:
            parts.append(f"{male} is male. He does not refer to {female_names[0]}.")
    parts.append("Name the person before switching reference. When both are present and easy to mix, use names, not pronouns alone.")
    return "".join(parts)


def _excerpt(text: str, start: int, end: int) -> str:
    return text[max(0, start - 4):min(len(text), end + 12)]


def _after_closing_quote(text: str, he_at: int) -> bool:
    index = he_at - 1
    while index >= 0 and text[index].isspace():
        index -= 1
    return index >= 0 and text[index] in CLOSING_QUOTES


def _dialogue_attribution_he(text: str, start: int, he_at: int) -> bool:
    if _after_closing_quote(text, he_at):
        return True
    return DIALOGUE_SAID_HE.search(text[start:he_at + 2]) is not None


def _name_used_as_object(text: str, name_at: int) -> bool:
    before = text[max(0, name_at - 12):name_at].lower()
    return any(before.endswith(prefix) for prefix in OBJECT_NAME_PREFIXES)


def _asked_then_answered(between: str, after_he: str) -> bool:
    low = between.lower()
    nxt = after_he.lower()
    return ("ask" in low or "asked" in low) and nxt.startswith((" said", " answered", " replied", " said"))


def _overlaps_female_name(candidate: str, female_names: tuple[str, ...]) -> bool:
    return any(name in candidate or candidate in name for name in female_names)


def _span_has_other_male(span: str, female_names: tuple[str, ...], male_others: tuple[str, ...]) -> bool:
    lower = span.lower()
    if any(marker.lower() in lower for marker in male_others):
        return True
    if any(noun in lower for noun in GENERIC_MALE_NOUNS):
        return True
    if any(title in lower for title in TITLE_ROLES):
        return True
    for match in PROPER_NAME.finditer(span):
        candidate = match.group(1)
        if candidate in NAME_STOPWORDS:
            continue
        if _overlaps_female_name(candidate, female_names):
            continue
        return True
    return False


def _pronoun_conflicts(text: str, snapshot: dict) -> list[dict]:
    conflicts = []
    female_names = tuple(item["name"] for item in _female_characters(snapshot))
    male_others = tuple(snapshot.get("male_others") or [])
    for name in female_names:
        start = 0
        while True:
            index = text.find(name, start)
            if index < 0:
                break
            window = text[index:index + PRONOUN_LOOKAHEAD + len(name) + 8]
            lookback_at = max(0, index - PRONOUN_LOOKBACK)
            for match in SUBJECT_HE.finditer(window):
                he_offset = match.group(0).rfind("He")
                if he_offset < 0:
                    continue
                he_at = index + match.start() + he_offset
                if he_at < index or text[he_at:he_at + 2] != "He":
                    continue
                between = text[index:he_at]
                span = text[lookback_at:he_at]
                if _span_has_other_male(span, female_names, male_others):
                    continue
                if _name_used_as_object(text, index):
                    continue
                if any(marker in between.lower() for marker in OBJECT_HIM):
                    continue
                if _asked_then_answered(between, text[he_at + 2:he_at + 16]):
                    continue
                if any(marker in between.lower() for marker in HANDOFF_MARKERS):
                    continue
                if any(marker in between.lower() for marker in ENTRANCE_TIME_MARKERS):
                    continue
                if _dialogue_attribution_he(text, index, he_at):
                    continue
                conflicts.append({
                    "kind": "pronoun",
                    "name": name,
                    "expected": "she",
                    "found": "He",
                    "excerpt": _excerpt(text, index, he_at + 2),
                })
                break
            start = index + len(name)
    return conflicts


def _kinship_conflicts(text: str, snapshot: dict) -> list[dict]:
    conflicts = []
    source = text.lower()
    for person in _female_characters(snapshot):
        for other, relation in (person.get("kinship") or {}).items():
            if relation != "younger sister":
                continue
            other_l = other.lower()
            phrases = (
                "your older sister",
                f"older sister {other_l}",
                f"{other_l} is her older sister",
                f"{other_l} is the older sister",
                f"the older sister is {other_l}",
            )
            for phrase in phrases:
                found_at = source.find(phrase)
                if found_at < 0:
                    continue
                conflicts.append({
                    "kind": "kinship",
                    "name": other,
                    "expected": "younger sister",
                    "found": text[found_at:found_at + len(phrase)],
                    "excerpt": _excerpt(text, found_at, found_at + len(phrase)),
                })
                return conflicts
    return conflicts


def validate_character_canon(text: str | None, snapshot: dict | None = None) -> dict:
    """Conservative content gate. Nearby male He and older-sister kinship must pass."""
    source = text if isinstance(text, str) else ""
    snap = snapshot or character_canon_snapshot()
    conflicts = _pronoun_conflicts(source, snap) + _kinship_conflicts(source, snap)
    if conflicts:
        return {
            "status": "failed",
            "reason": CHARACTER_CANON_REASON,
            "rule": CHARACTER_CANON_RULE,
            "conflicts": conflicts,
        }
    return {
        "status": "passed",
        "reason": None,
        "rule": CHARACTER_CANON_RULE,
        "conflicts": [],
    }
