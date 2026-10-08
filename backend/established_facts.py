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
    "same as yesterday", "as yesterday", "unchanged", "exactly the same",
    "still the same", "has not changed",
), key=len, reverse=True))
SAME_DAY_YESTERDAY = tuple(sorted((
    "yesterday just", "yesterday's new", "just yesterday", "yesterday newly",
), key=len, reverse=True))
OFFSTAGE_ARRIVAL = tuple(sorted((
    "came with her", "showed up here", "walked in", "came along", "arrived here",
), key=len, reverse=True))
OFFSTAGE_MARKERS = tuple(sorted((
    "not onstage",
    "did not come",
    "stayed behind",
    "already left",
    "did not follow",
    "not present",
    "has not arrived",
    "remained behind",
    "did not come along",
    "was not there",
), key=len, reverse=True))
CLOCK_HOUR_NUMS = tuple(str(i) for i in range(1, 13))
CLOCK_HOUR_WORDS = ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve")
CLOCK_PHRASES = tuple(sorted(
    [f"{hour} o'clock" for hour in CLOCK_HOUR_NUMS + CLOCK_HOUR_WORDS]
    + [f"{hour} a.m." for hour in CLOCK_HOUR_NUMS]
    + [f"{hour} p.m." for hour in CLOCK_HOUR_NUMS]
    + ["midnight", "noon", "a.m.", "p.m.", "o'clock"],
    key=len, reverse=True,
))
MEASURE_PHRASES = tuple(sorted((
    "three steps", "two steps", "one step", "a step",
    "two spans", "one span", "a span",
    "two fingers", "one finger", "a finger",
), key=len, reverse=True))
DAY_NEXT_MARKERS = tuple(sorted((
    "the next day", "next night", "a day later", "next day", "overnight",
), key=len, reverse=True))
DAY_SAME_MARKERS = tuple(sorted((
    "the same day", "that same day", "same night", "same day",
    "right after the last scene",
), key=len, reverse=True))
ESTABLISHED_NEGATION_LOOKBEHIND = 16
ESTABLISHED_NEGATIONS = tuple(sorted((
    "still has not appeared",
    "has never appeared",
    "has never entered",
    "had never entered",
    "has never shown",
    "has never met",
    "never went in",
    "never entered",
    "never appeared",
    "never met",
), key=len, reverse=True))
SCENE_SCOPED_MARKERS = ("this scene", "tonight", "today", "this night")
SCENE_ABSENCE_EXTRA = (
    "did not cross the threshold",
    "has not crossed the threshold",
    "this scene did not enter",
    "still has not entered",
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
    "walked into",
    "stepped into",
    "opened the case",
    "opened the box",
    "climbed to",
    "went in",
    "entered",
    "appeared",
    "encountered",
    "met ",
    "died",
    "was killed",
), key=len, reverse=True))
IRREVERSIBLE_NEGATION = ("not ", "never ", "no ", "n't")
IRREVERSIBLE_LOOKBEHIND = 8


def established_facts_snapshot(*, version: int = ESTABLISHED_FACTS_VERSION, facts=None, chapter_summary="") -> dict:
    return {
        "canon_version": version,
        "rule": ESTABLISHED_FACTS_RULE,
        "facts": list(facts or []),
        "chapter_summary": chapter_summary or "",
    }


def established_facts_instruction() -> str:
    return (
        "Established facts are context_pack.established_facts. These already happened."
        "previous_scene_state and progression_baseline are only the last scene's now-state, with never-entered / did-not-cross-the-threshold phrasing already removed."
        "Do not copy a now-state absence as a book-wide never-happened."
        "kind=canon is irreversible and already happened; trim will not drop it; do not write it as never happened."
        "context_pack.chapter_summary is mid-book events dropped from the ledger; they already happened; each chapter keeps one or two sentences; details are incomplete; do not write them as never happened, and do not invent an ending the summary does not have."
    )


def empty_world_state() -> dict:
    return {key: ([] if key in WORLD_STATE_LIST_KEYS else "") for key in WORLD_STATE_KEYS}


def world_state_instruction() -> str:
    return (
        "context_pack.world_state is the now-state at the end of the last scene."
        "Continue this scene from here. Do not write an offstage person as having walked in. "
        "Do not change a clock already in clocks to another hour or another phrase for the same hour. "
        "Do not change a measure already in measures to another number. "
        "When day_relation=same_day, do not write something that just happened last scene as yesterday just / yesterday's new. "
        "When day_relation=next_day, yesterday may refer to the last scene. "
        "What already happened still follows established_facts / chapter_summary. "
        "Writing this backwards is a content failure."
    )


def _is_offstage(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in OFFSTAGE_MARKERS)


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
    source = text.lower()
    index = 0
    while index < len(source):
        for phrase in phrases:
            if source.startswith(phrase, index):
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
    low = time_context.lower()
    if any(marker in low for marker in DAY_NEXT_MARKERS):
        return "next_day"
    if any(marker in low for marker in DAY_SAME_MARKERS):
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
    source = text.lower()
    if "proposed" in source and "enter" in source:
        return False
    index = 0
    while index < len(source):
        for marker in IRREVERSIBLE_MARKERS:
            if source.startswith(marker, index):
                window = source[max(0, index - IRREVERSIBLE_LOOKBEHIND):index]
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
    low = text.lower()
    return any(phrase in low for phrase in ESTABLISHED_NEGATIONS + SCENE_ABSENCE_EXTRA)


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
        parts.append(f"Chapter {chapter}: " + body)
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
        f"Chapter {chapter}: " + texts[0][:CHAPTER_SUMMARY_STUB_MIN]
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
    window = text[max(0, start - ESTABLISHED_NEGATION_LOOKBEHIND):start].lower()
    return any(marker in window for marker in SCENE_SCOPED_MARKERS)


def _first_negation_conflict(text: str) -> dict | None:
    source = text.lower()
    index = 0
    while index < len(source):
        for phrase in ESTABLISHED_NEGATIONS:
            if source.startswith(phrase, index):
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
    if not isinstance(phrase, str):
        return ""
    low = phrase.lower().strip()
    if low in ("noon", "midnight"):
        return low
    for hour in list(CLOCK_HOUR_NUMS) + list(CLOCK_HOUR_WORDS):
        if low.startswith(hour + " "):
            return hour
    return low


def _scan_phrase_hits(text, phrases):
    hits = []
    source = text.lower()
    index = 0
    while index < len(source):
        for phrase in phrases:
            if source.startswith(phrase, index):
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
    words = name.split()
    if 1 <= len(words) <= 4 and 2 <= len(name) <= 32:
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
            window = text[index + len(name):index + len(name) + OFFSTAGE_ARRIVAL_LOOKAHEAD].lower()
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
