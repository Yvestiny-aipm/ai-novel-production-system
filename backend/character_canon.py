"""Frozen book-level character facts. Previous-scene state cannot override this."""
from __future__ import annotations
import re

CHARACTER_CANON_VERSION = 1
CHARACTER_CANON_RULE = "character_canon_v1"
CHARACTER_CANON_REASON = "character_canon_conflict"
PRONOUN_LOOKAHEAD = 48
SUBJECT_TA = re.compile(r"[。！？\n，；、]他")
KINSHIP_FAIL = (
    re.compile(r"你姐姐"),
    re.compile(r"姐姐林澜"),
    re.compile(r"林澜姐姐"),
    re.compile(r"林澜是她的姐姐"),
    re.compile(r"林澜是姐姐"),
    re.compile(r"姐姐是林澜"),
)
MALE_OTHERS = ("老陈", "守灯的", "老人", "男人", "老头")
CLOSING_QUOTES = frozenset("”\"」』")
DIALOGUE_SAID_HE = re.compile(r"[”\"」』]他说")


def character_canon_snapshot(*, version: int = CHARACTER_CANON_VERSION) -> dict:
    return {
        "canon_version": version,
        "rule": CHARACTER_CANON_RULE,
        "characters": [
            {
                "name": "林照",
                "gender": "female",
                "pronoun": "她",
                "kinship": {"林澜": "妹妹"},
            },
            {
                "name": "林澜",
                "gender": "female",
                "pronoun": "她",
                "relation": "林照的妹妹",
            },
        ],
    }


def character_canon_instruction() -> str:
    return (
        "代词和亲属称谓以 context_pack.character_canon 为准，禁止写反。"
        "林照是女性，代词用她，不得用他承接林照。"
        "林澜是林照的妹妹，不得写成姐姐，不得对林照称林澜为你姐姐。"
    )


def _excerpt(text: str, start: int, end: int) -> str:
    return text[max(0, start - 4):min(len(text), end + 12)]


def _after_closing_quote(text: str, ta_at: int) -> bool:
    index = ta_at - 1
    while index >= 0 and text[index].isspace():
        index -= 1
    return index >= 0 and text[index] in CLOSING_QUOTES


def _dialogue_attribution_he(text: str, start: int, ta_at: int) -> bool:
    if _after_closing_quote(text, ta_at):
        return True
    return DIALOGUE_SAID_HE.search(text[start:ta_at + 1]) is not None


def _linzhao_pronoun_conflicts(text: str) -> list[dict]:
    conflicts = []
    start = 0
    while True:
        index = text.find("林照", start)
        if index < 0:
            break
        window = text[index:index + PRONOUN_LOOKAHEAD + 2]
        for match in SUBJECT_TA.finditer(window):
            ta_at = index + match.start() + 1
            between = text[index:ta_at]
            if any(name in between for name in MALE_OTHERS):
                continue
            if _dialogue_attribution_he(text, index, ta_at):
                continue
            conflicts.append({
                "kind": "pronoun",
                "name": "林照",
                "expected": "她",
                "found": "他",
                "excerpt": _excerpt(text, index, ta_at + 1),
            })
            break
        start = index + 2
    return conflicts


def _linlan_kinship_conflicts(text: str) -> list[dict]:
    conflicts = []
    for pattern in KINSHIP_FAIL:
        match = pattern.search(text)
        if not match:
            continue
        conflicts.append({
            "kind": "kinship",
            "name": "林澜",
            "expected": "妹妹",
            "found": match.group(0),
            "excerpt": _excerpt(text, match.start(), match.end()),
        })
    return conflicts


def validate_character_canon(text: str | None) -> dict:
    """Conservative content gate. Male-other 他 and 妹妹-for-林澜 must pass."""
    source = text if isinstance(text, str) else ""
    conflicts = _linzhao_pronoun_conflicts(source) + _linlan_kinship_conflicts(source)
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
