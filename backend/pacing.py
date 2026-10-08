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
    "keep watching",
    "do not leave",
    "wait next",
    "next time",
    "safe place",
    "sort records",
    "recheck",
    "remain",
    "return",
    "review",
    "stay",
    "wait",
), key=len, reverse=True))
ARRIVAL_MARKERS = tuple(sorted((
    "returned to",
    "walked to",
    "headed to",
    "went to",
    "come to",
    "came to",
    "go to",
    "return to",
    "walk to",
    "head to",
    "entered",
    "arrived",
    "reached",
    "enter",
    "arrive",
    "reach",
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
        "context_pack.pacing_state is a pacing signal from recently completed scenes, not a new gate."
        "same_location_run is the count of consecutive completed scenes that stayed in the same place."
        "It is computed from the arrival point; a departure place in a travel sentence does not count as still staying."
        "recent_locations / recent_goals are the original recent-scene strings."
        "stall_markers are wait / recheck / remain / stay words found in those goals."
        "prior_locations are places already visited that are not this place now."
        "When same_location_run reaches 4 and stall_markers is not empty, this scene must not advance only by waiting again, rechecking the same place, or remaining there; "
        "it must move to one of prior_locations, or advance one still-open thread in previous_scene_state.unresolved_threads, and must not only change a local observation of the same place."
        "When same_location_run is under 4, staying is allowed, but there must be a new destination, decision, or an opened/closed thread."
        "What already happened still follows established_facts / chapter_summary."
        "The now-state still follows world_state."
    )


def location_core(text) -> str:
    if not isinstance(text, str):
        return ""
    return text.replace(";", "；").split("；", 1)[0].strip()


def location_anchor(text) -> str:
    core = location_core(text)
    if not core:
        return ""
    last_pos = -1
    last_len = 0
    core_l = core.lower()
    for marker in ARRIVAL_MARKERS:
        pos = core_l.rfind(marker)
        if pos < 0:
            continue
        if pos > last_pos or (pos == last_pos and len(marker) > last_len):
            last_pos = pos
            last_len = len(marker)
    if last_pos < 0:
        return core
    after = core[last_pos + last_len:]
    cut = len(after)
    for sep in ("，", "。", "、", ",", "."):
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
            low = text.lower()
            for marker in STALL_MARKERS:
                if marker in low and marker not in seen:
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
