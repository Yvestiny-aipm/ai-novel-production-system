"""SiliconFlow OpenAI-compatible adapter. Keys are read from the environment only."""
import hashlib, json, os, re, urllib.request

from backend.character_canon import character_canon_instruction
from backend.established_facts import established_facts_instruction, world_state_instruction
from backend.chapter_state import chapter_state_instruction
from backend.pacing import pacing_state_instruction
from backend.setting_canon import setting_canon_instruction
from backend.prose_length import (DEFAULT_TARGET_WORD_COUNT, MAX_CHARACTER_COUNT, MIN_CHARACTER_COUNT,
    PREFERRED_SOFT_MAX, PREFERRED_SOFT_MIN, actual_character_count)

PARSE_EXCERPT_LIMIT = 400
PARSE_SUFFIX_LIMIT = 200
TRIM_SINGLE_REDUNDANT_BRACE_RULE = "trim_single_redundant_closing_brace_v1"
PLAIN_PROSE_WRAP_RULE = "wrap_plain_prose_as_prose_draft_v1"
ESCAPE_UNESCAPED_QUOTES_IN_REVIEWER_STRINGS_RULE = "escape_unescaped_quotes_in_reviewer_strings_v1"
INSERT_MISSING_COMMA_IN_REVIEWER_RESULT_RULE = "insert_missing_comma_in_reviewer_result_v1"
MIN_PLAIN_PROSE_WRAP_CHARS = 50
FENCED_JSON = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


class ModelResponseParseError(RuntimeError):
    """Unparseable model JSON. Technical only; never a content failure."""

    def __init__(self, message, *, error_code="MODEL_RESPONSE_JSON_INVALID", content="",
                 finish_reason=None, usage=None, parse_error=None, refusal_reason=None):
        super().__init__(message)
        self.error_code = error_code
        self.content = content if isinstance(content, str) else ""
        self.finish_reason = finish_reason
        self.usage = usage
        self.parse_error = parse_error or message
        self.refusal_reason = refusal_reason

    def to_audit(self):
        content = self.content
        excerpt = content[:PARSE_EXCERPT_LIMIT]
        if len(content) > PARSE_EXCERPT_LIMIT:
            excerpt += "…"
        audit = {
            "error": self.error_code,
            "error_code": self.error_code,
            "content_length": len(content),
            "content_hash": hashlib.sha256(content.encode()).hexdigest(),
            "response_excerpt": excerpt,
            "response_suffix": content[-PARSE_SUFFIX_LIMIT:] if content else "",
            "finish_reason": self.finish_reason,
            "usage": self.usage,
            "parse_error": str(self.parse_error),
        }
        if self.refusal_reason:
            audit["refusal_reason"] = self.refusal_reason
        return audit

CONTRACT_FIELDS = {
    'ScenePlan': 'scene_goal, entrance_state, exit_state, characters, location, time_context, conflict, action_beats, must_happen, must_not_happen, knowledge_boundary, target_word_count (exactly 1250; never 2000, 1000, 1500, or any other value), acceptance_criteria, validation_result, ready_for_writing, progression_requirements (non-empty array: progress_type, target_key, before_state, expected_after_state, acceptance_criterion). progress_type must be one of new_clue, character_state_change, relationship_change, conflict_change, decision_or_consequence, thread_opened, thread_advanced, thread_closed, goal_milestone. before_state must copy progression_baseline literally; do not summarize or invent.',
    'ProseDraft': f'text (complete scene prose, not a plot summary; aim for {PREFERRED_SOFT_MIN}-{PREFERRED_SOFT_MAX} words; hard range {MIN_CHARACTER_COUNT}-{MAX_CHARACTER_COUNT} words), word_count (>0, self-check audit value only; backend recounts words), target_word_count (1250 words), complete (true), writer_self_check; never return empty text or incomplete=true. Finish a concrete action, interaction, turning point, and outcome. Complete at least one ScenePlan progression_requirements item in the prose. Self-check length before return, but word_count is never official. Return JSON only; no explanation outside text.',
    'ReviewerResult': 'reviewer_role must match the assigned task (review_world=world_consistency, review_plot=character_plot, review_style=language_experience); result (passed|failed only); findings (array of must-fix issues); suggestions (array of optional polish); issue_count must equal findings length and never count suggestions; severity (ordinary|serious); impact_scope (local|cross_scene|cross_chapter|book); true_conflict_candidate (boolean); scene_state with characters, location, time_context, events, relationship_changes, unresolved_threads extracted from the current draft; character_plot must include progression_assessment with status (achieved|not_achieved|unclear; never partial, partially_achieved, or partial_success), achieved_items and missing_items. Every achieved item includes progress_type,target_key,before_state copied from ScenePlan, after_state that contains expected_after_state, evidence_text copied verbatim from this draft, evidence_location. Empty findings require result=passed and issue_count=0; non-empty findings require result=failed.',
    'QualityReport': 'review_completion_status must be completed (never complete); reviewer_results; deduped_issue_count; ordinary_issue_count; serious_issue_count; has_true_conflict; needs_arbiter must be false; routing_recommendation must be complete or rewrite (never proceed_with_revisions); accepted_scene_state must contain characters, location, time_context, events, relationship_changes, unresolved_threads; status must be passed or failed (never accepted_with_notes). Do not declare progression_status; the backend verifies progression.',
    'MemoryProposal': 'either (A) one complete proposal recording a confirmed fictional fact change with memory_type, target_scope, target_key, action, before_value, after_value, evidence, evidence_location, change_reason, conflict_status (none|conflict|resolved), write_policy (auto_save|human_confirmation|never_auto_write), status (pending|approved|rejected|written|conflict), or (B) no confirmed fictional fact change to record: payload exactly contains status="skipped" and a non-empty reason; never return empty proposal fields or a proposals array',
}


