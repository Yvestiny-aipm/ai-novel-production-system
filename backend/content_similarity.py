"""Local, deterministic same-book repetition checks (algorithm v1)."""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid

ALGORITHM_VERSION = "char_ngram_jaccard_v1"
NGRAM_SIZE = 3
OPENING_LENGTH = 120
OPENING_THRESHOLD = 0.72
BODY_THRESHOLD = 0.55
PLAN_GOAL_THRESHOLD = 0.80
PLAN_ACTION_THRESHOLD = 0.65
PLAN_OVERALL_THRESHOLD = 0.75
LOOKBACK_SCENES = 3

# Normalize punctuation and case only for comparison; original database text is
# never changed.  Names, locations, and all semantic content remain intact.
_PUNCTUATION = str.maketrans({
    "，": ",", "。": ".", "！": "!", "？": "?", "：": ":", "；": ";",
    "（": "(", "）": ")", "【": "[", "】": "]", "“": '"', "”": '"',
    "‘": "'", "’": "'", "、": ",", "—": "-", "–": "-", "…": ".",
})


def normalize_for_similarity(value: object) -> str:
    """Whitespace/punctuation/case normalization for deterministic comparison."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return re.sub(r"\s+", "", value.translate(_PUNCTUATION)).lower()


def character_ngrams(value: object, n: int = NGRAM_SIZE) -> set[str]:
    text = normalize_for_similarity(value)
    if not text:
        return set()
    if len(text) <= n:
        return {text}
    return {text[index:index + n] for index in range(len(text) - n + 1)}


def ngram_similarity(left: object, right: object, n: int = NGRAM_SIZE) -> float:
    a, b = character_ngrams(left, n), character_ngrams(right, n)
    if not a or not b:
        return 0.0
    return round(len(a & b) / len(a | b), 6)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _plan_text(payload: dict, key: str) -> str:
    value = payload.get(key, "")
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return str(value)


def plan_similarity(current: dict, compared: dict) -> dict:
    """Compare only narrative goal/action fields, never cast/location/time."""
    goal = ngram_similarity(_plan_text(current, "scene_goal"), _plan_text(compared, "scene_goal"))
    action = ngram_similarity(_plan_text(current, "action_beats"), _plan_text(compared, "action_beats"))
    combined_current = "\n".join(_plan_text(current, key) for key in ("scene_goal", "conflict", "action_beats", "must_happen"))
    combined_compared = "\n".join(_plan_text(compared, key) for key in ("scene_goal", "conflict", "action_beats", "must_happen"))
    overall = ngram_similarity(combined_current, combined_compared)
    failed = (goal >= PLAN_GOAL_THRESHOLD and action >= PLAN_ACTION_THRESHOLD) or overall >= PLAN_OVERALL_THRESHOLD
    return {"scene_goal": goal, "action_beats": action, "overall": overall, "failed": failed}


def _current_number(db, scene_id: str) -> int:
    row = db.execute("select scene_number from scenes where scene_id=?", (scene_id,)).fetchone()
    if row is None:
        raise ValueError("UNKNOWN_SCENE")
    return int(row[0])


def _confirmed_history(db, book_id: str, current_scene_id: str, *, limit: int = LOOKBACK_SCENES) -> list[dict]:
    """Latest approved draft/plan from prior completed scenes in this book only."""
    number = _current_number(db, current_scene_id)
    rows = db.execute("""
        select s.scene_id, s.scene_number, p.plan_id, p.payload_json,
               d.draft_id, d.draft_hash, d.text
          from scenes s
          join task_states t on t.scene_id=s.scene_id
          join quality_reports q on q.scene_id=s.scene_id and q.status='passed'
          join prose_drafts d on d.draft_id=q.draft_id
          join scene_plans p on p.scene_id=d.scene_id and p.plan_version=d.plan_version
         where s.book_id=? and s.scene_number<? and t.status='completed'
           and q.report_id=(select q2.report_id from quality_reports q2
                              join prose_drafts d2 on d2.draft_id=q2.draft_id
                             where q2.scene_id=s.scene_id and q2.status='passed'
                             order by d2.draft_version desc limit 1)
         order by s.scene_number desc
         limit ?
    """, (book_id, number, limit)).fetchall()
    return [{"scene_id": row[0], "scene_number": row[1], "plan_id": row[2],
             "plan": json.loads(row[3]), "draft_id": row[4],
             "draft_hash": row[5], "text": row[6]} for row in rows]


def _saved_check(db, *, book_id, current_scene_id, current_plan_id, current_draft_id,
                 compared_scene_id, compared_plan_id, compared_draft_id, check_type):
    return db.execute("""
        select check_id,similarity_score,threshold,result,failure_reason
          from content_similarity_checks
         where book_id=? and current_scene_id=? and current_plan_id is ? and current_draft_id is ?
           and compared_scene_id=? and compared_plan_id is ? and compared_draft_id is ?
           and check_type=? and algorithm_version=?
         order by created_at desc limit 1
    """, (book_id, current_scene_id, current_plan_id, current_draft_id,
          compared_scene_id, compared_plan_id, compared_draft_id, check_type, ALGORITHM_VERSION)).fetchone()


def _record(db, *, book_id, current_scene_id, current_plan_id=None, current_draft_id=None,
            compared_scene_id, compared_plan_id=None, compared_draft_id=None,
            check_type, score, threshold, failed, reason=None):
    existing = _saved_check(db, book_id=book_id, current_scene_id=current_scene_id,
                            current_plan_id=current_plan_id, current_draft_id=current_draft_id,
                            compared_scene_id=compared_scene_id, compared_plan_id=compared_plan_id,
                            compared_draft_id=compared_draft_id, check_type=check_type)
    if existing:
        return {"check_id": existing[0], "similarity_score": existing[1], "threshold": existing[2],
                "result": existing[3], "failure_reason": existing[4], "reused": True}
    check_id = "sim_" + uuid.uuid4().hex
    db.execute("""
        insert into content_similarity_checks(
            check_id,book_id,current_scene_id,current_plan_id,current_draft_id,
            compared_scene_id,compared_plan_id,compared_draft_id,check_type,
            algorithm_version,similarity_score,threshold,result,failure_reason,created_at)
        values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (check_id, book_id, current_scene_id, current_plan_id, current_draft_id,
          compared_scene_id, compared_plan_id, compared_draft_id, check_type,
          ALGORITHM_VERSION, score, threshold, "failed" if failed else "passed", reason, str(time.time())))
    db.commit()
    return {"check_id": check_id, "similarity_score": score, "threshold": threshold,
            "result": "failed" if failed else "passed", "failure_reason": reason, "reused": False}


