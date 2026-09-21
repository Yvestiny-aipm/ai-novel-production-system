"""Deterministic verification that a reviewed scene actually advances story state."""
from __future__ import annotations
import copy, json, time, uuid

ALGORITHM_VERSION = "progression_evidence_v3"
PROGRESS_TYPES = {"new_clue","character_state_change","relationship_change","conflict_change","decision_or_consequence","thread_opened","thread_advanced","thread_closed","goal_milestone"}
UNKNOWN = {"未知", "unknown", "尚未知", "不明"}
VAGUE = {"继续调查", "推进剧情", "继续推进", "发生一些事情", "调查", "没有新结果"}
NON_PROGRESS_WORDS = ("天气", "环境", "气氛", "情绪", "雨夜", "焦虑", "沮丧", "害怕")
SUBSTANTIVE_WORDS = ("发现", "确认", "决定", "获得", "交给", "烧毁", "背叛", "合作", "升级", "关闭", "打开", "获救", "死亡", "失踪地点", "求救录音")
TYPE_FIELDS = {
    "new_clue": ("events", "unresolved_threads"),
    "character_state_change": ("characters", "events"),
    "relationship_change": ("relationship_changes",),
    "conflict_change": ("events", "relationship_changes", "unresolved_threads"),
    "decision_or_consequence": ("events", "characters"),
    "thread_opened": ("unresolved_threads", "events"),
    "thread_advanced": ("unresolved_threads", "events"),
    "thread_closed": ("events", "unresolved_threads"),
    "goal_milestone": ("events",),
}
PROGRESSION_BASELINE_FIELDS = (
    "characters", "events", "relationship_changes", "unresolved_threads", "location", "time_context",
)
PLAN_BEFORE_STATE_FIELDS = {
    "new_clue": ("events", "unresolved_threads"),
    "character_state_change": ("characters", "events"),
    "relationship_change": ("relationship_changes",),
    "conflict_change": ("events", "relationship_changes", "unresolved_threads"),
    "decision_or_consequence": ("events", "characters"),
    "thread_advanced": ("unresolved_threads", "events"),
    "thread_closed": ("unresolved_threads", "events"),
    "goal_milestone": ("events",),
}
ALLOW_UNKNOWN_BEFORE = {"new_clue", "thread_opened"}
PLAN_BEFORE_STATE_REASON = "plan_before_state_conflicts_previous_scene"
SYNC_FIELDS = {
    "new_clue": "events",
    "character_state_change": "characters",
    "relationship_change": "relationship_changes",
    "conflict_change": "events",
    "decision_or_consequence": "events",
    "thread_opened": "unresolved_threads",
    "thread_advanced": "unresolved_threads",
    "thread_closed": "events",
    "goal_milestone": "events",
}

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",",":"))