def _json_text(content):
    text = content.strip()
    fenced = FENCED_JSON.search(text)
    if fenced:
        return fenced.group(1).strip()
    if '```' in text:
        return text.replace('```json', '').replace('```', '').strip()
    return text


def _extra_data_error(error):
    return getattr(error, "msg", "") == "Extra data" or str(error).startswith("Extra data")


def _unterminated_string_error(error):
    message = getattr(error, "msg", "") or str(error)
    return "Unterminated string" in message or "Unterminated" in message


def _missing_comma_error(error):
    message = getattr(error, "msg", "") or str(error)
    return "Expecting ',' delimiter" in message


def _loads_object_no_trailing(text):
    try:
        value, end = json.JSONDecoder().raw_decode(text)
    except json.JSONDecodeError:
        return None
    if text[end:].strip() or not isinstance(value, dict):
        return None
    return value


def _insert_missing_comma_in_reviewer_result(text, error, *, original_text=None):
    """Insert one comma at the reported delimiter gap. ReviewerResult only."""
    if not _missing_comma_error(error):
        return None
    pos = getattr(error, "pos", None)
    if not isinstance(pos, int) or pos < 0 or pos > len(text):
        return None
    if pos > 0 and text[pos - 1] == ",":
        return None
    candidate = text[:pos] + "," + text[pos:]
    value = _loads_object_no_trailing(candidate)
    if value is None:
        return None
    source = original_text if original_text is not None else text
    if "contract_parse_normalization_audit" not in value:
        value = dict(value)
        value["contract_parse_normalization_audit"] = {
            "rule": INSERT_MISSING_COMMA_IN_REVIEWER_RESULT_RULE,
            "original_content_length": len(source),
            "original_content_hash": hashlib.sha256(source.encode()).hexdigest(),
        }
    return value


def _trim_single_redundant_closing_brace(text, *, finish_reason=None):
    """Accept only a complete JSON object plus one extra closing brace."""
    if finish_reason == "length":
        return None
    try:
        value, end = json.JSONDecoder().raw_decode(text)
    except json.JSONDecodeError:
        return None
    trailing = text[end:].strip()
    if not isinstance(value, dict) or trailing != "}":
        return None
    if "contract_parse_normalization_audit" not in value:
        value = dict(value)
        value["contract_parse_normalization_audit"] = {
            "rule": TRIM_SINGLE_REDUNDANT_BRACE_RULE,
            "trailing_character": "}",
            "original_content_length": len(text),
            "original_content_hash": hashlib.sha256(text.encode()).hexdigest(),
        }
    return value


def _escape_bare_ascii_quotes_in_json_strings(text):
    """Escape bare ASCII quotes inside JSON string values. Refuse unclosed strings."""
    if not isinstance(text, str) or not text:
        return None
    out = []
    in_string = False
    escaped = False
    changed = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if not in_string:
            out.append(ch)
            if ch == '"':
                in_string = True
            i += 1
            continue
        if escaped:
            out.append(ch)
            escaped = False
            i += 1
            continue
        if ch == "\\":
            out.append(ch)
            escaped = True
            i += 1
            continue
        if ch == '"':
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            if j == n or text[j] in ",}]:":
                out.append(ch)
                in_string = False
                i += 1
                continue
            out.append("\\")
            out.append('"')
            changed = True
            i += 1
            continue
        out.append(ch)
        i += 1
    if in_string or not changed:
        return None
    return "".join(out)


def _escape_unescaped_quotes_in_reviewer_result(text):
    """ReviewerResult only. Repair string-internal bare quotes; never invent structure."""
    repaired = _escape_bare_ascii_quotes_in_json_strings(text)
    if repaired is None:
        return None
    try:
        value, end = json.JSONDecoder().raw_decode(repaired)
    except json.JSONDecodeError:
        return None
    if repaired[end:].strip() or not isinstance(value, dict):
        return None
    if "contract_parse_normalization_audit" not in value:
        value = dict(value)
        value["contract_parse_normalization_audit"] = {
            "rule": ESCAPE_UNESCAPED_QUOTES_IN_REVIEWER_STRINGS_RULE,
            "original_content_length": len(text),
            "original_content_hash": hashlib.sha256(text.encode()).hexdigest(),
        }
    return value


def looks_like_plain_prose(text):
    stripped = (text or "").strip()
    if not stripped or stripped[0] in "{[":
        return False
    visible = sum(1 for character in stripped if not character.isspace())
    return visible >= MIN_PLAIN_PROSE_WRAP_CHARS


def wrap_plain_prose_as_draft(content, *, finish_reason=None):
    text = content.strip()
    return {
        "contract_type": "ProseDraft",
        "contract_version": "v1",
        "payload": {
            "text": text,
            "word_count": actual_character_count(text),
            "target_word_count": DEFAULT_TARGET_WORD_COUNT,
            "complete": finish_reason != "length",
            "writer_self_check": {"source": "plain_text_wrap"},
        },
        "contract_parse_normalization_audit": {
            "rule": PLAIN_PROSE_WRAP_RULE,
            "original_content_length": len(content),
            "original_content_hash": hashlib.sha256(content.encode()).hexdigest(),
        },
    }


