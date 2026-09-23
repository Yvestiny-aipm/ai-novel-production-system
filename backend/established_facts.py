"""Confirmed-event ledger for planning and writing, plus a closed-set negation gate."""
from __future__ import annotations

import json

ESTABLISHED_FACTS_VERSION = 1
ESTABLISHED_FACTS_RULE = "established_facts_v1"
ESTABLISHED_FACTS_REASON = "established_facts_conflict"
ESTABLISHED_FACTS_HEAD = 30
ESTABLISHED_FACTS_TAIL = 90
ESTABLISHED_FACTS_CAP = ESTABLISHED_FACTS_HEAD + ESTABLISHED_FACTS_TAIL
CHAPTER_SUMMARY_PER_CHAPTER_MAX = 2
CHAPTER_SUMMARY_LINE_CAP = 80
CHAPTER_SUMMARY_STUB_MIN = 20
CHAPTER_SUMMARY_CAP = 7200
ESTABLISHED_FACT_KEYS = ("scene_id", "scene_number", "text", "kind")
WORLD_STATE_KEYS = ("location", "time_context", "present", "offstage", "clocks", "measures", "day_relation")
WORLD_STATE_LIST_KEYS = ("present", "offstage", "clocks", "measures")
WORLD_STATE_RULE = "world_state_v1"
WORLD_STATE_REASON = "world_state_conflict"
MEASURE_LOOKAROUND = 16
OFFSTAGE_ARRIVAL_LOOKAHEAD = 12
MEASURE_UNCHANGED_MARKERS = tuple(sorted((
    "和昨日记住", "和昨天", "和昨日", "与昨天", "与昨日",
    "没有变", "未变", "分毫不差", "一样", "仍是",
), key=len, reverse=True))
SAME_DAY_YESTERDAY = tuple(sorted((
    "昨天新", "昨日新", "昨天刚", "昨日刚", "昨天上场", "昨日上场",
    "昨天打在", "昨日打在", "昨天量", "昨日量", "昨天露", "昨日露",
), key=len, reverse=True))
OFFSTAGE_ARRIVAL = tuple(sorted((
    "跟着来了", "跟着来", "也到了", "随行到", "走进来", "来到这里", "一起来了",
), key=len, reverse=True))
OFFSTAGE_MARKERS = tuple(sorted((
    "未登场",
    "不随行",
    "已留在",
    "未到场",
    "未上场",
    "不在场",
    "已离开",
    "仍在原处",
    "未同行",
    "没有到场",
), key=len, reverse=True))
CLOCK_HOURS = tuple("子丑寅卯辰巳午未申酉戌亥")
CLOCK_SUFFIXES = ("未到", "已过", "三刻", "二刻", "一刻", "正刻", "初刻")
CLOCK_PHRASES = tuple(sorted(
    [hour + "时" + suffix for hour in CLOCK_HOURS for suffix in CLOCK_SUFFIXES]
    + [hour + "时" for hour in CLOCK_HOURS],
    key=len, reverse=True,
))
MEASURE_AMOUNTS = ("一", "二", "两", "三", "四", "五", "六", "七", "八", "九", "十", "半")
MEASURE_UNITS = ("指", "拃", "步", "尺", "里")
MEASURE_SUFFIXES = ("多一点", "出头", "略多", "略少", "半")
MEASURE_PHRASES = tuple(sorted({
    amount + unit + suffix
    for amount in MEASURE_AMOUNTS
    for unit in MEASURE_UNITS
    for suffix in ("",) + MEASURE_SUFFIXES
}, key=len, reverse=True))
DAY_NEXT_MARKERS = tuple(sorted((
    "隔夜", "次日", "次夜", "翌日", "第二天", "相隔一日", "隔一日",
), key=len, reverse=True))
DAY_SAME_MARKERS = tuple(sorted((
    "同日", "同一天", "当日", "同一夜", "紧接上一场", "紧接上场",
), key=len, reverse=True))
ESTABLISHED_NEGATION_LOOKBEHIND = 8
ESTABLISHED_NEGATIONS = tuple(sorted((
    "从未进入",
    "从未进过",
    "从来没有进入",
    "从来没进入",
    "从来没进过",
    "从来没有进过",
    "一层也没进",
    "一层都没进",
    "一层也没进过",
    "一层都没进过",
    "从未见面",
    "从未见过",
    "从未现身",
    "从来没有见过",
    "从来没见过",
    "从来没有现身",
    "从来没现身",
    "均未进入",
    "仍未现身",
), key=len, reverse=True))
SCENE_SCOPED_MARKERS = ("本场", "此场", "这一场", "今日", "当天", "今晚", "今夜")
SCENE_ABSENCE_EXTRA = (
    "未跨门槛",
    "没有跨过门槛",
    "门槛未跨",
    "仍未跨门槛",
    "未跨过门槛",
    "本场未进入",
    "此场未进入",
    "这一场未进入",
    "仍未进入",
)
SCENE_STATE_LIST_FIELDS = ("characters", "events", "relationship_changes", "unresolved_threads")
SCENE_STATE_SCALAR_FIELDS = ("location", "time_context")
EMPTY_SCENE_STATE = {
    "characters": [],
    "events": [],
    "relationship_changes": [],
    "unresolved_threads": [],
    "location": "",
    "time_context": "",
}
IRREVERSIBLE_MARKERS = tuple(sorted((
    "进入",
    "进了",
    "走进",
    "踏入",
    "登上",
    "见到",
    "遇见",
    "相遇",
    "现身",
    "揭开封条",
    "打开木匣",
    "开了匣",
    "死去",
    "身亡",
), key=len, reverse=True))
IRREVERSIBLE_NEGATION = ("未", "不", "没", "非")
IRREVERSIBLE_LOOKBEHIND = 4


