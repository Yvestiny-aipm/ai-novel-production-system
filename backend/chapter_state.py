"""Chapter destination signals for planning. Seen, not a gate."""
from __future__ import annotations

import json

CHAPTER_STATE_KEYS = (
    "chapter_number",
    "scene_in_chapter",
    "scenes_in_chapter",
    "is_chapter_open",
    "is_chapter_close",
    "destination",
    "previous_destination",
    "previous_end_location",
)


def empty_chapter_state() -> dict:
    return {
        "chapter_number": 0,
        "scene_in_chapter": 0,
        "scenes_in_chapter": 0,
        "is_chapter_open": False,
        "is_chapter_close": False,
        "destination": "",
        "previous_destination": "",
        "previous_end_location": "",
    }


def chapter_state_instruction() -> str:
    return (
        "context_pack.chapter_state 是本章要到哪，不是新门栏。"
        "is_chapter_open 时，payload 必须写 chapter_destination：本章结束时要到达的具体去向，或要打开/关闭的一条悬念，不能只写继续调查。"
        "不得照抄 previous_destination。"
        "不得把终点只写成在 previous_end_location 再等一次、再复核同一处。"
        "is_chapter_open 为假且 destination 非空时，本场必须朝 destination 推进。"
        "is_chapter_close 时本场应抵达该去向，或写下尚未抵达的明确缺口，不得另起一条与 destination 无关的微观察。"
        "previous_destination 是上一章已经立过的终点，本章不得原地重复。"
        "已经发生仍以 established_facts / chapter_summary 为准。"
        "此刻仍以 world_state 为准。"
        "节奏信号仍以 pacing_state 为准。"
    )


def build_chapter_state(raw=None) -> dict:
    empty = empty_chapter_state()
    if not isinstance(raw, dict):
        return empty
    out = dict(empty)
    for key in CHAPTER_STATE_KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if key in ("chapter_number", "scene_in_chapter", "scenes_in_chapter"):
            if isinstance(value, int) and not isinstance(value, bool):
                out[key] = value
        elif key in ("is_chapter_open", "is_chapter_close"):
            if isinstance(value, bool):
                out[key] = value
        elif isinstance(value, str):
            out[key] = value
    return out


def _parse_json(blob):
    try:
        value = json.loads(blob or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _unwrap_plan(payload):
    inner = payload.get("payload")
    return inner if isinstance(inner, dict) else payload


def _latest_chapter_destination(db, scene_id) -> str:
    rows = db.execute(
        "select payload_json from scene_plans where scene_id=? order by plan_version desc",
        (scene_id,),
    ).fetchall()
    if not rows:
        return ""
    payload = _unwrap_plan(_parse_json(rows[0][0]))
    destination = payload.get("chapter_destination")
    return destination if isinstance(destination, str) else ""


def _passed_location(db, scene_id) -> str:
    rows = db.execute(
        """select accepted_scene_state_json, review_attempt, created_at
           from quality_reports
           where scene_id=? and status=?
           order by review_attempt desc, created_at desc""",
        (scene_id, "passed"),
    ).fetchall()
    if not rows:
        return ""
    location = _parse_json(rows[0][0]).get("location")
    return location if isinstance(location, str) else ""


def _previous_end_location(db, chapter_id) -> str:
    rows = db.execute(
        """select s.scene_id
           from scenes s
           join quality_reports q on q.scene_id=s.scene_id and q.status=?
           where s.chapter_id=?
           order by s.scene_number desc""",
        ("passed", chapter_id),
    ).fetchall()
    if not rows:
        return ""
    return _passed_location(db, rows[0][0])


def load_chapter_context(db, book_id, scene_id) -> dict:
    empty = empty_chapter_state()
    if not db or not scene_id:
        return empty
    try:
        row = db.execute(
            "select chapter_id from scenes where scene_id=?",
            (scene_id,),
        ).fetchone()
    except Exception:
        return empty
    if not row:
        return empty
    chapter_id = row[0]
    try:
        chapter_row = db.execute(
            "select chapter_number from chapters where chapter_id=?",
            (chapter_id,),
        ).fetchone()
    except Exception:
        chapter_row = None
    chapter_number = chapter_row[0] if chapter_row and isinstance(chapter_row[0], int) else 0
    try:
        scenes = db.execute(
            "select scene_id from scenes where chapter_id=? order by scene_number",
            (chapter_id,),
        ).fetchall()
    except Exception:
        return empty
    ids = [item[0] for item in scenes]
    if scene_id not in ids:
        return empty
    position = ids.index(scene_id) + 1
    count = len(ids)
    is_open = position == 1
    is_close = position == count
    destination = ""
    if not is_open and ids:
        try:
            destination = _latest_chapter_destination(db, ids[0])
        except Exception:
            destination = ""
    previous_destination = ""
    previous_end_location = ""
    if chapter_number > 1 and book_id:
        try:
            previous = db.execute(
                "select chapter_id from chapters where book_id=? and chapter_number=?",
                (book_id, chapter_number - 1),
            ).fetchone()
        except Exception:
            previous = None
        if previous:
            previous_chapter_id = previous[0]
            try:
                previous_scenes = db.execute(
                    "select scene_id from scenes where chapter_id=? order by scene_number",
                    (previous_chapter_id,),
                ).fetchall()
            except Exception:
                previous_scenes = []
            if previous_scenes:
                try:
                    previous_destination = _latest_chapter_destination(db, previous_scenes[0][0])
                except Exception:
                    previous_destination = ""
            try:
                previous_end_location = _previous_end_location(db, previous_chapter_id)
            except Exception:
                previous_end_location = ""
    return {
        "chapter_number": chapter_number,
        "scene_in_chapter": position,
        "scenes_in_chapter": count,
        "is_chapter_open": is_open,
        "is_chapter_close": is_close,
        "destination": destination,
        "previous_destination": previous_destination,
        "previous_end_location": previous_end_location,
    }