def _texts(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _texts(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _texts(item)
    elif value is not None:
        yield str(value).strip()


def _has_value(value):
    return any(_texts(value))


def non_vague(value):
    texts = [text for text in _texts(value) if text]
    return bool(texts) and not all(text.lower() in VAGUE for text in texts)


def non_substantive(value):
    text = "".join(_texts(value)).replace(" ", "").lower()
    generic = ("继续调查", "再次询问同一个问题", "又问了同一个问题", "只换地点", "换到另一个房间")
    if not text or text in VAGUE or (any(phrase in text for phrase in generic) and not any(word in text for word in SUBSTANTIVE_WORDS)):
        return True
    return any(word in text for word in NON_PROGRESS_WORDS) and not any(word in text for word in SUBSTANTIVE_WORDS)

def validate_requirements(requirements):
    if not isinstance(requirements, list) or not requirements:
        raise ValueError("plan_progression_missing")
    for item in requirements:
        if not isinstance(item, dict) or item.get("progress_type") not in PROGRESS_TYPES:
            raise ValueError("plan_progression_missing")
        if any(key not in item for key in ("progress_type", "target_key", "before_state", "expected_after_state", "acceptance_criterion")):
            raise ValueError("plan_progression_missing")
        if not non_vague(item.get("target_key")) or not _has_value(item.get("before_state")):
            raise ValueError("plan_progression_missing")
        if not non_vague(item.get("expected_after_state")) or non_substantive(item.get("expected_after_state")) or not non_vague(item.get("acceptance_criterion")):
            raise ValueError("plan_progression_missing")
    return True


def progression_baseline_from_state(state):
    """Copy the confirmed previous-scene fields Planning must treat as literal before_state."""
    empty = {
        "characters": [], "events": [], "relationship_changes": [], "unresolved_threads": [],
        "location": "", "time_context": "",
    }
    if not isinstance(state, dict):
        return empty
    baseline = {}
    for field in PROGRESSION_BASELINE_FIELDS:
        baseline[field] = copy.deepcopy(state[field]) if field in state else empty[field]
    return baseline


def _baseline_from_input(input_payload):
    payload = input_payload if isinstance(input_payload, dict) else {}
    baseline = payload.get("progression_baseline")
    if isinstance(baseline, dict):
        return baseline
    pack = payload.get("context_pack") if isinstance(payload.get("context_pack"), dict) else {}
    previous = pack.get("previous_scene_state")
    return previous if isinstance(previous, dict) else {}


def _is_followup_scene(input_payload, baseline):
    payload = input_payload if isinstance(input_payload, dict) else {}
    number = payload.get("scene_number")
    if number is not None:
        try:
            return int(number) > 1
        except (TypeError, ValueError):
            pass
    return any(_has_value(baseline.get(field)) for field in PROGRESSION_BASELINE_FIELDS)


def _baseline_fields(baseline, fields):
    if not isinstance(baseline, dict):
        return []
    return [baseline.get(field) for field in fields]


def _existing_open_thread(item, baseline):
    threads = baseline.get("unresolved_threads") if isinstance(baseline, dict) else []
    for value in (item.get("before_state"), item.get("target_key"), item.get("expected_after_state")):
        if _unknown(value) or value in (None, "", {}, []):
            continue
        if contains_state(threads, value):
            return True
    return False


def _plan_before_state_item_conflict(item, baseline):
    if not isinstance(item, dict):
        return False
    progress_type = item.get("progress_type")
    before = item.get("before_state")
    if progress_type == "thread_opened":
        return _existing_open_thread(item, baseline) or not _unknown(before)
    if progress_type in ALLOW_UNKNOWN_BEFORE and _unknown(before):
        return False
    fields = PLAN_BEFORE_STATE_FIELDS.get(progress_type)
    if not fields:
        return False
    return _unknown(before) or not contains_state(_baseline_fields(baseline, fields), before)


def plan_before_state_conflict_reason(requirements, baseline):
    """Return the planning-quality reason when a before_state is not a literal previous-state copy."""
    if not isinstance(requirements, list):
        return None
    for item in requirements:
        if _plan_before_state_item_conflict(item, baseline):
            return PLAN_BEFORE_STATE_REASON
    return None


def plan_before_state_conflict_items(requirements, baseline):
    """List each failed progression_requirements item. Same gate as the reason string."""
    if not isinstance(requirements, list):
        return []
    items = []
    for item in requirements:
        if not _plan_before_state_item_conflict(item, baseline):
            continue
        progress_type = item.get("progress_type")
        items.append({
            "progress_type": progress_type,
            "before_state": item.get("before_state"),
            "allowed_fields": list(PLAN_BEFORE_STATE_FIELDS.get(progress_type) or ()),
        })
    return items


def validate_scene_plan_against_input(response, input_payload):
    """Follow-up ScenePlans must copy before_state from the previous confirmed baseline."""
    payload = response.get("payload") if isinstance(response, dict) else None
    if not isinstance(payload, dict):
        return
    baseline = _baseline_from_input(input_payload)
    if not _is_followup_scene(input_payload, baseline):
        return
    reason = plan_before_state_conflict_reason(payload.get("progression_requirements") or [], baseline)
    if reason:
        raise ValueError(reason)


def contains_state(container, expected):
    if expected in (None, "", {}, []):
        return True
    if isinstance(expected, dict):
        if isinstance(container, dict):
            return all(key in container and contains_state(container[key], value) for key, value in expected.items())
        return any(contains_state(item, expected) for item in container) if isinstance(container, list) else False
    if isinstance(expected, list):
        return all(contains_state(container, item) for item in expected)
    needle = str(expected).strip()
    return any(needle in text for text in _texts(container) if text)


def relevant_state(state, progress_type):
    if not isinstance(state, dict):
        return []
    return [state.get(field, []) for field in TYPE_FIELDS[progress_type]]


def _unknown(value):
    return isinstance(value, str) and value.strip().lower() in UNKNOWN


def verified_progression_record(progress_type, target_key, after_state, evidence_text):
    return {
        "progress_type": progress_type,
        "target_key": target_key,
        "state": after_state,
        "evidence_text": evidence_text or "",
        "source": "verified_progression",
    }


def _field_list(state, field):
    value = state.get(field)
    if isinstance(value, list):
        return value
    if value in (None, ""):
        state[field] = []
        return state[field]
    state[field] = [value]
    return state[field]


def _same_synced_record(item, record):
    if not isinstance(item, dict) or item.get("source") != "verified_progression":
        return False
    return (item.get("progress_type") == record["progress_type"]
            and item.get("target_key") == record["target_key"]
            and canonical(item.get("state")) == canonical(record["state"]))


def already_has_verified_state(state, record):
    field = SYNC_FIELDS.get(record["progress_type"])
    if not field or not isinstance(state, dict):
        return False
    return any(_same_synced_record(item, record) for item in _field_list(state, field))


def _remove_closed_thread(state, before_state):
    """Drop the open thread identified by before_state. after_state is the close result, not the match key."""
    threads = state.get("unresolved_threads")
    if not isinstance(threads, list) or before_state in (None, "", {}, []):
        return
    state["unresolved_threads"] = [
        thread for thread in threads
        if not contains_state(thread, before_state)
    ]


def is_location_or_time_only(after, accepted):
    """A location/time paraphrase is not a verified plot state worth syncing."""
    if not isinstance(accepted, dict) or after in (None, "", {}, []):
        return False
    in_place = contains_state(accepted.get("location"), after) or contains_state(accepted.get("time_context"), after)
    in_plot = any(contains_state(accepted.get(field), after) for field in
                  ("events", "characters", "relationship_changes", "unresolved_threads"))
    return in_place and not in_plot


def can_sync_missing_accepted_state(reason, after, accepted):
    return reason == "after_state_missing_from_accepted_scene_state" and not is_location_or_time_only(after, accepted)


def sync_verified_progression_state(accepted_scene_state, items):
    """Deep-copy scene_state and append verified after_state records. Never mutates the input."""
    copied = copy.deepcopy(accepted_scene_state) if isinstance(accepted_scene_state, dict) else {
        "characters": [], "location": "", "time_context": "", "events": [],
        "relationship_changes": [], "unresolved_threads": [],
    }
    synced = []
    for item in items:
        progress_type = item.get("progress_type")
        field = SYNC_FIELDS.get(progress_type)
        if not field:
            continue
        record = verified_progression_record(
            progress_type, item.get("target_key"), item.get("after_state"), item.get("evidence_text"),
        )
        bucket = _field_list(copied, field)
        if progress_type == "thread_closed":
            _remove_closed_thread(copied, item.get("before_state"))
        if already_has_verified_state(copied, record):
            continue
        bucket.append(record)
        synced.append(record)
    return copied, synced

def assessment_for(reviews):
    # The character/plot reviewer is authoritative for progression. A missing
    # assessment is a content failure, not a technical exception.
    for review in reviews:
        payload = review.get("payload", {})
        if payload.get("reviewer_role") == "character_plot":
            return payload.get("progression_assessment", {})
    return {}


def _cached_result(db, plan_id, draft_id, requirements):
    rows = db.execute("""select progress_type,target_key,before_state_json,actual_after_state_json,
        evidence_text,evidence_location,result,failure_reason from scene_progression_checks
        where plan_id=? and draft_id=? and algorithm_version=? order by created_at,check_id""",
        (plan_id, draft_id, ALGORITHM_VERSION)).fetchall()
    expected = [(item["progress_type"], item["target_key"]) for item in requirements]
    if [(row[0], row[1]) for row in rows] != expected:
        return None
    verified, missing = [], []
    for row in rows:
        item = {"progress_type": row[0], "target_key": row[1], "before_state": json.loads(row[2]),
                "after_state": json.loads(row[3]), "evidence_text": row[4], "evidence_location": row[5]}
        (verified if row[6] == "passed" else missing).append(item if row[6] == "passed" else {**item, "failure_reason": row[7]})
    return {"progression_status": "passed" if verified else "failed", "planned_progression_count": len(requirements),
            "achieved_progression_count": len(verified), "verified_progression_items": verified,
            "missing_progression_items": missing,
            "progression_failure_reason": None if verified else (missing[0]["failure_reason"] if missing else "planned_progression_not_achieved")}

def _record(db, *, book_id, chapter_id, scene_id, plan_id, draft_id, report_id, previous_scene_id,
            requirement, actual_after, evidence, location, verified, result, reason):
    existing = db.execute("""select check_id from scene_progression_checks where plan_id=? and draft_id=?
        and progress_type=? and target_key=? and algorithm_version=? order by created_at desc limit 1""",
        (plan_id,draft_id,requirement["progress_type"],requirement["target_key"],ALGORITHM_VERSION)).fetchone()
    if existing: return existing[0]
    db.execute("""insert into scene_progression_checks(check_id,book_id,chapter_id,scene_id,plan_id,draft_id,report_id,previous_scene_id,
        progress_type,target_key,before_state_json,expected_after_state_json,actual_after_state_json,evidence_text,evidence_location,
        evidence_verified,result,failure_reason,algorithm_version,created_at)
        values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("prog_"+uuid.uuid4().hex,book_id,chapter_id,scene_id,plan_id,draft_id,report_id,previous_scene_id,
         requirement["progress_type"],requirement["target_key"],canonical(requirement.get("before_state")),canonical(requirement.get("expected_after_state")),
         canonical(actual_after),evidence,location,int(verified),result,reason,ALGORITHM_VERSION,str(time.time())))
    db.commit()
    return None

def _assess_requirement(requirement, *, achieved, text, previous_scene_id, previous_book, book_id,
                        previous_state, accepted_scene_state):
    matches = [item for item in achieved if item.get("progress_type") == requirement["progress_type"] and item.get("target_key") == requirement["target_key"]]
    candidate = matches[0] if matches else {}
    evidence, location = candidate.get("evidence_text", ""), candidate.get("evidence_location", "")
    before, after = requirement.get("before_state"), candidate.get("after_state")
    previous_relevant = relevant_state(previous_state, requirement["progress_type"])
    accepted_relevant = relevant_state(accepted_scene_state, requirement["progress_type"])
    reason = None
    if previous_scene_id and previous_book != book_id: reason = "previous_scene_book_mismatch"
    elif not candidate: reason = "planned_progression_not_achieved"
    elif not isinstance(evidence, str) or not evidence.strip() or evidence not in text: reason = "progression_evidence_not_in_draft"
    elif not isinstance(location, str) or any(token in location.lower() for token in ("contextpack","context_pack","sceneplan","scene_plan")): reason = "progression_evidence_not_in_draft"
    elif non_substantive(after): reason = "non_substantive_progression"
    elif requirement["progress_type"] == "character_state_change" and after in (accepted_scene_state.get("characters") or []) and not contains_state(accepted_scene_state.get("events", []), after): reason = "non_substantive_progression"
    elif not _unknown(before) and canonical(candidate.get("before_state")) != canonical(before): reason = "before_state_conflicts_previous_scene"
    elif previous_state and not _unknown(before) and not contains_state(previous_relevant, before): reason = "before_state_conflicts_previous_scene"
    elif not contains_state(after, requirement.get("expected_after_state")): reason = "after_state_misses_planned_target"
    elif not contains_state(accepted_relevant, after): reason = "after_state_missing_from_accepted_scene_state"
    elif canonical(before) == canonical(after) or contains_state(previous_relevant, after): reason = "progression_reuses_previous_state"
    elif canonical(before) == canonical(requirement.get("expected_after_state")): reason = "plan_progression_missing"
    item = {"progress_type":requirement["progress_type"],"target_key":requirement["target_key"],"before_state":requirement.get("before_state"),
            "after_state":after,"evidence_text":evidence,"evidence_location":location}
    return reason, item, candidate


def verify_progression(db, *, book_id, chapter_id, scene_id, plan_id, draft_id, report_id, requirements,
                       reviews, text, previous_scene_id, previous_state, accepted_scene_state):
    validate_requirements(requirements)
    accepted = copy.deepcopy(accepted_scene_state) if isinstance(accepted_scene_state, dict) else {}
    cached = _cached_result(db, plan_id, draft_id, requirements)
    if cached:
        if cached["verified_progression_items"]:
            accepted, synced = sync_verified_progression_state(accepted, cached["verified_progression_items"])
        else:
            synced = []
        cached["accepted_scene_state"] = accepted
        cached["synced_progression_states"] = synced
        return cached
    assessment = assessment_for(reviews)
    achieved = assessment.get("achieved_items", []) if assessment.get("status") == "achieved" else []
    previous_book = None
    if previous_scene_id:
        row = db.execute("select book_id from scenes where scene_id=?", (previous_scene_id,)).fetchone()
        previous_book = row[0] if row else None

    def run_pass(state):
        return [
            _assess_requirement(
                requirement, achieved=achieved, text=text, previous_scene_id=previous_scene_id,
                previous_book=previous_book, book_id=book_id, previous_state=previous_state,
                accepted_scene_state=state,
            ) + (requirement,)
            for requirement in requirements
        ]

    first = run_pass(accepted)
    syncable = [item for reason, item, _candidate, _req in first if can_sync_missing_accepted_state(reason, item.get("after_state"), accepted)]
    synced = []
    if syncable:
        accepted, synced = sync_verified_progression_state(accepted, syncable)
        final = run_pass(accepted)
    else:
        final = first
    verified, missing = [], []
    for reason, item, candidate, requirement in final:
        ok = reason is None
        _record(db,book_id=book_id,chapter_id=chapter_id,scene_id=scene_id,plan_id=plan_id,draft_id=draft_id,report_id=report_id,
                previous_scene_id=previous_scene_id,requirement=requirement,actual_after=candidate.get("after_state"),
                evidence=item.get("evidence_text"),location=item.get("evidence_location"),
                verified=ok,result="passed" if ok else "failed",reason=reason)
        (verified if ok else missing).append(item if ok else {**item,"failure_reason":reason})
    return {"progression_status":"passed" if verified else "failed", "planned_progression_count":len(requirements),
            "achieved_progression_count":len(verified), "verified_progression_items":verified,
            "missing_progression_items":missing,
            "progression_failure_reason":None if verified else (missing[0]["failure_reason"] if missing else "planned_progression_not_achieved"),
            "accepted_scene_state": accepted, "synced_progression_states": synced}


def reviewer_findings_from_payload(payload):
    findings = []
    for item in (payload or {}).get("reviewer_results") or []:
        source = item.get("payload") if isinstance(item, dict) and isinstance(item.get("payload"), dict) else item
        if not isinstance(source, dict):
            continue
        findings.append({
            "reviewer_role": source.get("reviewer_role"),
            "result": source.get("result"),
            "issue_count": source.get("issue_count"),
            "severity": source.get("severity"),
            "impact_scope": source.get("impact_scope"),
            "findings": source.get("findings"),
            "suggestions": source.get("suggestions") or [],
        })
    return findings


def quality_revision_feedback(*, previous_draft_id, previous_text, plan_id, plan_version,
                              progression_failure_reason=None, planned_progression_requirements=None,
                              missing_progression_items=None, reviewer_findings=None,
                              progression_status=None, routing_recommendation=None):
    """Structured Writing rework input after a failed QualityReport."""
    missing = list(missing_progression_items or [])
    reason = progression_failure_reason
    if progression_status == "passed":
        missing = []
        reason = None
    return {
        "failure_type": "quality_report",
        "previous_draft_id": previous_draft_id,
        "previous_text": previous_text or "",
        "plan_id": plan_id,
        "plan_version": int(plan_version),
        "reviewer_findings": list(reviewer_findings or []),
        "progression_status": progression_status,
        "progression_failure_reason": reason,
        "missing_progression_items": missing,
        "planned_progression_requirements": planned_progression_requirements or [],
        "routing_recommendation": routing_recommendation,
        "instruction": "必须实际修改正文，禁止原样返回，禁止只改结构化字段或word_count",
        "evidence_requirement": "正文必须出现可逐字引用的证据",
        "accepted_state_requirement": "完成后的状态必须进入对应 scene_state 字段",
    }


PROGRESSION_RESULT_KEYS = (
    "progression_status", "planned_progression_count", "achieved_progression_count",
    "verified_progression_items", "missing_progression_items", "progression_failure_reason",
)


def apply_to_quality(quality, result):
    """Backend progression fields always overwrite any Arbiter or reviewer claim."""
    payload=quality["payload"]
    for key in PROGRESSION_RESULT_KEYS:
        if key in result:
            payload[key] = result[key]
    if result.get("accepted_scene_state") is not None:
        payload["accepted_scene_state"] = result["accepted_scene_state"]
    if result["progression_status"] == "failed":
        payload["status"]="failed"; payload["routing_recommendation"]="rewrite"
        payload["ordinary_issue_count"]=max(1, int(payload.get("ordinary_issue_count",0)))
    return quality