def established_facts_snapshot(*, version: int = ESTABLISHED_FACTS_VERSION, facts=None, chapter_summary="") -> dict:
    return {
        "canon_version": version,
        "rule": ESTABLISHED_FACTS_RULE,
        "facts": list(facts or []),
        "chapter_summary": chapter_summary or "",
    }


def established_facts_instruction() -> str:
    return (
        "已成立事实以 context_pack.established_facts 为准，这些是已经发生。"
        "previous_scene_state 与 progression_baseline 只是上场此刻，且已去掉未进入/未跨门槛/均未进入这类未发生表述。"
        "不得把此刻未发生抄成全书从未发生。"
        "kind=canon 是不可逆已发生，裁剪不会丢掉，不得写成从未发生。"
        "context_pack.chapter_summary 是被账本裁掉的中间已发生；已经发生，每章各留已发生的一句或首尾两句，细节不完整；不得写成从未发生，也不得发明摘要里没有的新结局。"
    )


def empty_world_state() -> dict:
    return {key: ([] if key in WORLD_STATE_LIST_KEYS else "") for key in WORLD_STATE_KEYS}


def world_state_instruction() -> str:
    return (
        "context_pack.world_state 是上场结束时的此刻。"
        "本场从这里接着写，不得把 offstage 写成跟着来了，"
        "clocks 里已有的时辰不得改成另一个时辰或另一个刻，"
        "measures 里已有的量记不得改成另一个数，"
        "day_relation=same_day 时不得把上场刚发生的事写成昨日/昨天，"
        "day_relation=next_day 时昨日可以指上场。"
        "已经发生仍以 established_facts / chapter_summary 为准。"
        "写反按内容失败。"
    )


def _is_offstage(text: str) -> bool:
    return any(marker in text for marker in OFFSTAGE_MARKERS)


def _field_strings(state, *keys):
    texts = []
    for key in keys:
        value = state.get(key)
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    texts.append(item)
    return texts


def _scan_phrases(text, phrases):
    hits = []
    index = 0
    while index < len(text):
        for phrase in phrases:
            if text.startswith(phrase, index):
                hits.append(phrase)
                index += len(phrase)
                break
        else:
            index += 1
    return hits