def parse_contract_content(content, *, finish_reason=None, usage=None, expected=None,
                           refusal_reason=None):
    if finish_reason == "refusal":
        text = content if isinstance(content, str) else ""
        reason = (refusal_reason or "").strip()
        raise ModelResponseParseError(
            f"MODEL_RESPONSE_REFUSED: {reason or 'empty refusal'}",
            error_code="MODEL_RESPONSE_REFUSED",
            content=text or reason,
            finish_reason="refusal",
            usage=usage,
            parse_error=reason or "refusal",
            refusal_reason=reason or None,
        )
    if not isinstance(content, str):
        return content
    text = _json_text(content)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        if _extra_data_error(exc):
            normalized = _trim_single_redundant_closing_brace(text, finish_reason=finish_reason)
            if normalized is not None:
                return normalized
        elif expected == "ProseDraft" and finish_reason != "length" and looks_like_plain_prose(text):
            return wrap_plain_prose_as_draft(text, finish_reason=finish_reason)
        elif (
            expected == "ReviewerResult"
            and finish_reason != "length"
            and not _unterminated_string_error(exc)
        ):
            normalized = None
            if _missing_comma_error(exc):
                normalized = _insert_missing_comma_in_reviewer_result(text, exc)
            if normalized is None:
                normalized = _escape_unescaped_quotes_in_reviewer_result(text)
            if normalized is None:
                quoted = _escape_bare_ascii_quotes_in_json_strings(text)
                if quoted:
                    try:
                        json.JSONDecoder().raw_decode(quoted)
                    except json.JSONDecodeError as quote_exc:
                        if (
                            _missing_comma_error(quote_exc)
                            and not _unterminated_string_error(quote_exc)
                        ):
                            normalized = _insert_missing_comma_in_reviewer_result(
                                quoted, quote_exc, original_text=text,
                            )
            if normalized is not None:
                return normalized
        code = "MODEL_OUTPUT_TRUNCATED" if finish_reason == "length" else "MODEL_RESPONSE_JSON_INVALID"
        raise ModelResponseParseError(
            f"{code}: {exc}", error_code=code, content=content,
            finish_reason=finish_reason, usage=usage, parse_error=exc,
        ) from exc


