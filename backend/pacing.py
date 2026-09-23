"""Recent-scene pacing signals for planning. Seen, not a gate."""
from __future__ import annotations

import json

PACING_STATE_KEYS = (
    "same_location_run", "recent_locations", "recent_goals", "stall_markers", "prior_locations",
)
PACING_LOOKBACK = 12
PACING_RECENT_WINDOW = 6
PACING_PRIOR_CAP = 8
STALL_MARKERS = tuple(sorted((
    "原路返回",
    "继续观察",
    "不离开",
    "等下次",
    "下一次",
    "安全位置",
    "整理记录",
    "等待",
    "复查",
    "复核",
    "留在",
    "不下",
), key=len, reverse=True))
ARRIVAL_MARKERS = tuple(sorted((
    "转到",
    "回到",
    "来到",
    "走到",
    "进入",
    "走进",
    "前往",
    "抵达",
    "去到",
    "去了",
), key=len, reverse=True))


def empty_pacing_state() -> dict:
    return {
        "same_location_run": 0,
        "recent_locations": [],
        "recent_goals": [],
        "stall_markers": [],
        "prior_locations": [],
    }


def pacing_state_instruction() -> str:
    return (
        "context_pack.pacing_state 是最近已完成场的节奏信号，不是新门栏。"
        "same_location_run 是连续停在同一处的已完成场数。"
        "按落脚点计算；行程句里的出发地不算仍停在原处。"
        "recent_locations / recent_goals 是最近几场原文。"
        "stall_markers 是这些目标里出现的等待、复查、留在、不下这类词。"
        "prior_locations 是已经去过、但不是此刻这一处的地点。"
        "same_location_run 达到 4 且 stall_markers 非空时，本场不得只靠再等一次、再复核同一处、再留在原处推进；"
        "必须换到 prior_locations 里的一处，或推进 previous_scene_state.unresolved_threads 里一条尚未关闭的悬念，且不能只改同一处的局部观察。"
        "same_location_run 不足 4 时可以留在原处，但必须有新的去向、决定或打开/关闭悬念。"
        "已经发生仍以 established_facts / chapter_summary 为准。"
        "此刻仍以 world_state 为准。"
    )


def location_core(text) -> str:
    if not isinstance(text, str):
        return ""
    return text.split("；", 1)[0].strip()


def location_anchor(text) -> str:
    core = location_core(text)
    if not core:
        return ""
    last_pos = -1
    last_len = 0
    for marker in ARRIVAL_MARKERS:
        pos = core.rfind(marker)
        if pos < 0:
            continue
        if pos > last_pos or (pos == last_pos and len(marker) > last_len):
            last_pos = pos
            last_len = len(marker)
    if last_pos < 0:
        return core
    after = core[last_pos + last_len:]
    cut = len(after)
    for sep in ("，", "。", "、"):
        idx = after.find(sep)
        if 0 <= idx < cut:
            cut = idx
    after = after[:cut].strip()
    if len(after) >= 2:
        return after
    return core


def _longest_common_substring(left: str, right: str) -> int:
    if not left or not right:
        return 0
    best = 0
    table = [[0] * (len(right) + 1) for _ in range(len(left) + 1)]
    for i, char in enumerate(left, 1):
        for j, other in enumerate(right, 1):
            if char != other:
                continue
            table[i][j] = table[i - 1][j - 1] + 1
            if table[i][j] > best:
                best = table[i][j]
    return best


def locations_same(left, right) -> bool:
    left_anchor = location_anchor(left)
    right_anchor = location_anchor(right)
    if not left_anchor or not right_anchor:
        return False
    shorter, longer = (left_anchor, right_anchor) if len(left_anchor) <= len(right_anchor) else (right_anchor, left_anchor)
    if shorter in longer and len(shorter) >= 4:
        return True
    return _longest_common_substring(left_anchor, right_anchor) >= 4


def _as_text(value) -> str:
    return value if isinstance(value, str) else ""


