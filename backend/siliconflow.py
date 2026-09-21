"""硅基流动 OpenAI 兼容接口适配器。密钥只从环境变量读取。"""
import hashlib, json, os, re, urllib.request

from backend.character_canon import character_canon_instruction
from backend.setting_canon import setting_canon_instruction
from backend.prose_length import (DEFAULT_TARGET_WORD_COUNT, MAX_CHARACTER_COUNT, MIN_CHARACTER_COUNT,
    PREFERRED_SOFT_MAX, PREFERRED_SOFT_MIN, actual_character_count)

PARSE_EXCERPT_LIMIT = 400
PARSE_SUFFIX_LIMIT = 200
TRIM_SINGLE_REDUNDANT_BRACE_RULE = "trim_single_redundant_closing_brace_v1"
PLAIN_PROSE_WRAP_RULE = "wrap_plain_prose_as_prose_draft_v1"
ESCAPE_UNESCAPED_QUOTES_IN_REVIEWER_STRINGS_RULE = "escape_unescaped_quotes_in_reviewer_strings_v1"
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
    'ProseDraft': f'text (complete scene prose, not a plot summary; aim for {PREFERRED_SOFT_MIN}-{PREFERRED_SOFT_MAX} non-whitespace Chinese characters so the {MIN_CHARACTER_COUNT}-{MAX_CHARACTER_COUNT} hard range has margin), word_count (>0, self-check audit value only; backend recounts), target_word_count (1250), complete (true), writer_self_check; never return empty text or incomplete=true. Finish a concrete action, interaction, turning point, and outcome. Complete at least one ScenePlan progression_requirements item in the prose. Self-check length before return, but word_count is never official. Return JSON only; no explanation outside text.',
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
    return actual_character_count(stripped) >= MIN_PLAIN_PROSE_WRAP_CHARS


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
            normalized = _escape_unescaped_quotes_in_reviewer_result(text)
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
        f" The finished prose may later contain {MIN_CHARACTER_COUNT}-{MAX_CHARACTER_COUNT} non-whitespace characters; that range is not the ScenePlan target."
        " Do not copy the ContextPack as the plan. validation_result must state that every required field is complete and valid; set ready_for_writing to true only after this self-check passes. If any required field is missing or empty, do not claim a complete plan."
        " characters, location, time_context, entrance_state, and exit_state MUST each appear independently at the payload top level."
        " Nested presence inside entrance_state or exit_state does not replace those top-level fields; do not omit them even if the nested objects already contain the same keys."
        " If progression_baseline is present, before_state must copy an existing baseline state literally: no summary, rewrite, abbreviation, or inference."
        " Truly new clues or threads may use 未知; expected_after_state describes this scene's new state."
        " Prefer 1-3 key progression_requirements, not a long target list."
    ) if expected == 'ScenePlan' else ''
    reviewer_rule = (
        " For ReviewerResult, inspect the current draft against the supplied scene_plan."
        " reviewer_role MUST match the assigned task: review_world=world_consistency, review_plot=character_plot, review_style=language_experience."
        " result MUST be passed or failed, never pass_with_notes."
        " findings MUST be an array of must-fix issues only. suggestions MUST be an array of optional polish only."
        " findings / suggestions / evidence / scene_state 字符串禁止裸 ASCII \"，改用「」或中文引号。"
        " issue_count MUST equal findings length and MUST NOT count suggestions."
        " Empty findings require result=passed and issue_count=0; acceptable prose MAY return findings=[]."
        " Non-empty findings require result=failed. Do not invent findings to look thorough."
        " Phrases such as 可接受, 可酌情, 可以优化, or 略显重复 belong in suggestions, not findings."
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
        " 记录本场已确认的虚构事实变化。"
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
        f" Aim for {PREFERRED_SOFT_MIN}-{PREFERRED_SOFT_MAX} non-whitespace Chinese characters;"
        f" the backend hard range remains {MIN_CHARACTER_COUNT}-{MAX_CHARACTER_COUNT} and is recalculated independently."
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
    parts = ["正式长度以后端实算为准，word_count 不是官方计数。"]
    if reported is not None and actual is not None and str(reported).strip() != "":
        parts.append(f"你自称{reported}，后端实算{actual}，以{actual}为准。")
    return "".join(parts)


def writing_length_edit_instruction(feedback):
    """Highest-priority quantitative edit. Keep it short so it is not buried in previous_text."""
    actual = feedback["previous_actual_character_count"]
    required = feedback["required_minimum_character_delta"]
    preferred = feedback["preferred_character_delta"]
    hard = f"{MIN_CHARACTER_COUNT}～{MAX_CHARACTER_COUNT}"
    soft = f"{PREFERRED_SOFT_MIN}～{PREFERRED_SOFT_MAX}"
    official = _official_count_instruction(feedback)
    if feedback.get("adjustment_direction") == "expand":
        return (
            f"上一稿实际为{actual}个非空白字符。本次必须输出{hard}，建议{soft}。"
            f"{official}"
            f"至少增加{required}，建议增加{preferred}。"
            "禁止交回同一篇。必须加到硬下限以上。"
            "再交回同一篇会被立即阻断。"
            "把已有节拍的动作、对话、阻力写得更具体来加字。"
            "不要另起一场戏，但不要因为这句话就整篇不动。"
            "不得新增未铺垫人物、地点、世界机制。"
            "不得让灯塔具备保存与展示记忆以外的能力。"
            "不要复述，不要在结尾补总结。"
        )
    return (
        f"上一稿实际为{actual}个非空白字符。本次必须输出{hard}，建议{soft}。"
        f"{official}"
        f"至少删除{required}，建议删除{preferred}。"
        "禁止交回同一篇。必须删到硬上限以下。"
        "再交回同一篇会被立即阻断。"
        "请真正删除重复环境、心理和同义表达。"
        "不能只改word_count，不能近乎原样返回。"
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
        return "：".join(pieces)
    return str(part).strip() if part else ""


def _finding_text(item):
    findings = item.get("findings")
    if isinstance(findings, list):
        return "；".join(text for text in (_finding_part_text(part) for part in findings) if text)
    if isinstance(findings, dict):
        return _finding_part_text(findings)
    return str(findings or "").strip()


def writing_quality_edit_instruction(feedback):
    parts = [
        "上一稿 QualityReport 失败。未点名的可用段落可以保留；"
        "findings 点名的句子必须改写或删除。必须实际修改正文。"
        "禁止整篇原样返回。禁止原样返回。禁止只改结构化字段或word_count。"
    ]
    findings = feedback.get("reviewer_findings") or []

    def role_issues(role):
        return [item for item in findings if item.get("reviewer_role") == role and int(item.get("issue_count") or 0) > 0]

    world = role_issues("world_consistency")
    plot = role_issues("character_plot")
    style = role_issues("language_experience")
    if world:
        parts.append("世界/连续性问题：" + "；".join(_finding_text(item) or "需修正" for item in world) + "。")
    if plot:
        parts.append("人物/剧情问题：" + "；".join(_finding_text(item) or "需修正" for item in plot) + "。")
    if style:
        parts.append("语言问题：" + "；".join(_finding_text(item) or "需修正" for item in style) + "。")
    if feedback.get("progression_status") == "failed" and (feedback.get("missing_progression_items") or feedback.get("progression_failure_reason")):
        reason = feedback.get("progression_failure_reason") or "planned_progression_not_achieved"
        parts.append(f"推进目标未完成，原因：{reason}。必须完成原规划目标，不得另造 target_key 或 progress_type。")
    return "".join(parts)


REVIEWER_ENUM_INSTRUCTION = (
    "severity 只能是 ordinary 或 serious。"
    "impact_scope 只能是 local、cross_scene、cross_chapter 或 book。"
)


def reviewer_findings_instruction():
    return (
        "findings 必须是数组，只放必须返工的硬问题："
        "世界规则冲突、前后事实矛盾、人物行为明显不成立、剧情没有完成有效推进、"
        "证据不存在、严重语法或表达错误、明显影响阅读理解、跨场/跨章/全书硬问题、真正审查冲突。"
        "suggestions 必须是数组，只放可选优化："
        "某句略重复、可酌情精简、可以换词、节奏还有空间但不影响阅读、比喻可以更丰富、非必要风格偏好。"
        "可接受、可酌情、可以优化、略显重复等非必要修改只能进入 suggestions。"
        "issue_count 必须等于 findings 长度，不得把 suggestions 计入 issue_count。"
        "findings 为空时 result 必须是 passed、issue_count 必须是 0；正文达到标准时允许 findings=[]。"
        "findings 非空时 result 必须是 failed。"
        "result 只能是 passed 或 failed，不得返回 pass_with_notes。"
        "不得为了显得认真而强行制造 findings。"
        "suggestions 不触发 Writing 返工、Arbiter 或阻塞，但仍须完整返回。"
    )


def reviewer_world_instruction():
    return (
        "reviewer_role 必须严格为 world_consistency。"
        "只检查世界规则、设定、时间地点、知识边界和前后连续性。"
        + character_canon_instruction()
        + setting_canon_instruction()
        + "不得冒充 character_plot。"
        "progression_assessment 可不提供。"
        + reviewer_findings_instruction()
        + REVIEWER_ENUM_INSTRUCTION
    )


def reviewer_plot_instruction():
    return (
        "reviewer_role 必须严格为 character_plot。"
        "负责人物行为、剧情结构和 progression_assessment。"
        "progression_assessment.status 只能是 achieved、not_achieved、unclear。"
        "有至少一个合法 achieved_item 时，status 使用 achieved。"
        "没有达成项且存在 missing_items 时，status 使用 not_achieved。"
        "无法判断时使用 unclear。"
        "achieved_items 必须精确对应 ScenePlan 的 progress_type、target_key、before_state。"
        "after_state 必须包含对应 expected_after_state 的原文表达。"
        "不得返回 partial、partially_achieved、partial_success。"
        + reviewer_progression_instruction()
        + reviewer_evidence_instruction()
        + reviewer_findings_instruction()
        + REVIEWER_ENUM_INSTRUCTION
    )


def reviewer_style_instruction():
    return (
        "reviewer_role 必须严格为 language_experience。"
        "只检查语言、节奏、可读性和明显表达问题。"
        "不得冒充 character_plot。"
        "progression_assessment 可不提供。"
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
        "逐项核验 scene_plan.payload.progression_requirements。"
        "achieved_item 必须原样使用规划的 progress_type、target_key、before_state。"
        "after_state 必须包含对应 expected_after_state 的原文表达，evidence_text 必须是当前 draft.payload.text 的连续逐字子串。"
        "不得创造 character_development、world_expansion、emotional_response 等规划外类型或 target_key。"
        "未完成时放入 missing_items，不能换一个目标冒充完成。"
        "scene_state 必须包含 characters、location、time_context、events、relationship_changes、unresolved_threads。"
        "每个 achieved_item.after_state 必须同步进入 scene_state 的对应字段："
        "new_clue → events 或 unresolved_threads；"
        "character_state_change → characters 或 events；"
        "relationship_change → relationship_changes；"
        "thread_opened、thread_advanced、thread_closed → unresolved_threads 或 events。"
        "不能只在 progression_assessment 中写 after_state。"
    )


def reviewer_correction_instruction():
    return (
        "这是一次 ReviewerResult Contract 技术纠正，correction_attempt=1，禁止再次循环纠正。"
        "只纠正非法字段，不得改写 ScenePlan 或 Draft。"
        "progression_assessment.status 只能是 achieved、not_achieved、unclear。"
        "有至少一个合法 achieved_item 时，status 使用 achieved。"
        "没有达成项且存在 missing_items 时，status 使用 not_achieved。"
        "无法判断时使用 unclear。"
        "禁止 partial、partially_achieved、partial_success。"
        "每个 achieved_item 的 progress_type、target_key、before_state 必须原样匹配 ScenePlan。"
        "after_state 必须包含对应 expected_after_state 的原文表达。"
        "evidence_text 必须是 Draft 正文中的连续逐字子串；找不到证据就移入 missing_items，不能伪造。"
        + reviewer_findings_instruction()
        + "旧的 pass_with_notes、字符串 findings、或把可酌情精简写入 findings 的结构必须改成新结构。"
    )


def reviewer_evidence_instruction():
    return (
        "evidence_text只复制正文中的一个短而连续的原句或连续片段。"
        "建议控制在1～2句话。"
        "不得跨段拼接。"
        "不得删去中间句子。"
        "不得使用“……”或省略号代替原文。"
        "不得改写、翻译或总结。"
        "引号必须与正文一致，不要把 “ ” 改成 ‘ ’ 或 ASCII 引号。"
        "返回前确认Python语义上的：evidence_text in draft.payload.text。"
        "如果找不到连续原文，必须放入missing_items或status=unclear，不能声称achieved。"
    )


def arbiter_quality_instruction():
    return (
        "必须返回完整 QualityReport。"
        "review_completion_status 只能是 completed，不得返回 complete。"
        "status 只能是 passed 或 failed，不得返回 accepted_with_notes。"
        "routing_recommendation 只能是 complete 或 rewrite，不得返回 proceed_with_revisions。"
        "needs_arbiter 必须为 false。"
        "accepted_scene_state 必须包含 characters、location、time_context、events、relationship_changes、unresolved_threads。"
        "对照 scene_plan、draft、reviewer_results、preliminary_quality 和 progression_requirements 裁决争议。"
        "不得自行声明推进通过；progression 字段由后端核验写入。"
    )


def planning_progression_instruction():
    return (
        "before_state 必须直接复制 progression_baseline 中的现有状态，不得总结、改写、缩写或自行推断。"
        "真正新增的线索或悬念可以使用“未知”。"
        "expected_after_state 才描述本场预计的新状态。"
        "第一版优先只设置1～3项关键推进，不要一次塞入过多目标。"
        "new_clue：before_state 可为未知，否则必须存在于上一场 events 或 unresolved_threads。"
        "character_state_change：before_state 必须存在于上一场 characters 或 events。"
        "relationship_change：before_state 必须存在于上一场 relationship_changes。"
        "conflict_change：before_state 必须存在于 events、relationship_changes 或 unresolved_threads。"
        "decision_or_consequence：before_state 必须存在于 events 或 characters。"
        "thread_advanced 与 thread_closed：before_state 必须存在于 unresolved_threads 或 events。"
        "thread_opened：可使用未知，不能把已有悬念冒充新悬念。"
        "goal_milestone：before_state 必须存在于 events。"
        "characters、location、time_context、entrance_state、exit_state 必须在 payload 顶层独立出现。"
        "不能因为这些字段已出现在 entrance_state 或 exit_state 中就省略顶层字段。"
        + character_canon_instruction()
        + setting_canon_instruction()
    )


def planning_revision_instruction(feedback):
    reason = feedback.get("reason") or ""
    parts = [f"上一版因{reason}被打回。"]
    for item in feedback.get("failed_items") or []:
        progress_type = item.get("progress_type") or ""
        before = item.get("before_state")
        allowed = "、".join(item.get("allowed_fields") or [])
        parts.append(f"错项：类型{progress_type}，错误before_state为{before}，允许字段为{allowed or '未知'}。")
    parts.append("new_clue / thread_opened 可写「未知」。")
    parts.append("必须从允许字段原样复制，不得总结改写，不得从其他列挪句子。")
    parts.append("禁止交回同一套错误 before_state。")
    return "".join(parts)


def first_draft_writing_instruction():
    return (
        f"本次必须输出{MIN_CHARACTER_COUNT}～{MAX_CHARACTER_COUNT}个非空白字符，建议{PREFERRED_SOFT_MIN}～{PREFERRED_SOFT_MAX}。"
        "写成12～15个有效段落，每段承担动作、互动、阻力、转折或结果。"
        "禁止用大量环境描写凑字，禁止剧情摘要。"
        "完成至少一项 progression_requirements。"
        "必须遵守 scene_plan.must_not_happen、knowledge_boundary 和已批准世界规则。"
        + character_canon_instruction()
        + setting_canon_instruction()
        + f"超过{MAX_CHARACTER_COUNT}不合格。必须压到硬上限以下。不能只改word_count。"
        "正式长度以后端非空白实算为准。payload.word_count 不是官方计数。"
        "不能只把 word_count 改成 1287/1250 来充合格。"
        "返回前自检长度，但不能只改word_count。"
    )


MEMORY_REFUSAL_RETRY_NOTE = "正文已通过审查，按已确认场次状态记账。"
MEMORY_REFUSAL_RETRY_PACK_KEYS = ("character_canon", "setting_canon", "approved_facts", "previous_scene_state")


def memory_proposal_instruction():
    return (
        "这是虚构作品的场次状态记账，不是提取或保存真人记忆。"
        "记录本场已确认的虚构事实变化。"
        "若本场没有可记账的虚构事实变化，返回 payload {\"status\":\"skipped\",\"reason\":\"...\"}。"
        "不要提取、交出或写入真人记忆。"
    )


def memory_refusal_retry_instruction():
    return (
        "再次说明：这是虚构作品的场次状态记账，不是提取或保存真人记忆。"
        "只记录本场已确认的虚构事实变化；没有可记账变化时返回 skipped 并写明原因。"
        "不要提取、交出或写入真人记忆。"
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