def contract_system_prompt(expected):
    fields = CONTRACT_FIELDS.get(expected, '')
    scene_plan_rule = (
        " For ScenePlan, generate a concrete scene goal, entrance_state, exit_state, characters, location, time_context, conflict, action_beats, must_happen, must_not_happen, knowledge_boundary, target_word_count, acceptance_criteria, and validation_result."
        f" target_word_count MUST be exactly {DEFAULT_TARGET_WORD_COUNT}."
        " Do not output 2000, 1000, 1500, or any other target_word_count."
        f" The finished prose may later contain {MIN_CHARACTER_COUNT}-{MAX_CHARACTER_COUNT} words; that range is not the ScenePlan target."
        " Do not copy the ContextPack as the plan. validation_result must state that every required field is complete and valid; set ready_for_writing to true only after this self-check passes. If any required field is missing or empty, do not claim a complete plan."
        " characters, location, time_context, entrance_state, and exit_state MUST each appear independently at the payload top level."
        " Nested presence inside entrance_state or exit_state does not replace those top-level fields; do not omit them even if the nested objects already contain the same keys."
        " If progression_baseline is present, before_state must copy an existing baseline state literally: no summary, rewrite, abbreviation, or inference."
        " Truly new clues or threads may use unknown; expected_after_state describes this scene's new state."
        " Prefer 1-3 key progression_requirements, not a long target list."
    ) if expected == 'ScenePlan' else ''
    reviewer_rule = (
        " For ReviewerResult, inspect the current draft against the supplied scene_plan."
        " reviewer_role MUST match the assigned task: review_world=world_consistency, review_plot=character_plot, review_style=language_experience."
        " result MUST be passed or failed, never pass_with_notes."
        " findings MUST be an array of must-fix issues only. suggestions MUST be an array of optional polish only."
        " In findings / suggestions / evidence / scene_state JSON strings, escape ASCII quotes; curly quotes are allowed in prose."
        " issue_count MUST equal findings length and MUST NOT count suggestions."
        " Empty findings require result=passed and issue_count=0; acceptable prose MAY return findings=[]."
        " Non-empty findings require result=failed. Do not invent findings to look thorough."
        " Phrases such as acceptable, optional, could polish, or slightly repetitive belong in suggestions, not findings."
        " severity MUST be ordinary or serious. impact_scope MUST be local, cross_scene, cross_chapter, or book."
        " The character_plot reviewer MUST read scene_plan.payload.progression_requirements item by item."
        " Each achieved_item.progress_type, target_key, and before_state MUST copy the planned values exactly."
        " after_state must describe what the current draft actually reached and MUST contain the planned expected_after_state wording."
        " evidence_text MUST be one short contiguous verbatim substring of the current draft.payload.text (Python: evidence_text in draft.payload.text)."
        " Copy one or two consecutive sentences only. Do not splice non-adjacent paragraphs, omit middle sentences, use ellipsis, rewrite, translate, or summarize."
        " If no contiguous original sentence exists, put the item in missing_items or set status=unclear; never claim achieved."
        " Do not invent progress_type values such as character_development, world_expansion, or emotional_response."
        " Do not invent a new target_key to claim success."
        " If a planned item is not completed, put it in missing_items; never substitute another goal."
        " If at least one legal achieved_item exists, status MUST be achieved."
        " If there is no achieved item and missing_items is non-empty, status MUST be not_achieved."
        " Use unclear only when the draft cannot be judged."
        " progression_assessment.status may only be achieved, not_achieved, or unclear; never partial, partially_achieved, or partial_success."
        " scene_state MUST include characters, location, time_context, events, relationship_changes, unresolved_threads."
        " Each achieved_item.after_state MUST also be written into the matching scene_state field:"
        " new_clue → events or unresolved_threads; character_state_change → characters or events;"
        " relationship_change → relationship_changes; thread_opened/thread_advanced/thread_closed → unresolved_threads or events."
        " Do not write after_state only inside progression_assessment."
        " The character_plot scene_state is the authority for plot and progression state."
        " world_consistency and language_experience must not impersonate character_plot."
    ) if expected == 'ReviewerResult' else ''
    quality_report_rule = (
        " For QualityReport, return the Arbiter final report only."
        " review_completion_status MUST be completed, never complete."
        " status MUST be passed or failed, never accepted_with_notes."
        " routing_recommendation MUST be complete or rewrite, never proceed_with_revisions."
        " needs_arbiter MUST be false."
        " accepted_scene_state MUST contain characters, location, time_context, events, relationship_changes, unresolved_threads."
        " Do not declare progression_status, verified items, or a pass on planned progression; the backend verifies those fields."
    ) if expected == 'QualityReport' else ''
    memory_proposal_rule = (
        " For MemoryProposal, this is fictional-work scene-state bookkeeping, not extracting or storing a real person's memory."
        " Record confirmed fictional fact changes from this scene."
        " Do not extract, hand over, or write a real person's memory."
        " Choose exactly one outcome: a complete single proposal, or payload {\"status\":\"skipped\",\"reason\":\"...\"} when this scene has no durable new fictional fact to record."
        " The skipped outcome must contain no proposal fields and does not need target_key. If submitting a proposal, target_key is mandatory and must be a specific, stable identifier for the fact's real subject: "
        "e.g. character:linlan:archive_discovery, location:lighthouse_archive, event:linzhao:memory_projection, or scene_fact:lighthouse:memory_only. "
        "It must identify a character, place, event, or scene fact from the current draft or ContextPack; never use a ContextPack/fixture filename, context_pack, pack_v*, a generic label such as fact/event/memory/scene, or a vague description. "
        "For a proposal, action MUST be exactly create for a new memory, update for changing an existing memory, or delete for removing an existing memory. Never use add, modify, remove, append, or any other action value. "
        "memory_type MUST be exactly one of scene_fact, narrative_event, world_rule, character_detail, and target_scope MUST be exactly one of scene_memory, book_memory, character_memory. "
        "Mapping is mandatory: scene_fact→scene_memory + auto_save; narrative_event→book_memory + human_confirmation; world_rule→book_memory + human_confirmation; character_detail→character_memory + human_confirmation. "
        "Never use story, chapter, chapter_summary, fact, narrative, event, or never_auto_write for ordinary recorded fictional facts. "
        "Do not return a proposals array. Do not use Markdown fences or explanatory text."
    ) if expected == 'MemoryProposal' else ''
    prose_draft_rule = (
        " For ProseDraft, write a complete scene rather than a plot summary."
        f" Aim for {PREFERRED_SOFT_MIN}-{PREFERRED_SOFT_MAX} words;"
        f" the backend hard range remains {MIN_CHARACTER_COUNT}-{MAX_CHARACTER_COUNT} words and is recalculated independently."
        " Write 12-15 effective paragraphs; each paragraph must carry action, interaction, resistance, a turning point, or a result."
        " Do not pad with environment, weather, or atmosphere. Do not replace the scene with a plot summary."
        " Complete at least one ScenePlan progression_requirements item."
        " If revision_feedback is present, treat this as a quantitative edit of previous_text, not a new blind draft."
        " If quality_revision_feedback is present, treat this as a revision of previous_text: keep acceptable prose, fix the listed reviewer findings, and complete only remaining progression gaps."
        " If progression_status is passed, do not rewrite the scene as if the prose failed to advance."
        " Do not invent a new progress_type or target_key. Do not append a mechanical closing summary. Do not only change word_count or structured fields. Resubmit a complete ProseDraft."
        " Self-check length before returning; the self-check is not official."
        " Return only JSON; do not output explanation outside text."
    ) if expected == 'ProseDraft' else ''
    return (
        f"Return only valid JSON. The business Contract type MUST be exactly {expected!r}; this is different from the internal task_type. "
        f"Use keys contract_type, contract_version, payload. Set contract_type to {expected!r}, contract_version to 'v1', "
        f"and include every required payload field: {fields}.{scene_plan_rule}{prose_draft_rule}{reviewer_rule}{quality_report_rule}{memory_proposal_rule} "
        "Do not use Markdown fences or explanatory text."
    )


def _official_count_instruction(feedback):
    actual = feedback.get("previous_actual_character_count")
    reported = feedback.get("previous_model_reported_word_count")
    parts = ["Official length is the backend word count. word_count is not official."]
    if reported is not None and actual is not None and str(reported).strip() != "":
        parts.append(f"You claimed {reported}; the backend counted {actual} words. Use {actual}.")
    return "".join(parts)


def writing_length_edit_instruction(feedback):
    """Highest-priority quantitative edit. Keep it short so it is not buried in previous_text."""
    actual = feedback["previous_actual_character_count"]
    required = feedback["required_minimum_character_delta"]
    preferred = feedback["preferred_character_delta"]
    hard = f"{MIN_CHARACTER_COUNT}-{MAX_CHARACTER_COUNT}"
    soft = f"{PREFERRED_SOFT_MIN}-{PREFERRED_SOFT_MAX}"
    official = _official_count_instruction(feedback)
    if feedback.get("adjustment_direction") == "expand":
        return (
            f"The previous draft was {actual} words. This draft must be {hard} words, preferred {soft}."
            f"{official}"
            f"Add at least {required} words, preferably {preferred}."
            "Do not resubmit the same draft. You must reach the hard minimum."
            "Resubmitting the same draft will be blocked immediately."
            "Expand existing beats: make action, dialogue, and resistance more concrete."
            "Do not start a new plot, but do not leave the draft unchanged because of this sentence."
            "Do not add unprepared characters, places, or world mechanisms."
            "Do not give the lighthouse any power beyond storing and displaying memory."
            "Do not recap. Do not add a closing summary."
        )
    return (
        f"The previous draft was {actual} words. This draft must be {hard} words, preferred {soft}."
        f"{official}"
        f"Cut at least {required} words, preferably {preferred}."
        "Do not resubmit the same draft. You must get under the hard maximum."
        "Resubmitting the same draft will be blocked immediately."
        "Really delete repeated setting, interiority, and synonymous phrasing."
        "Do not only change word_count. Do not return nearly the same text."
    )