def _string_items(value) -> list:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _stall_markers(recent: list) -> list:
    found = []
    seen = set()
    for item in recent:
        texts = _string_items(item.get("scene_goal")) + _string_items(item.get("must_happen"))
        for text in texts:
            for marker in STALL_MARKERS:
                if marker in text and marker not in seen:
                    seen.add(marker)
                    found.append(marker)
    return found


def _same_location_run(recent: list) -> int:
    if not recent:
        return 0
    last = recent[-1].get("location")
    if not location_core(last):
        return 0
    run = 0
    for item in reversed(recent):
        if not locations_same(item.get("location"), last):
            break
        run += 1
    return run


def _prior_locations(recent: list, run: int, last_location) -> list:
    prefix = recent[:-run] if run else recent
    found = []
    seen = set()
    for item in prefix:
        location = item.get("location")
        if not isinstance(location, str) or not location or location in seen:
            continue
        if locations_same(location, last_location):
            continue
        seen.add(location)
        found.append(location)
        if len(found) >= PACING_PRIOR_CAP:
            break
    return found


def build_pacing_state(recent=None) -> dict:
    empty = empty_pacing_state()
    if not isinstance(recent, list):
        return empty
    items = [item for item in recent if isinstance(item, dict)]
    run = _same_location_run(items)
    window = items[-PACING_RECENT_WINDOW:]
    last_location = items[-1].get("location") if items else ""
    return {
        "same_location_run": run,
        "recent_locations": [_as_text(item.get("location")) for item in window],
        "recent_goals": [_as_text(item.get("scene_goal")) for item in window],
        "stall_markers": _stall_markers(items),
        "prior_locations": _prior_locations(items, run, last_location),
    }


def _parse_json(blob):
    try:
        value = json.loads(blob or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _passed_location(db, scene_id) -> str | None:
    rows = db.execute(
        """select accepted_scene_state_json, review_attempt, created_at
           from quality_reports
           where scene_id=? and status=?
           order by review_attempt desc, created_at desc""",
        (scene_id, "passed"),
    ).fetchall()
    if not rows:
        return None
    state = _parse_json(rows[0][0])
    location = state.get("location")
    return location if isinstance(location, str) else ""


def _latest_plan_goals(db, scene_id) -> tuple:
    rows = db.execute(
        """select payload_json from scene_plans
           where scene_id=? order by plan_version desc""",
        (scene_id,),
    ).fetchall()
    if not rows:
        return "", []
    payload = _parse_json(rows[0][0])
    if isinstance(payload.get("payload"), dict):
        payload = payload["payload"]
    goal = payload.get("scene_goal")
    must = payload.get("must_happen")
    return (goal if isinstance(goal, str) else ""), must


def load_pacing_recent(db, *, book_id, before_scene_number, limit: int = PACING_LOOKBACK) -> list:
    if not db or not before_scene_number or before_scene_number <= 1:
        return []
    try:
        rows = db.execute(
            """select s.scene_id, s.scene_number
               from scenes s
               join task_states t on t.scene_id=s.scene_id
               join quality_reports q on q.scene_id=s.scene_id and q.status=?
               where s.book_id=? and t.status=? and s.scene_number>=1 and s.scene_number<?
               order by s.scene_number""",
            ("passed", book_id, "completed", before_scene_number),
        ).fetchall()
    except Exception:
        return []
    seen = {}
    ordered = []
    for scene_id, number in rows:
        if scene_id in seen:
            continue
        seen[scene_id] = True
        ordered.append((scene_id, number))
    recent = []
    for scene_id, _number in ordered[-limit:]:
        try:
            location = _passed_location(db, scene_id)
        except Exception:
            return []
        if location is None:
            continue
        try:
            goal, must = _latest_plan_goals(db, scene_id)
        except Exception:
            goal, must = "", []
        recent.append({"location": location, "scene_goal": goal, "must_happen": must})
    return recent