def _unique_phrases(texts, phrases):
    seen = set()
    found = []
    for text in texts:
        for hit in _scan_phrases(text, phrases):
            if hit in seen:
                continue
            seen.add(hit)
            found.append(hit)
    return found


def extract_world_clocks(state) -> list:
    return _unique_phrases(
        _field_strings(state, "time_context", "location", "events", "unresolved_threads"),
        CLOCK_PHRASES,
    )


def extract_world_measures(state) -> list:
    return _unique_phrases(
        _field_strings(state, "events", "unresolved_threads", "location"),
        MEASURE_PHRASES,
    )


def extract_day_relation(time_context) -> str:
    if not isinstance(time_context, str):
        return ""
    if any(marker in time_context for marker in DAY_NEXT_MARKERS):
        return "next_day"
    if any(marker in time_context for marker in DAY_SAME_MARKERS):
        return "same_day"
    return ""


def build_world_state(state=None) -> dict:
    world = empty_world_state()
    if not isinstance(state, dict):
        return world
    location = state.get("location")
    time_context = state.get("time_context")
    world["location"] = location if isinstance(location, str) else ""
    world["time_context"] = time_context if isinstance(time_context, str) else ""
    characters = state.get("characters")
    if isinstance(characters, list):
        for item in characters:
            if not isinstance(item, str):
                continue
            if _is_offstage(item):
                world["offstage"].append(item)
            else:
                world["present"].append(item)
    world["clocks"] = extract_world_clocks(state)
    world["measures"] = extract_world_measures(state)
    world["day_relation"] = extract_day_relation(world["time_context"])
    return world


def is_irreversible_fact(text) -> bool:
    if not isinstance(text, str) or is_scene_absence(text):
        return False
    if "提出" in text and "进入" in text:
        return False
    index = 0
    while index < len(text):
        for marker in IRREVERSIBLE_MARKERS:
            if text.startswith(marker, index):
                window = text[max(0, index - IRREVERSIBLE_LOOKBEHIND):index]
                if any(negation in window for negation in IRREVERSIBLE_NEGATION):
                    index += len(marker)
                    break
                return True
        else:
            index += 1
    return False


def is_scene_absence(text) -> bool:
    if not isinstance(text, str):
        return False
    return any(phrase in text for phrase in ESTABLISHED_NEGATIONS + SCENE_ABSENCE_EXTRA)


def present_scene_state(state) -> dict:
    if not isinstance(state, dict):
        return {field: (list(value) if isinstance(value, list) else value) for field, value in EMPTY_SCENE_STATE.items()}
    present = {}
    for field in SCENE_STATE_LIST_FIELDS:
        if field not in state:
            present[field] = []
            continue
        value = state[field]
        if not isinstance(value, list):
            present[field] = value
            continue
        present[field] = [
            item for item in value
            if not (isinstance(item, str) and is_scene_absence(item))
        ]
    for field in SCENE_STATE_SCALAR_FIELDS:
        if field not in state:
            present[field] = ""
            continue
        value = state[field]
        present[field] = "" if isinstance(value, str) and is_scene_absence(value) else value
    return present


def split_accepted_scene_state(state) -> dict:
    present = present_scene_state(state)
    absences = []
    if isinstance(state, dict):
        for field in SCENE_STATE_LIST_FIELDS:
            value = state.get(field)
            if not isinstance(value, list):
                continue
            for item in value:
                if isinstance(item, str) and is_scene_absence(item):
                    absences.append(item)
        for field in SCENE_STATE_SCALAR_FIELDS:
            value = state.get(field)
            if isinstance(value, str) and is_scene_absence(value):
                absences.append(value)
    return {"present": present, "absences": absences}