def writing_progression_edit_instruction(feedback):
    return writing_quality_edit_instruction(feedback)


def _finding_part_text(part):
    if isinstance(part, dict):
        pieces = []
        for key in ("issue", "detail", "suggested_fix"):
            value = part.get(key)
            if isinstance(value, str) and value.strip():
                pieces.append(value.strip())
        return ": ".join(pieces)
    return str(part).strip() if part else ""


def _finding_text(item):
    findings = item.get("findings")
    if isinstance(findings, list):
        return "; ".join(text for text in (_finding_part_text(part) for part in findings) if text)
    if isinstance(findings, dict):
        return _finding_part_text(findings)
    return str(findings or "").strip()


def writing_quality_edit_instruction(feedback):
    parts = [
        "The previous QualityReport failed. Keep unnamed usable paragraphs. "
        "Sentences named in findings must be rewritten or deleted. You must edit the prose. "
        "Do not return the same draft. Do not only change structured fields or word_count."
    ]
    findings = feedback.get("reviewer_findings") or []

    def role_issues(role):
        return [item for item in findings if item.get("reviewer_role") == role and int(item.get("issue_count") or 0) > 0]

    world = role_issues("world_consistency")
    plot = role_issues("character_plot")
    style = role_issues("language_experience")
    if world:
        parts.append("World / continuity issues: " + "; ".join(_finding_text(item) or "needs a fix" for item in world) + ".")
    if plot:
        parts.append("Character / plot issues: " + "; ".join(_finding_text(item) or "needs a fix" for item in plot) + ".")
    if style:
        parts.append("Language issues: " + "; ".join(_finding_text(item) or "needs a fix" for item in style) + ".")
    if feedback.get("progression_status") == "failed" and (feedback.get("missing_progression_items") or feedback.get("progression_failure_reason")):
        reason = feedback.get("progression_failure_reason") or "planned_progression_not_achieved"
        parts.append(f"Progression is incomplete. Reason: {reason}. Complete the planned items. Do not invent a new target_key or progress_type.")
    return "".join(parts)


REVIEWER_ENUM_INSTRUCTION = (
    "severity must be ordinary or serious."
    "impact_scope must be local, cross_scene, cross_chapter, or book."
)


def reviewer_findings_instruction():
    return (
        "findings must be an array of must-fix issues only: "
        "world-rule conflicts, fact contradictions, implausible character action, missing planned progression, "
        "missing evidence, serious grammar that blocks reading, hard cross-scene / cross-chapter / book issues, true review conflicts."
        "suggestions must be an array of optional polish only: "
        "a slightly repetitive sentence, optional tightening, a word swap, unused rhythm, richer metaphor, non-required style preference."
        "Acceptable / optional / could polish / slightly repetitive notes belong only in suggestions."
        "issue_count must equal findings length and must not count suggestions."
        "Empty findings require result=passed and issue_count=0; acceptable prose may return findings=[]."
        "Non-empty findings require result=failed."
        "result must be passed or failed, never pass_with_notes."
        "Do not invent findings to look thorough."
        "suggestions do not trigger Writing rework, Arbiter, or a block, but must still be returned in full."
    )


def reviewer_world_instruction():
    return (
        "reviewer_role must be exactly world_consistency."
        "Check only world rules, setting, time and place, knowledge boundary, and continuity."
        + character_canon_instruction()
        + setting_canon_instruction()
        + "Do not impersonate character_plot."
        "progression_assessment may be omitted."
        + reviewer_findings_instruction()
        + REVIEWER_ENUM_INSTRUCTION
    )


def reviewer_plot_instruction():
    return (
        "reviewer_role must be exactly character_plot."
        "Own character behavior, plot structure, and progression_assessment."
        "progression_assessment.status must be achieved, not_achieved, or unclear."
        "If at least one legal achieved_item exists, status is achieved."
        "If there is no achieved item and missing_items is non-empty, status is not_achieved."
        "Use unclear only when the draft cannot be judged."
        "achieved_items must copy ScenePlan progress_type, target_key, and before_state exactly."
        "after_state must contain the planned expected_after_state wording."
        "Do not return partial, partially_achieved, or partial_success."
        + reviewer_progression_instruction()
        + reviewer_evidence_instruction()
        + reviewer_findings_instruction()
        + REVIEWER_ENUM_INSTRUCTION
    )


def reviewer_style_instruction():
    return (
        "reviewer_role must be exactly language_experience."
        "Check only language, rhythm, readability, and obvious expression problems."
        "Do not impersonate character_plot."
        "progression_assessment may be omitted."
        + reviewer_findings_instruction()
        + REVIEWER_ENUM_INSTRUCTION
    )


def reviewer_instruction_for_task(task_type):
    if task_type == "review_world":
        return reviewer_world_instruction()
    if task_type == "review_style":
        return reviewer_style_instruction()
    return reviewer_plot_instruction()


