"""Frozen book-level setting facts. Previous-scene state cannot override this."""
from __future__ import annotations
import re

SETTING_CANON_VERSION = 1
SETTING_CANON_RULE = "setting_canon_v1"
SETTING_CANON_REASON = "setting_canon_conflict"
INVENTED_OFFICIAL_LAYERS = (
    "Inscription Pavilion", "Stele Vault", "Stele Store", "Inscription Hall", "Memory Temple",
)
OFFICIAL_ROOMS = ("Archive Room", "Memory Hall", "Glyph Vault")
MERGE_MARKERS = ("the same room", "the same place", "one room", "a single room")
NEGATION_TAILS = ("not", "cannot", "must not", "never")
ROOM_IS = re.compile(
    r"(Archive Room|Memory Hall|Glyph Vault)(?:[^.!?\n]{0,20})(is also|is|equals)(?:[^.!?\n]{0,8})(Archive Room|Memory Hall|Glyph Vault)",
    re.IGNORECASE,
)
ROOM_AND_SAME = re.compile(
    r"(Archive Room|Memory Hall|Glyph Vault)(?:[^.!?\n]{0,24})(?:and|,)(?:[^.!?\n]{0,12})"
    r"(Archive Room|Memory Hall|Glyph Vault)(?:[^.!?\n]{0,16})(the same room|the same place|one room|a single room)",
    re.IGNORECASE,
)
REWRITE_MEMORY = re.compile(
    r"lighthouse(.{0,32})(rewrote|rewrite|alter|overwrite|delete|deleted|overwrote)(.{0,16})memory",
    re.IGNORECASE,
)
COMPLETE_NAME = re.compile(
    r"lighthouse(.{0,24})(completed|completes|filled in|fill in)(.{0,24})(name|last character)",
    re.IGNORECASE,
)


def setting_canon_snapshot(*, version: int = SETTING_CANON_VERSION) -> dict:
    return {
        "canon_version": version,
        "rule": SETTING_CANON_RULE,
        "places": [
            {
                "name": "Archive Room",
                "also": ["Preservation tier"],
                "layer": "Preservation tier",
                "props": ["chips", "brass plates", "racks"],
                "function": "store archived memory media",
            },
            {
                "name": "Memory Hall",
                "also": ["Display tier"],
                "layer": "Display tier",
                "props": ["wall script"],
                "function": "display retrieved memory; cannot rewrite",
            },
            {
                "name": "Glyph Vault",
                "also": ["Unnamed tier"],
                "layer": "Unnamed tier",
                "props": ["wooden cases"],
                "function": "hold unnamed glyphs",
            },
        ],
        "must_not": [
            "rewrite, overwrite, or delete a person's memory",
            "complete anyone's name or last character",
            "invent a fourth official storage or display system",
            "write Archive Room, Memory Hall, and Glyph Vault as the same room",
            "treat the public archive, the town, Amah Zhou's house, or the Jiang house as inside the lighthouse",
        ],
    }


def setting_canon_instruction() -> str:
    return (
        "Places follow context_pack.setting_canon."
        "The lighthouse body has only Archive Room, Memory Hall, and Glyph Vault. They may exist at the same time. Do not write them as the same room."
        "The lighthouse may only store, retrieve, and display. It must not rewrite, overwrite, or delete a person's memory, and must not complete anyone's name or last character."
        "Do not invent a fourth official storage or display system."
        "The public archive, the town, Amah Zhou's house, and the Jiang house are not inside the lighthouse."
    )


def _excerpt(text: str, start: int, end: int) -> str:
    return text[max(0, start - 4):min(len(text), end + 12)]


def _negated(gap: str) -> bool:
    tail = gap[-12:].lower()
    return any(gap.lower().endswith(token) or token in tail for token in NEGATION_TAILS)


def _invented_layer_conflicts(text: str) -> list[dict]:
    conflicts = []
    for name in INVENTED_OFFICIAL_LAYERS:
        index = text.find(name)
        if index < 0:
            continue
        conflicts.append({
            "kind": "invented_official_layer",
            "name": name,
            "expected": "Archive Room / Memory Hall / Glyph Vault",
            "found": name,
            "excerpt": _excerpt(text, index, index + len(name)),
        })
        break
    return conflicts


def _same_room_conflicts(text: str) -> list[dict]:
    conflicts = []
    for match in ROOM_IS.finditer(text):
        if match.group(1).lower() == match.group(3).lower():
            continue
        conflicts.append({
            "kind": "collapsed_layers",
            "name": f"{match.group(1)}/{match.group(3)}",
            "expected": "three layers exist at once, not the same room",
            "found": match.group(0),
            "excerpt": _excerpt(text, match.start(), match.end()),
        })
        return conflicts
    for match in ROOM_AND_SAME.finditer(text):
        if match.group(1).lower() == match.group(2).lower():
            continue
        conflicts.append({
            "kind": "collapsed_layers",
            "name": f"{match.group(1)}/{match.group(2)}",
            "expected": "three layers exist at once, not the same room",
            "found": match.group(0),
            "excerpt": _excerpt(text, match.start(), match.end()),
        })
        return conflicts
    for marker in MERGE_MARKERS:
        start = 0
        while True:
            index = text.lower().find(marker, start)
            if index < 0:
                break
            window = text[max(0, index - 48):index + len(marker)]
            rooms = [name for name in OFFICIAL_ROOMS if name.lower() in window.lower()]
            if len(rooms) >= 2:
                conflicts.append({
                    "kind": "collapsed_layers",
                    "name": "/".join(rooms),
                    "expected": "three layers exist at once, not the same room",
                    "found": marker,
                    "excerpt": _excerpt(text, index, index + len(marker)),
                })
                return conflicts
            start = index + len(marker)
    return conflicts


def _rewrite_memory_conflicts(text: str) -> list[dict]:
    conflicts = []
    for match in REWRITE_MEMORY.finditer(text):
        if _negated(match.group(1)):
            continue
        conflicts.append({
            "kind": "memory_rewrite",
            "name": "lighthouse",
            "expected": "may only store, retrieve, and display",
            "found": match.group(2),
            "excerpt": _excerpt(text, match.start(), match.end()),
        })
        break
    return conflicts


def _complete_name_conflicts(text: str) -> list[dict]:
    conflicts = []
    for match in COMPLETE_NAME.finditer(text):
        if _negated(match.group(1)):
            continue
        conflicts.append({
            "kind": "name_completion",
            "name": "lighthouse",
            "expected": "must not complete a name or last character",
            "found": match.group(3),
            "excerpt": _excerpt(text, match.start(), match.end()),
        })
        break
    return conflicts


def validate_setting_canon(text: str | None) -> dict:
    """Conservative content gate. Outside-lighthouse places and layered props must pass."""
    source = text if isinstance(text, str) else ""
    conflicts = (
        _invented_layer_conflicts(source)
        + _same_room_conflicts(source)
        + _rewrite_memory_conflicts(source)
        + _complete_name_conflicts(source)
    )
    if conflicts:
        return {
            "status": "failed",
            "reason": SETTING_CANON_REASON,
            "rule": SETTING_CANON_RULE,
            "conflicts": conflicts,
        }
    return {
        "status": "passed",
        "reason": None,
        "rule": SETTING_CANON_RULE,
        "conflicts": [],
    }