def trim_established_facts(facts: list) -> list:
    items = list(facts or [])
    event_indexes = [index for index, item in enumerate(items) if item.get("kind") != "canon"]
    if len(event_indexes) <= ESTABLISHED_FACTS_CAP:
        return items
    keep_events = set(event_indexes[:ESTABLISHED_FACTS_HEAD] + event_indexes[-ESTABLISHED_FACTS_TAIL:])
    return [
        item for index, item in enumerate(items)
        if item.get("kind") == "canon" or index in keep_events
    ]


def facts_from_scene_events(scene_id, scene_number, events, chapter_number=None) -> list[dict]:
    rows = []
    if not isinstance(events, list):
        return rows
    chapter = chapter_number if chapter_number not in (None, "") else scene_number
    for item in events:
        if not isinstance(item, str) or not item.strip() or is_scene_absence(item):
            continue
        rows.append({
            "scene_id": scene_id,
            "scene_number": scene_number,
            "text": item,
            "kind": "canon" if is_irreversible_fact(item) else "event",
            "chapter_number": chapter,
        })
    return rows


def _public_fact(item) -> dict:
    return {key: item[key] for key in ESTABLISHED_FACT_KEYS}


def _chapter_of(item):
    value = item.get("chapter_number")
    if value in (None, ""):
        value = item.get("scene_number")
    return 0 if value in (None, "") else value


def _clip_summary_segment(text: str, budget: int) -> str:
    if budget <= 0:
        return ""
    if len(text) <= budget:
        return text
    ellipsis = "…"
    remain = budget - len(ellipsis)
    if remain <= 0:
        return ellipsis[:budget]
    head = remain // 2
    tail = remain - head
    return text[:head] + ellipsis + text[-tail:]


def _chapter_kept_lines(texts):
    first = texts[0]
    if CHAPTER_SUMMARY_PER_CHAPTER_MAX < 2 or texts[-1] == first:
        return [first]
    return [first, texts[-1]]


def _render_chapter_summary(groups, line_cap) -> str:
    parts = []
    for chapter, texts in groups:
        body = "；".join(_chapter_kept_lines(texts))
        if len(body) > line_cap:
            body = _clip_summary_segment(body, line_cap)
        parts.append(f"第{chapter}章：" + body)
    return " / ".join(parts)