def reviewer_progression_instruction():
    return (
        "Check scene_plan.payload.progression_requirements item by item."
        "Each achieved_item must copy the planned progress_type, target_key, and before_state."
        "after_state must contain the planned expected_after_state wording. evidence_text must be a contiguous verbatim substring of the current draft.payload.text."
        "Do not invent progress_type values such as character_development, world_expansion, or emotional_response, or a new target_key."
        "If an item is not completed, put it in missing_items. Do not substitute another goal."
        "scene_state must include characters, location, time_context, events, relationship_changes, unresolved_threads."
        "Each achieved_item.after_state must also land in the matching scene_state field: "
        "new_clue → events or unresolved_threads; "
        "character_state_change → characters or events; "
        "relationship_change → relationship_changes; "
        "thread_opened, thread_advanced, thread_closed → unresolved_threads or events."
        "Do not write after_state only inside progression_assessment."
    )


def reviewer_correction_instruction():
    return (
        "This is a ReviewerResult contract technical correction, correction_attempt=1. Do not loop again."
        "Fix illegal fields only. Do not rewrite the ScenePlan or Draft."
        "progression_assessment.status must be achieved, not_achieved, or unclear."
        "If at least one legal achieved_item exists, status is achieved."
        "If there is no achieved item and missing_items is non-empty, status is not_achieved."
        "Use unclear only when the draft cannot be judged."
        "Do not use partial, partially_achieved, or partial_success."
        "Each achieved_item progress_type, target_key, and before_state must match the ScenePlan exactly."
        "after_state must contain the planned expected_after_state wording."
        "evidence_text must be a contiguous verbatim substring of the Draft. If no evidence exists, move the item to missing_items. Do not invent it."
        + reviewer_findings_instruction()
        + "Old pass_with_notes, string findings, or optional-tightening notes stuffed into findings must be converted to the new structure."
    )


def reviewer_evidence_instruction():
    return (
        "evidence_text copies one short contiguous original sentence or fragment from the draft."
        "Prefer one or two sentences."
        "Do not splice across paragraphs."
        "Do not drop a middle sentence."
        "Do not replace the original with an ellipsis."
        "Do not rewrite, translate, or summarize."
        "Quotes must match the draft. Do not turn curly quotes into ASCII quotes."
        "Before return, confirm the Python meaning: evidence_text in draft.payload.text."
        "If no contiguous original exists, put the item in missing_items or set status=unclear. Do not claim achieved."
    )


def arbiter_quality_instruction():
    return (
        "Return a complete QualityReport."
        "review_completion_status must be completed, never complete."
        "status must be passed or failed, never accepted_with_notes."
        "routing_recommendation must be complete or rewrite, never proceed_with_revisions."
        "needs_arbiter must be false."
        "accepted_scene_state must include characters, location, time_context, events, relationship_changes, unresolved_threads."
        "Judge disputes against scene_plan, draft, reviewer_results, preliminary_quality, and progression_requirements."
        "Do not declare progression passed; the backend writes those fields after verification."
    )


def planning_progression_instruction():
    return (
        "before_state must copy an existing state from progression_baseline literally. Do not summarize, rewrite, abbreviate, or infer."
        "Truly new clues or threads may use unknown."
        "expected_after_state describes this scene's expected new state."
        "The first version should set only 1-3 key progression items. Do not load too many targets."
        "new_clue: before_state may be unknown, otherwise it must exist in the previous scene's events or unresolved_threads."
        "character_state_change: before_state must exist in the previous scene's characters or events."
        "relationship_change: before_state must exist in the previous scene's relationship_changes."
        "conflict_change: before_state must exist in events, relationship_changes, or unresolved_threads."
        "decision_or_consequence: before_state must exist in events or characters."
        "thread_advanced and thread_closed: before_state must exist in unresolved_threads or events."
        "thread_opened: unknown is allowed. Do not disguise an existing thread as new."
        "goal_milestone: before_state must exist in events."
        "characters, location, time_context, entrance_state, and exit_state must each appear independently at the payload top level."
        "Do not omit those top-level fields because they already appear inside entrance_state or exit_state."
        + character_canon_instruction()
        + setting_canon_instruction()
        + established_facts_instruction()
        + world_state_instruction()
        + pacing_state_instruction()
        + chapter_state_instruction()
    )


def planning_revision_instruction(feedback):
    reason = feedback.get("reason") or ""
    parts = [f"The previous plan was sent back because {reason}."]
    for item in feedback.get("failed_items") or []:
        progress_type = item.get("progress_type") or ""
        before = item.get("before_state")
        allowed = ", ".join(item.get("allowed_fields") or [])
        parts.append(f"Bad item: type {progress_type}, wrong before_state {before}, allowed fields {allowed or 'unknown'}.")
    parts.append("new_clue / thread_opened may use unknown.")
    parts.append("Copy from allowed fields literally. Do not summarize or move a sentence from another column.")
    parts.append("Do not resubmit the same wrong before_state set.")
    return "".join(parts)


def first_draft_writing_instruction():
    return (
        f"This draft must be {MIN_CHARACTER_COUNT}-{MAX_CHARACTER_COUNT} words, preferred {PREFERRED_SOFT_MIN}-{PREFERRED_SOFT_MAX}."
        "Write 12-15 effective paragraphs. Each paragraph must carry action, interaction, resistance, a turning point, or a result."
        "Do not pad with environment. Do not replace the scene with a plot summary."
        "Complete at least one progression_requirements item."
        "Obey scene_plan.must_not_happen, knowledge_boundary, and approved world rules."
        + character_canon_instruction()
        + setting_canon_instruction()
        + established_facts_instruction()
        + world_state_instruction()
        + f"Over {MAX_CHARACTER_COUNT} words fails. You must get under the hard maximum. Do not only change word_count."
        "Official length is the backend word count. payload.word_count is not official."
        "Do not pass by only setting word_count to 1287/1250."
        "Self-check length before return, but do not only change word_count."
    )


