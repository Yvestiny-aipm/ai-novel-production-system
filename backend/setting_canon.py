"""Frozen book-level setting facts. Previous-scene state cannot override this."""
from __future__ import annotations
import re

SETTING_CANON_VERSION = 1
SETTING_CANON_RULE = "setting_canon_v1"
SETTING_CANON_REASON = "setting_canon_conflict"
INVENTED_OFFICIAL_LAYERS = ("铭录阁", "石碑库", "碑库", "铭文殿", "记忆圣殿")
OFFICIAL_ROOMS = ("档案室", "记忆厅", "字库")
MERGE_MARKERS = ("同一间", "同一处", "同一个房间", "同一房间")
NEGATION_TAILS = ("不", "不得", "不能", "禁止")
ROOM_IS = re.compile(
    r"(档案室|记忆厅|字库)(?:[^。！？\n]{0,20})(就是|也是|即是|即)(?:[^。！？\n]{0,8})(档案室|记忆厅|字库)"
)
ROOM_AND_SAME = re.compile(
    r"(档案室|记忆厅|字库)(?:[^。！？\n]{0,24})(?:和|与|、)(?:[^。！？\n]{0,12})"
    r"(档案室|记忆厅|字库)(?:[^。！？\n]{0,16})(同一间|同一处|同一个房间|同一房间)"
)
REWRITE_MEMORY = re.compile(r"灯塔(.{0,32})(改写|修改|覆盖|删除)(.{0,16})记忆")
COMPLETE_NAME = re.compile(r"灯塔(.{0,24})补[上全](.{0,8})(名字|末字)")


def setting_canon_snapshot(*, version: int = SETTING_CANON_VERSION) -> dict:
    return {
        "canon_version": version,
        "rule": SETTING_CANON_RULE,
        "places": [
            {
                "name": "档案室",
                "also": ["保存层"],
                "layer": "保存层",
                "props": ["晶片", "铜牌", "柜架"],
                "function": "保存已归档的记忆载体",
            },
            {
                "name": "记忆厅",
                "also": ["展示层"],
                "layer": "展示层",
                "props": ["墙上浮字"],
                "function": "展示被调取的记忆，不能改写",
            },
            {
                "name": "字库",
                "also": ["未成名层"],
                "layer": "未成名层",
                "props": ["木匣"],
                "function": "存放未成名的字",
            },
        ],
        "must_not": [
            "改写、覆盖或删除人的记忆",
            "补全任何人的名字或末字",
            "发明第四套官方存放或展示系统",
            "把档案室、记忆厅、字库写成同一间房",
            "把公共档案馆、镇上、周阿婆家、蒋家并入灯塔内部",
        ],
    }


def setting_canon_instruction() -> str:
    return (
        "场地分层以 context_pack.setting_canon 为准。"
        "灯塔本体只有档案室、记忆厅、字库三层，可以同时存在，不得写成同一间房。"
        "灯塔只能保存、检索、展示，不得改写、覆盖、删除人的记忆，不得补全任何人的名字或末字。"
        "禁止再发明第四套官方存放或展示系统。"
        "公共档案馆、镇上、周阿婆家、蒋家不是灯塔内部。"
    )


def _excerpt(text: str, start: int, end: int) -> str:
    return text[max(0, start - 4):min(len(text), end + 12)]


def _negated(gap: str) -> bool:
    tail = gap[-4:]
    return any(gap.endswith(token) or token in tail for token in NEGATION_TAILS)


def _invented_layer_conflicts(text: str) -> list[dict]:
    conflicts = []
    for name in INVENTED_OFFICIAL_LAYERS:
        index = text.find(name)
        if index < 0:
            continue
        conflicts.append({
            "kind": "invented_official_layer",
            "name": name,
            "expected": "档案室 / 记忆厅 / 字库",
            "found": name,
            "excerpt": _excerpt(text, index, index + len(name)),
        })
        break
    return conflicts


def _same_room_conflicts(text: str) -> list[dict]:
    conflicts = []
    for match in ROOM_IS.finditer(text):
        if match.group(1) == match.group(3):
            continue
        conflicts.append({
            "kind": "collapsed_layers",
            "name": f"{match.group(1)}/{match.group(3)}",
            "expected": "三层同时存在，不是同一间房",
            "found": match.group(0),
            "excerpt": _excerpt(text, match.start(), match.end()),
        })
        return conflicts
    for match in ROOM_AND_SAME.finditer(text):
        if match.group(1) == match.group(2):
            continue
        conflicts.append({
            "kind": "collapsed_layers",
            "name": f"{match.group(1)}/{match.group(2)}",
            "expected": "三层同时存在，不是同一间房",
            "found": match.group(0),
            "excerpt": _excerpt(text, match.start(), match.end()),
        })
        return conflicts
    for marker in MERGE_MARKERS:
        start = 0
        while True:
            index = text.find(marker, start)
            if index < 0:
                break
            window = text[max(0, index - 24):index + len(marker)]
            rooms = [name for name in OFFICIAL_ROOMS if name in window]
            if len(rooms) >= 2:
                conflicts.append({
                    "kind": "collapsed_layers",
                    "name": "/".join(rooms),
                    "expected": "三层同时存在，不是同一间房",
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
            "name": "灯塔",
            "expected": "只能保存、检索、展示",
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
            "name": "灯塔",
            "expected": "不能补全名字或末字",
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
