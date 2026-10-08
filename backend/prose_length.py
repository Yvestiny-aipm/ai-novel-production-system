"""Authoritative prose-length measurement and validation.

Official count is English words via whitespace split. Column names
word_count and actual_character_count are historical; stored values
are word counts. The model's self-report is audit data only.
"""
from __future__ import annotations

MIN_CHARACTER_COUNT = 1000
MAX_CHARACTER_COUNT = 1500
MAX_LENGTH_FAILURES_IN_PLAN = 4
LENGTH_FAILURE_REASONS = frozenset({"empty_text", "under_length", "over_length"})
DEFAULT_TARGET_WORD_COUNT = 1250
PREFERRED_SOFT_MIN = 1200
PREFERRED_SOFT_MAX = 1350
WRITING_PROMPT_VERSION = "prose_quality_v9"


def actual_word_count(text: str | None) -> int:
    """Official count: whitespace-split English words. don't / it's count as 1."""
    if not isinstance(text, str):
        return 0
    return len(text.split())


def actual_character_count(text: str | None) -> int:
    """Historical name. Returns the official word count."""
    return actual_word_count(text)


def validate_prose_length(text: str | None, *, target_word_count: int = DEFAULT_TARGET_WORD_COUNT) -> dict:
    """Return durable, model-independent length validation metadata."""
    actual = actual_word_count(text)
    target = target_word_count if isinstance(target_word_count, int) and target_word_count > 0 else DEFAULT_TARGET_WORD_COUNT
    if actual == 0:
        reason = "empty_text"
    elif actual < MIN_CHARACTER_COUNT:
        reason = "under_length"
    elif actual > MAX_CHARACTER_COUNT:
        reason = "over_length"
    else:
        reason = None
    return {
        "actual_character_count": actual,
        "target_word_count": target,
        "length_validation_status": "passed" if reason is None else "failed",
        "length_validation_reason": reason,
    }


def length_revision_feedback(previous_draft: dict) -> dict | None:
    """Structured Writing rework input. The previous draft stays immutable."""
    reason = previous_draft.get("length_validation_reason")
    if previous_draft.get("length_validation_status") != "failed" or reason not in ("under_length", "over_length", "empty_text"):
        return None
    actual = int(previous_draft.get("actual_character_count") or 0)
    direction = "trim" if reason == "over_length" else "expand"
    if direction == "expand":
        required_min = max(0, MIN_CHARACTER_COUNT - actual)
        required_max = max(required_min, MAX_CHARACTER_COUNT - actual)
        preferred_delta = DEFAULT_TARGET_WORD_COUNT - actual
    else:
        required_min = max(0, actual - MAX_CHARACTER_COUNT)
        required_max = max(required_min, actual - MIN_CHARACTER_COUNT)
        preferred_delta = actual - DEFAULT_TARGET_WORD_COUNT
    payload = {
        "failure_type": "prose_length",
        "previous_draft_id": previous_draft["draft_id"],
        "previous_actual_character_count": actual,
        "minimum_character_count": MIN_CHARACTER_COUNT,
        "maximum_character_count": MAX_CHARACTER_COUNT,
        "preferred_character_count": DEFAULT_TARGET_WORD_COUNT,
        "adjustment_direction": direction,
        "character_delta_to_target": DEFAULT_TARGET_WORD_COUNT - actual,
        "required_minimum_character_delta": required_min,
        "required_maximum_character_delta": required_max,
        "preferred_character_delta": preferred_delta,
        "preferred_output_minimum": PREFERRED_SOFT_MIN,
        "preferred_output_maximum": PREFERRED_SOFT_MAX,
        "approximate_output_ratio": round(DEFAULT_TARGET_WORD_COUNT / actual, 2) if actual else None,
        "content_attempt_in_plan": int(previous_draft.get("content_attempt_in_plan") or 0),
        "previous_text": previous_draft.get("text") or "",
    }
    reported = previous_draft.get("model_reported_word_count")
    if reported is not None and str(reported).strip() != "":
        try:
            payload["previous_model_reported_word_count"] = int(reported)
        except (TypeError, ValueError):
            pass
    return payload


def planning_length_rework_feedback(failed_drafts: list[dict]) -> dict | None:
    """Tell Planning why the previous plan was exhausted. Drafts are not confirmed state."""
    drafts = [draft for draft in failed_drafts if draft.get("length_validation_reason") in ("under_length", "over_length", "empty_text")]
    if not drafts:
        return None
    return {
        "failure_type": "prose_length",
        "reason": "consecutive_length_failures",
        "failed_attempt_count": len(drafts),
        "length_validation_reasons": [draft.get("length_validation_reason") for draft in drafts],
        "actual_character_counts": [int(draft.get("actual_character_count") or 0) for draft in drafts],
        "minimum_character_count": MIN_CHARACTER_COUNT,
        "maximum_character_count": MAX_CHARACTER_COUNT,
        "preferred_character_count": DEFAULT_TARGET_WORD_COUNT,
        "previous_drafts_are_not_confirmed_state": True,
    }


def normalized_draft_payload(payload: dict, validation: dict) -> dict:
    """Make downstream consumers see the authoritative, not self-reported, count."""
    normalized = dict(payload)
    normalized["model_reported_word_count"] = payload.get("word_count")
    normalized["actual_character_count"] = validation["actual_character_count"]
    normalized["word_count"] = validation["actual_character_count"]
    normalized["target_word_count"] = validation["target_word_count"]
    normalized["length_validation_status"] = validation["length_validation_status"]
    normalized["length_validation_reason"] = validation["length_validation_reason"]
    return normalized