MEMORY_REFUSAL_RETRY_NOTE = "The prose already passed review. Bookkeep from the confirmed scene state."
MEMORY_REFUSAL_RETRY_PACK_KEYS = ("character_canon", "setting_canon", "approved_facts", "previous_scene_state")


def memory_proposal_instruction():
    return (
        "This is fictional-work scene-state bookkeeping, not extracting or storing a real person's memory."
        "Record confirmed fictional fact changes from this scene."
        "If this scene has no durable new fictional fact, return payload {\"status\":\"skipped\",\"reason\":\"...\"}."
        "Do not extract, hand over, or write a real person's memory."
    )


def memory_refusal_retry_instruction():
    return (
        "Again: this is fictional-work scene-state bookkeeping, not extracting or storing a real person's memory."
        "Record only confirmed fictional fact changes from this scene. If there is nothing to record, return skipped and say why."
        "Do not extract, hand over, or write a real person's memory."
    )


def _accepted_scene_state_from_input(payload):
    if not isinstance(payload, dict):
        return {}
    direct = payload.get("accepted_scene_state")
    if isinstance(direct, dict):
        return direct
    report = payload.get("quality_report")
    if not isinstance(report, dict):
        return {}
    if isinstance(report.get("accepted_scene_state"), dict):
        return report["accepted_scene_state"]
    nested = report.get("payload")
    if isinstance(nested, dict) and isinstance(nested.get("accepted_scene_state"), dict):
        return nested["accepted_scene_state"]
    return {}


def _slim_context_pack(pack):
    if not isinstance(pack, dict):
        return {}
    source = pack
    inner = pack.get("payload")
    if isinstance(inner, dict) and any(key in inner for key in MEMORY_REFUSAL_RETRY_PACK_KEYS):
        source = inner
    return {key: source[key] for key in MEMORY_REFUSAL_RETRY_PACK_KEYS if key in source}


def slim_memory_refusal_retry_input(payload):
    """Retry payload: confirmed scene-state bookkeeping only. No draft text, no full report."""
    payload = payload if isinstance(payload, dict) else {}
    return {
        "context_pack": _slim_context_pack(payload.get("context_pack")),
        "accepted_scene_state": _accepted_scene_state_from_input(payload),
    }


def retry_memory_refusal(adapter, error, request, timeout_seconds):
    """Same complete() call: one slim tone retry for memory_extraction refusal only."""
    if (
        isinstance(error, ModelResponseParseError)
        and error.error_code == "MODEL_RESPONSE_REFUSED"
        and request.get("task_type") == "memory_extraction"
        and not request.get("memory_refusal_retry")
    ):
        retry_request = dict(request)
        retry_request["memory_refusal_retry"] = True
        retry_request["input"] = slim_memory_refusal_retry_input(
            request.get("input") if isinstance(request.get("input"), dict) else {}
        )
        return adapter.complete(retry_request, timeout_seconds)
    raise error