def check_plan_repetition(db, *, book_id: str, current_scene_id: str, current_plan_id: str, payload: dict) -> dict:
    checks, failures = [], []
    for prior in _confirmed_history(db, book_id, current_scene_id):
        scores = plan_similarity(payload, prior["plan"])
        reason = json.dumps({"reason": "plan_repetition", **scores}, ensure_ascii=False) if scores["failed"] else None
        row = _record(db, book_id=book_id, current_scene_id=current_scene_id, current_plan_id=current_plan_id,
                      compared_scene_id=prior["scene_id"], compared_plan_id=prior["plan_id"],
                      check_type="plan", score=scores["overall"], threshold=PLAN_OVERALL_THRESHOLD,
                      failed=scores["failed"], reason=reason)
        item = {"compared_scene_id": prior["scene_id"], "check_type": "plan", "scores": scores, **row}
        checks.append(item)
        if scores["failed"]:
            failures.append(item)
    return {"status": "failed" if failures else "passed", "checks": checks, "failures": failures}


def _prior_same_scene_drafts(db, book_id: str, scene_id: str, draft_id: str) -> list[dict]:
    rows = db.execute("""
        select d.draft_id,d.text from prose_drafts d join scenes s on s.scene_id=d.scene_id
         where s.book_id=? and d.scene_id=? and d.draft_id<>? order by d.draft_version desc
    """, (book_id, scene_id, draft_id)).fetchall()
    return [{"scene_id": scene_id, "draft_id": row[0], "text": row[1]} for row in rows]


def check_draft_repetition(db, *, book_id: str, current_scene_id: str, current_draft_id: str, text: str) -> dict:
    """Compare a valid-length draft to confirmed prior scenes and prior revisions."""
    # Opening/body similarity is explicitly a cross-scene continuity check
    # against confirmed scenes.  Earlier revisions of this same scene only
    # participate in the existing exact-duplicate safety rule.
    candidates = [(candidate, True) for candidate in _confirmed_history(db, book_id, current_scene_id)]
    candidates.extend((candidate, False) for candidate in _prior_same_scene_drafts(db, book_id, current_scene_id, current_draft_id))
    seen, checks, failures = set(), [], []
    opening = normalize_for_similarity(text)[:OPENING_LENGTH]
    for prior, confirmed_scene in candidates:
        key = (prior["scene_id"], prior["draft_id"])
        if key in seen:
            continue
        seen.add(key)
        exact = content_hash(text) == content_hash(prior["text"])
        opening_score = ngram_similarity(opening, normalize_for_similarity(prior["text"])[:OPENING_LENGTH])
        body_score = ngram_similarity(text, prior["text"])
        checks_to_record = [("exact", 1.0 if exact else 0.0, 1.0, exact, "duplicate_draft_content" if exact else None)]
        if confirmed_scene:
            checks_to_record.extend([
                ("opening", opening_score, OPENING_THRESHOLD, opening_score >= OPENING_THRESHOLD, "opening_repetition" if opening_score >= OPENING_THRESHOLD else None),
                ("body", body_score, BODY_THRESHOLD, body_score >= BODY_THRESHOLD, "body_repetition" if body_score >= BODY_THRESHOLD else None),
            ])
        for check_type, score, threshold, failed, failure_reason in checks_to_record:
            row = _record(db, book_id=book_id, current_scene_id=current_scene_id, current_draft_id=current_draft_id,
                          compared_scene_id=prior["scene_id"], compared_draft_id=prior["draft_id"],
                          check_type=check_type, score=score, threshold=threshold, failed=failed, reason=failure_reason)
            item = {"compared_scene_id": prior["scene_id"], "compared_draft_id": prior["draft_id"],
                    "check_type": check_type, **row}
            checks.append(item)
            if failed:
                failures.append(item)
    return {"status": "failed" if failures else "passed", "checks": checks, "failures": failures}