def chapter_summary_from_dropped(dropped) -> str:
    groups = []
    seen = {}
    for item in dropped or []:
        if item.get("kind") == "canon":
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text:
            continue
        chapter = _chapter_of(item)
        if chapter not in seen:
            seen[chapter] = []
            groups.append((chapter, seen[chapter]))
        seen[chapter].append(text)
    if not groups:
        return ""
    groups.sort(key=lambda pair: pair[0])
    line_cap = CHAPTER_SUMMARY_LINE_CAP
    joined = _render_chapter_summary(groups, line_cap)
    if len(joined) <= CHAPTER_SUMMARY_CAP:
        return joined
    while line_cap > CHAPTER_SUMMARY_STUB_MIN:
        scaled = max(CHAPTER_SUMMARY_STUB_MIN, line_cap * CHAPTER_SUMMARY_CAP // len(joined))
        if scaled >= line_cap:
            scaled = line_cap - 1
        line_cap = scaled
        joined = _render_chapter_summary(groups, line_cap)
        if len(joined) <= CHAPTER_SUMMARY_CAP:
            return joined
    return " / ".join(
        f"第{chapter}章：" + texts[0][:CHAPTER_SUMMARY_STUB_MIN]
        for chapter, texts in groups
    )


def build_established_facts(scenes, *, version: int = ESTABLISHED_FACTS_VERSION) -> dict:
    """scenes: [{scene_id, scene_number, events, chapter_number?}] already in book order."""
    facts = []
    seen = set()
    ordered = sorted(scenes or [], key=lambda item: (item.get("scene_number") or 0,))
    for scene in ordered:
        for fact in facts_from_scene_events(
            scene.get("scene_id"), scene.get("scene_number"), scene.get("events"),
            chapter_number=scene.get("chapter_number"),
        ):
            if fact["text"] in seen:
                continue
            seen.add(fact["text"])
            facts.append(fact)
    kept = trim_established_facts(facts)
    kept_ids = {id(item) for item in kept}
    dropped = [item for item in facts if id(item) not in kept_ids]
    return established_facts_snapshot(
        version=version,
        facts=[_public_fact(item) for item in kept],
        chapter_summary=chapter_summary_from_dropped(dropped),
    )


def _parse_events(blob):
    try:
        state = json.loads(blob or "{}")
    except json.JSONDecodeError:
        return []
    if not isinstance(state, dict):
        return []
    events = state.get("events")
    return events if isinstance(events, list) else []


def load_established_facts(db, *, book_id, before_scene_number, version: int = ESTABLISHED_FACTS_VERSION) -> dict:
    """Latest passed QualityReport per prior scene. No new table."""
    if not before_scene_number or before_scene_number <= 1:
        return established_facts_snapshot(version=version)
    rows = db.execute(
        """select s.scene_id, s.scene_number, c.chapter_number, q.accepted_scene_state_json, q.review_attempt, q.created_at
           from quality_reports q
           join scenes s on s.scene_id=q.scene_id
           join chapters c on c.chapter_id=s.chapter_id
           where q.book_id=? and q.status=? and s.scene_number>=1 and s.scene_number<?
           order by s.scene_number, q.review_attempt desc, q.created_at desc""",
        (book_id, "passed", before_scene_number),
    ).fetchall()
    latest = {}
    scenes = []
    for scene_id, scene_number, chapter_number, state_json, _attempt, _created in rows:
        if scene_id in latest:
            continue
        latest[scene_id] = True
        scenes.append({
            "scene_id": scene_id,
            "scene_number": scene_number,
            "chapter_number": chapter_number,
            "events": _parse_events(state_json),
        })
    scenes.sort(key=lambda item: item["scene_number"])
    return build_established_facts(scenes, version=version)


def _ledger_facts(established_facts) -> list:
    if not isinstance(established_facts, dict):
        return []
    facts = established_facts.get("facts")
    return facts if isinstance(facts, list) else []


def _excerpt(text: str, start: int, end: int) -> str:
    return text[max(0, start - 4):min(len(text), end + 12)]


def _scene_scoped(text: str, start: int) -> bool:
    window = text[max(0, start - ESTABLISHED_NEGATION_LOOKBEHIND):start]
    return any(marker in window for marker in SCENE_SCOPED_MARKERS)


def _first_negation_conflict(text: str) -> dict | None:
    index = 0
    while index < len(text):
        for phrase in ESTABLISHED_NEGATIONS:
            if text.startswith(phrase, index):
                if not _scene_scoped(text, index):
                    return {
                        "kind": "established_negation",
                        "found": phrase,
                        "excerpt": _excerpt(text, index, index + len(phrase)),
                    }
                index += len(phrase)
                break
        else:
            index += 1
    return None


def validate_established_facts(text, established_facts=None) -> dict:
    """Closed-set book-wide negation gate. Empty ledger always passes."""
    source = text if isinstance(text, str) else ""
    if not _ledger_facts(established_facts):
        return {
            "status": "passed",
            "reason": None,
            "rule": ESTABLISHED_FACTS_RULE,
            "conflicts": [],
        }
    conflict = _first_negation_conflict(source)
    if conflict:
        return {
            "status": "failed",
            "reason": ESTABLISHED_FACTS_REASON,
            "rule": ESTABLISHED_FACTS_RULE,
            "conflicts": [conflict],
        }
    return {
        "status": "passed",
        "reason": None,
        "rule": ESTABLISHED_FACTS_RULE,
        "conflicts": [],
    }


def _world_list(world_state, key):
    value = world_state.get(key) if isinstance(world_state, dict) else None
    return value if isinstance(value, list) else []


def _clock_hour(phrase: str) -> str:
    if len(phrase) >= 2 and phrase[0] in CLOCK_HOURS and phrase[1] == "时":
        return phrase[:2]
    return phrase


def _scan_phrase_hits(text, phrases):
    hits = []
    index = 0
    while index < len(text):
        for phrase in phrases:
            if text.startswith(phrase, index):
                hits.append((index, phrase))
                index += len(phrase)
                break
        else:
            index += 1
    return hits


def _world_conflict(kind, text, start, found):
    return {
        "kind": kind,
        "found": found,
        "excerpt": _excerpt(text, start, start + len(found)),
    }


def _clock_rewrite_conflict(text, clocks):
    if not clocks:
        return None
    known = set(clocks)
    hours = {_clock_hour(item) for item in clocks if isinstance(item, str)}
    for start, phrase in _scan_phrase_hits(text, CLOCK_PHRASES):
        if phrase in known:
            continue
        if _clock_hour(phrase) in hours:
            return _world_conflict("clock_rewrite", text, start, phrase)
    return None


def _measure_rewrite_conflict(text, measures):
    if not measures:
        return None
    known = set(measures)
    for start, phrase in _scan_phrase_hits(text, MEASURE_PHRASES):
        if phrase in known:
            continue
        window = text[max(0, start - MEASURE_LOOKAROUND):min(len(text), start + len(phrase) + MEASURE_LOOKAROUND)]
        if any(marker in window for marker in MEASURE_UNCHANGED_MARKERS):
            return _world_conflict("measure_rewrite", text, start, phrase)
    return None


def _same_day_yesterday_conflict(text, day_relation):
    if day_relation != "same_day":
        return None
    for start, phrase in _scan_phrase_hits(text, SAME_DAY_YESTERDAY):
        return _world_conflict("same_day_yesterday", text, start, phrase)
    return None


def _offstage_name(item):
    if not isinstance(item, str):
        return None
    marks = [(item.find(sep), sep) for sep in ("：", ":") if sep in item]
    if not marks:
        return None
    index = min(pos for pos, _sep in marks)
    name = item[:index].strip()
    if 1 <= len(name) <= 4:
        return name
    return None


def _offstage_arrival_conflict(text, offstage):
    for item in offstage:
        name = _offstage_name(item)
        if not name:
            continue
        start = 0
        while True:
            index = text.find(name, start)
            if index < 0:
                break
            window = text[index + len(name):index + len(name) + OFFSTAGE_ARRIVAL_LOOKAHEAD]
            for arrival in OFFSTAGE_ARRIVAL:
                found_at = window.find(arrival)
                if found_at >= 0:
                    return _world_conflict("offstage_arrival", text, index + len(name) + found_at, arrival)
            start = index + len(name)
    return None


def validate_world_state(text, world_state=None) -> dict:
    """Closed-set now-state gate. Empty first-scene world always passes."""
    source = text if isinstance(text, str) else ""
    if not isinstance(world_state, dict):
        return {
            "status": "passed",
            "reason": None,
            "rule": WORLD_STATE_RULE,
            "conflicts": [],
        }
    clocks = _world_list(world_state, "clocks")
    measures = _world_list(world_state, "measures")
    offstage = _world_list(world_state, "offstage")
    day_relation = world_state.get("day_relation") if isinstance(world_state.get("day_relation"), str) else ""
    if not clocks and not measures and not offstage and day_relation != "same_day":
        return {
            "status": "passed",
            "reason": None,
            "rule": WORLD_STATE_RULE,
            "conflicts": [],
        }
    conflict = (
        _clock_rewrite_conflict(source, clocks)
        or _measure_rewrite_conflict(source, measures)
        or _same_day_yesterday_conflict(source, day_relation)
        or _offstage_arrival_conflict(source, offstage)
    )
    if conflict:
        return {
            "status": "failed",
            "reason": WORLD_STATE_REASON,
            "rule": WORLD_STATE_RULE,
            "conflicts": [conflict],
        }
    return {
        "status": "passed",
        "reason": None,
        "rule": WORLD_STATE_RULE,
        "conflicts": [],
    }