def build_chat_messages(request):
    """Pure message builder. No network. System holds format; users hold data then the edit."""
    expected = request.get("contract_type")
    payload = request.get("input") if isinstance(request.get("input"), dict) else {}
    if expected == "MemoryProposal" and request.get("memory_refusal_retry"):
        payload = slim_memory_refusal_retry_input(payload)
    messages = [
        {"role": "system", "content": contract_system_prompt(expected)},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    if expected == "ProseDraft":
        quality = payload.get("quality_revision_feedback")
        feedback = payload.get("revision_feedback")
        length_ok = isinstance(feedback, dict) and feedback.get("previous_actual_character_count") is not None
        quality_ok = isinstance(quality, dict) and quality.get("failure_type") in ("quality_report", "progression")
        if length_ok:
            messages.append({"role": "user", "content": writing_length_edit_instruction(feedback)})
        if quality_ok:
            messages.append({"role": "user", "content": writing_quality_edit_instruction(quality)})
        if not length_ok and not quality_ok:
            messages.append({"role": "user", "content": first_draft_writing_instruction()})
    elif expected == "ReviewerResult":
        messages.append({"role": "user", "content": reviewer_instruction_for_task(request.get("task_type"))})
        correction = payload.get("reviewer_contract_correction")
        if isinstance(correction, dict):
            messages.append({"role": "user", "content": reviewer_correction_instruction()})
    elif expected == "QualityReport":
        messages.append({"role": "user", "content": arbiter_quality_instruction()})
    elif expected == "ScenePlan":
        messages.append({"role": "user", "content": planning_progression_instruction()})
        revision = payload.get("planning_revision_feedback")
        if isinstance(revision, dict) and revision.get("reason"):
            messages.append({"role": "user", "content": planning_revision_instruction(revision)})
    elif expected == "MemoryProposal":
        messages.append({"role": "user", "content": memory_proposal_instruction()})
        if request.get("memory_refusal_retry"):
            messages.append({"role": "user", "content": MEMORY_REFUSAL_RETRY_NOTE})
            messages.append({"role": "user", "content": memory_refusal_retry_instruction()})
    return messages


DEFAULT_SILICONFLOW_MODEL = "deepseek-ai/DeepSeek-V3"
DEFAULT_TIMEOUT_SECONDS = 60
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 600
TASK_MODEL_ENV = {
    "writing": "SILICONFLOW_WRITING_MODEL",
    "planning": "SILICONFLOW_PLANNING_MODEL",
    "review_world": "SILICONFLOW_REVIEW_MODEL",
    "review_plot": "SILICONFLOW_REVIEW_MODEL",
    "review_style": "SILICONFLOW_REVIEW_MODEL",
    "arbiter": "SILICONFLOW_ARBITER_MODEL",
    "memory_extraction": "SILICONFLOW_MEMORY_MODEL",
}
STRUCTURED_TASKS = frozenset({
    "planning", "review_world", "review_plot", "review_style", "arbiter", "memory_extraction",
})
TASK_TIMEOUT_ENV = {
    "writing": "SILICONFLOW_WRITING_TIMEOUT_SECONDS",
    "planning": "SILICONFLOW_PLANNING_TIMEOUT_SECONDS",
    "review_world": "SILICONFLOW_REVIEW_TIMEOUT_SECONDS",
    "review_plot": "SILICONFLOW_REVIEW_TIMEOUT_SECONDS",
    "review_style": "SILICONFLOW_REVIEW_TIMEOUT_SECONDS",
    "arbiter": "SILICONFLOW_ARBITER_TIMEOUT_SECONDS",
    "memory_extraction": "SILICONFLOW_MEMORY_TIMEOUT_SECONDS",
}


class TimeoutConfigError(ValueError):
    """Invalid per-task timeout configuration. Never silently fall back."""


def _env_model(environ, name):
    if not name:
        return None
    value = environ.get(name)
    if isinstance(value, str):
        value = value.strip()
    return value or None


def _env_value(environ, name):
    if not name or name not in environ:
        return None
    return environ[name]


def parse_timeout_seconds(value, name):
    if isinstance(value, bool) or value is None:
        raise TimeoutConfigError(f"invalid {name}: {value!r}")
    text = value.strip() if isinstance(value, str) else value
    try:
        number = float(text)
    except (TypeError, ValueError) as error:
        raise TimeoutConfigError(f"invalid {name}: {value!r}") from error
    if number != number or number < MIN_TIMEOUT_SECONDS or number > MAX_TIMEOUT_SECONDS:
        raise TimeoutConfigError(f"invalid {name}: {value!r}")
    return int(number) if number == int(number) else number


def resolve_task_timeout(task_type, environ=None, *, default=None):
    """Resolve the routed timeout. Invalid values fail instead of falling back."""
    env = environ if environ is not None else os.environ
    fallback = DEFAULT_TIMEOUT_SECONDS if default is None else default
    specific_name = TASK_TIMEOUT_ENV.get(task_type)
    specific = _env_value(env, specific_name)
    if specific is not None:
        return parse_timeout_seconds(specific, specific_name)
    if task_type in STRUCTURED_TASKS:
        grouped = _env_value(env, "SILICONFLOW_STRUCTURED_TIMEOUT_SECONDS")
        if grouped is not None:
            return parse_timeout_seconds(grouped, "SILICONFLOW_STRUCTURED_TIMEOUT_SECONDS")
    default_value = _env_value(env, "SILICONFLOW_DEFAULT_TIMEOUT_SECONDS")
    if default_value is not None:
        return parse_timeout_seconds(default_value, "SILICONFLOW_DEFAULT_TIMEOUT_SECONDS")
    return fallback


def resolve_task_model(task_type, environ=None, *, default=None):
    """Resolve the routed model name. Never invents a new vendor model id."""
    env = environ if environ is not None else os.environ
    fallback = default or DEFAULT_SILICONFLOW_MODEL
    specific = _env_model(env, TASK_MODEL_ENV.get(task_type))
    if specific:
        return specific
    if task_type in STRUCTURED_TASKS:
        grouped = _env_model(env, "SILICONFLOW_STRUCTURED_MODEL")
        if grouped:
            return grouped
    return _env_model(env, "SILICONFLOW_DEFAULT_MODEL") or fallback


def json_mode_enabled(environ=None):
    env = environ if environ is not None else os.environ
    return str(env.get("SILICONFLOW_JSON_MODE") or "").strip() == "1"


def build_request_body(request, default_model=None, environ=None):
    """Pure OpenAI-compatible body. Model comes from the Harness request."""
    body = {
        "model": request.get("model") or default_model,
        "messages": build_chat_messages(request),
        "max_tokens": request.get("max_output_tokens", 4096),
        "temperature": 0,
    }
    enabled = request.get("json_mode")
    if enabled is None:
        enabled = json_mode_enabled(environ)
    if enabled:
        body["response_format"] = {"type": "json_object"}
    return body


class SiliconFlowAdapter:
    def __init__(self, *, api_url=None, api_key_env="SILICONFLOW_API_KEY", model="deepseek-ai/DeepSeek-V3", timeout=60):
        self.api_url=api_url or os.getenv("SILICONFLOW_API_URL", "https://api.siliconflow.cn/v1/chat/completions")
        self.api_key_env=api_key_env; self.model=model; self.timeout=timeout
    def complete(self, request, timeout_seconds):
        key=os.getenv(self.api_key_env)
        if not key: raise RuntimeError("SILICONFLOW_API_KEY_MISSING")
        body=build_request_body(request, default_model=self.model)
        req=urllib.request.Request(self.api_url,data=json.dumps(body).encode(),headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},method="POST")
        with urllib.request.urlopen(req,timeout=timeout_seconds or self.timeout) as res:
            result=json.loads(res.read())
        if result.get("error"):
            raise RuntimeError(result["error"])
        if result.get("contract"):
            return result["contract"]
        choice = (result.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content")
        finish_reason = choice.get("finish_reason")
        usage = result.get("usage")
        refusal_reason = message.get("refusal")
        try:
            if finish_reason == "refusal" or isinstance(content, str):
                return parse_contract_content(
                    content if isinstance(content, str) else "",
                    finish_reason=finish_reason, usage=usage,
                    expected=request.get("contract_type"),
                    refusal_reason=refusal_reason,
                )
        except ModelResponseParseError as error:
            return retry_memory_refusal(self, error, request, timeout_seconds)
        return result
