"""统一 Harness：Agent 只提交任务类型和输入，供应商差异留在适配器内。"""
from __future__ import annotations
import copy, json, sqlite3, time, uuid
from dataclasses import dataclass
from typing import Protocol
from datetime import datetime, timezone

def stamp(): return datetime.now(timezone.utc).isoformat()

class Adapter(Protocol):
    def complete(self, request: dict, timeout_seconds: float) -> dict: ...

REVIEWER_ROLE_BY_TASK = {
    "review_world": "world_consistency",
    "review_plot": "character_plot",
    "review_style": "language_experience",
}
REVIEWER_ROLES = frozenset(REVIEWER_ROLE_BY_TASK.values())
REVIEWER_RESULTS = frozenset({"passed", "failed"})
REVIEWER_SEVERITIES = frozenset({"ordinary", "serious"})
REVIEWER_IMPACT_SCOPES = frozenset({"local", "cross_scene", "cross_chapter", "book"})
REVIEWER_PROGRESSION_STATUSES = frozenset({"achieved", "not_achieved", "unclear"})
REVIEWER_SCENE_STATE_FIELDS = (
    "characters", "location", "time_context", "events", "relationship_changes", "unresolved_threads",
)
REVIEWER_ACHIEVED_ITEM_FIELDS = (
    "progress_type", "target_key", "before_state", "after_state", "evidence_text", "evidence_location",
)
PLANNING_PROMPT_VERSION = "planning_progression_v3"
SCENE_PLAN_REQUIRED_FIELDS = (
    "scene_goal", "entrance_state", "exit_state", "characters", "location", "time_context",
    "conflict", "action_beats", "must_happen", "must_not_happen", "knowledge_boundary",
    "target_word_count", "acceptance_criteria", "validation_result", "ready_for_writing",
    "progression_requirements",
)
SCENE_PLAN_NONEMPTY_FIELDS = (
    "scene_goal", "entrance_state", "exit_state", "characters", "location", "time_context",
    "conflict", "action_beats", "must_happen", "must_not_happen", "knowledge_boundary",
    "acceptance_criteria", "validation_result",
)
PLANNING_QUALITY_REASONS = (
    "plan_required_fields_missing",
    "plan_required_fields_empty",
    "plan_not_ready",
    "plan_target_word_count_invalid",
    "plan_progression_missing",
    "plan_before_state_conflicts_previous_scene",
)
REVIEWER_PROMPT_VERSION = "reviewer_contract_v8"
REVIEWER_NORMALIZATION_RULE = "unwrap_character_plot_progression_assessment_v1"
REVIEWER_ROLE_NORMALIZATION_RULE = "normalize_assigned_task_name_to_reviewer_role_v1"
EVIDENCE_QUOTE_NORMALIZATION_RULE = "normalize_quote_style_to_exact_draft_v1"
QUOTE_STYLE_TRANSLATION = str.maketrans({
    "\u2018": '"', "\u2019": '"',
    "\u201c": '"', "\u201d": '"',
    "'": '"',
})
ARBITER_PROMPT_VERSION = "arbiter_contract_v2"
ARBITER_STATUSES = frozenset({"passed", "failed"})
ARBITER_ROUTING = frozenset({"complete", "rewrite"})


@dataclass(frozen=True)
class ModelProfile:
    provider: str; model: str; timeout_seconds: float = 60; technical_retries: int = 1; max_output_tokens: int = 4096; budget_limit: float | None = None; prompt_version: str = "v1"

class ContractFormatError(ValueError):
    def __init__(self, message, *, call_id=None, response=None, code='CONTRACT_FORMAT_INVALID',
                 planning_reason=None, missing_fields=None, empty_fields=None):
        super().__init__(message); self.call_id=call_id; self.response=response; self.code=code
        self.planning_reason = planning_reason
        self.missing_fields = list(missing_fields or [])
        self.empty_fields = list(empty_fields or [])

class Harness:
    def __init__(self, db_path, routes: dict[str, ModelProfile], adapters: dict[str, Adapter], fallback: dict[str, str] | None = None):
        self.db = sqlite3.connect(str(db_path), check_same_thread=False); self.routes=routes; self.adapters=adapters; self.fallback=fallback or {}

    def run(self, *, task_id, agent_task_type, input_payload, contract_type, contract_validator):
        if agent_task_type not in self.routes: raise ValueError("NO_MODEL_ROUTE")
        from backend.siliconflow import ModelResponseParseError, json_mode_enabled
        profile=self.routes[agent_task_type]; call_id="hc_"+uuid.uuid4().hex; started=stamp(); request={"task_type":agent_task_type,"contract_type":contract_type,"contract_version":"v1","input":input_payload,"max_output_tokens":profile.max_output_tokens,"prompt_version":profile.prompt_version,"model":profile.model,"timeout_seconds":profile.timeout_seconds,"json_mode":json_mode_enabled()}
        context=input_payload.get('context_pack') if isinstance(input_payload,dict) else None
        if context and (context.get('book_id') != input_payload.get('book_id', context.get('book_id')) or context.get('scene_id') != input_payload.get('scene_id', context.get('scene_id'))): raise ContractFormatError('ContextPack scope mismatch', code='CONTRACT_PAYLOAD_INVALID')
        self.db.execute("INSERT INTO harness_calls(harness_call_id,task_id,agent_type,provider,model,request_json,status,started_at) VALUES (?,?,?,?,?,?,?,?)", (call_id,task_id,agent_task_type,profile.provider,profile.model,json.dumps(request),"running",started)); self.db.commit()
        providers=[profile.provider] + ([self.fallback[agent_task_type]] if agent_task_type in self.fallback else [])
        last=None
        for provider in providers:
            for attempt in range(profile.technical_retries+1):
                try:
                    response=self.adapters[provider].complete(request, profile.timeout_seconds)
                    try:
                        if contract_type == "ReviewerResult":
                            normalize_reviewer_role(response, agent_task_type)
                            normalize_reviewer_result(response, agent_task_type)
                            normalize_reviewer_evidence(response, input_payload)
                        contract_validator(response, contract_type)
                        if contract_type == "ScenePlan":
                            validate_scene_plan_against_input(response, input_payload)
                        if contract_type == "ReviewerResult":
                            validate_reviewer_result_for_task(response, agent_task_type)
                            validate_reviewer_result_against_input(response, agent_task_type, input_payload)
                        if contract_type == "QualityReport":
                            validate_quality_report_for_task(response, agent_task_type)
                    except ContractFormatError as exc:
                        self.db.execute("UPDATE harness_calls SET response_json=? WHERE harness_call_id=?", (json.dumps(response, ensure_ascii=False),call_id)); self.db.commit()
                        raise ContractFormatError(
                            str(exc), call_id=call_id, response=response, code=exc.code,
                            planning_reason=getattr(exc, 'planning_reason', None),
                            missing_fields=getattr(exc, 'missing_fields', None),
                            empty_fields=getattr(exc, 'empty_fields', None),
                        ) from exc
                    self.db.execute("UPDATE harness_calls SET response_json=?,status=?,completed_at=? WHERE harness_call_id=?", (json.dumps(response),"success",stamp(),call_id)); self.db.commit(); return {"harness_call_id":call_id,"response":response,"provider":provider}
                except ContractFormatError as exc:
                    self._finish(call_id,"contract_invalid",_contract_invalid_error(exc)); raise
                except ModelResponseParseError as exc:
                    last=exc; time.sleep(0)
                except Exception as exc: last=exc; time.sleep(0)
        if isinstance(last, ModelResponseParseError):
            self._finish(call_id,"failed",last.to_audit()); raise last
        self._finish(call_id,"failed",{"error":str(last) if last else "TECHNICAL_ERROR"}); raise RuntimeError("TECHNICAL_ERROR")

    def _finish(self, call_id, status, error):
        self.db.execute("UPDATE harness_calls SET status=?,error_json=?,completed_at=? WHERE harness_call_id=?", (status,json.dumps(error),stamp(),call_id)); self.db.commit()
    def close(self): self.db.close()

class MockAdapter:
    def __init__(self, response): self.response=response
    def complete(self, request, timeout_seconds): return self.response

def _scene_plan_field_empty(value):
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return value in ([], {})


def classify_scene_plan_quality(response):
    """Business ScenePlan failures. Never copies nested entrance_state/exit_state into the top level."""
    if not isinstance(response, dict):
        return None
    payload = response.get('payload')
    if not isinstance(payload, dict):
        return None
    missing = [key for key in SCENE_PLAN_REQUIRED_FIELDS if key not in payload]
    empty = [key for key in SCENE_PLAN_NONEMPTY_FIELDS if key in payload and _scene_plan_field_empty(payload.get(key))]
    if missing:
        return {
            'reason': 'plan_required_fields_missing',
            'missing_fields': missing,
            'empty_fields': empty,
            'message': 'missing payload fields: ' + ','.join(missing),
        }
    if empty:
        return {
            'reason': 'plan_required_fields_empty',
            'missing_fields': [],
            'empty_fields': empty,
            'message': 'empty required fields: ' + ','.join(empty),
        }
    if payload.get('ready_for_writing') is not True:
        return {
            'reason': 'plan_not_ready',
            'missing_fields': [],
            'empty_fields': [],
            'message': 'ScenePlan is not ready_for_writing',
        }
    if payload.get('target_word_count') != 1250:
        return {
            'reason': 'plan_target_word_count_invalid',
            'missing_fields': [],
            'empty_fields': [],
            'message': 'ScenePlan target_word_count must be exactly 1250',
        }
    from backend.progression import validate_requirements
    try:
        validate_requirements(payload.get('progression_requirements'))
    except ValueError as exc:
        return {
            'reason': 'plan_progression_missing',
            'missing_fields': [],
            'empty_fields': [],
            'message': str(exc) or 'plan_progression_missing',
        }
    return None


def _contract_invalid_error(exc):
    error = {"error": exc.code, "reason": str(exc), "response_shape": shape(exc.response)}
    if getattr(exc, 'planning_reason', None):
        error['planning_reason'] = exc.planning_reason
    if getattr(exc, 'missing_fields', None):
        error['missing_fields'] = list(exc.missing_fields)
    if getattr(exc, 'empty_fields', None):
        error['empty_fields'] = list(exc.empty_fields)
    return error


def required_fields_validator(response, contract_type):
    if not isinstance(response, dict): raise ContractFormatError("response is not an object")
    if response.get("contract_type") != contract_type: raise ContractFormatError(f"contract_type mismatch: expected {contract_type}, got {response.get('contract_type')!r}")
    if not isinstance(response.get("contract_version"), str): raise ContractFormatError("contract_version missing or invalid")
    if not isinstance(response.get("payload"), dict): raise ContractFormatError("payload missing or invalid", code='CONTRACT_PAYLOAD_INVALID')
    if contract_type == 'ScenePlan':
        classification = classify_scene_plan_quality(response)
        if classification:
            raise ContractFormatError(
                classification['message'], code='CONTRACT_PAYLOAD_INVALID',
                planning_reason=classification['reason'],
                missing_fields=classification['missing_fields'],
                empty_fields=classification['empty_fields'],
            )
        return
    # Memory extraction has one explicit non-proposal outcome.  It is valid
    # only when the model says no durable fact was found and explains why.
    if contract_type == 'MemoryProposal' and response['payload'].get('status') == 'skipped':
        reason = response['payload'].get('reason')
        if not isinstance(reason, str) or not reason.strip():
            raise ContractFormatError('no_memory_needed requires a non-empty reason', code='CONTRACT_PAYLOAD_INVALID')
        return
    required = {
        'CreativeBrief': ['title','genre','theme','target_length','main_characters','character_relationships','world_background','core_rules','main_conflict','style_requirements','ending_direction','special_requirements'],
        'ScenePlan': ['scene_goal','entrance_state','exit_state','characters','location','time_context','conflict','action_beats','must_happen','must_not_happen','knowledge_boundary','target_word_count','acceptance_criteria','validation_result','ready_for_writing','progression_requirements'],
        'ProseDraft': ['text','word_count','target_word_count','complete','writer_self_check'],
        'QualityReport': ['review_completion_status','reviewer_results','deduped_issue_count','ordinary_issue_count','serious_issue_count','has_true_conflict','needs_arbiter','routing_recommendation','accepted_scene_state','status'],
        'MemoryProposal': ['memory_type','target_scope','target_key','action','before_value','after_value','evidence','evidence_location','change_reason','conflict_status','write_policy','status']
        ,'ReviewerResult': ['reviewer_role','result','findings','suggestions','issue_count','severity','impact_scope','true_conflict_candidate','scene_state']
    }.get(contract_type, [])
    missing=[key for key in required if key not in response['payload']]
    if missing: raise ContractFormatError(f"missing payload fields: {','.join(missing)}", code='CONTRACT_PAYLOAD_INVALID')
    if contract_type == 'QualityReport':
        payload=response['payload']
        if payload['review_completion_status'] not in ('pending','completed','partial','failed'): raise ContractFormatError('invalid review_completion_status', code='CONTRACT_PAYLOAD_INVALID')
        if payload['status'] not in ('passed','failed','needs_arbiter'): raise ContractFormatError('invalid status', code='CONTRACT_PAYLOAD_INVALID')
        if not isinstance(payload['routing_recommendation'], str) or not payload['routing_recommendation'].strip(): raise ContractFormatError('routing_recommendation is empty', code='CONTRACT_PAYLOAD_INVALID')
        if not isinstance(payload['accepted_scene_state'], dict) or not payload['accepted_scene_state'] or payload['accepted_scene_state'] == {'reviewed': True}: raise ContractFormatError('accepted_scene_state is empty or placeholder', code='CONTRACT_PAYLOAD_INVALID')
        required_state_fields=('characters','location','time_context','events','relationship_changes','unresolved_threads')
        if any(key not in payload['accepted_scene_state'] for key in required_state_fields): raise ContractFormatError('accepted_scene_state missing real scene state fields', code='CONTRACT_PAYLOAD_INVALID')
        if any(not payload['accepted_scene_state'].get(key) for key in ('characters','location','time_context','events')): raise ContractFormatError('accepted_scene_state missing core real scene state', code='CONTRACT_PAYLOAD_INVALID')
    if contract_type == 'ReviewerResult':
        validate_reviewer_result(response['payload'])
    if contract_type == 'MemoryProposal':
        payload=response['payload']
        if any(not str(payload.get(key,'')).strip() for key in ('memory_type','target_scope','target_key','action','evidence','evidence_location','change_reason')): raise ContractFormatError('MemoryProposal contains empty required fields', code='CONTRACT_PAYLOAD_INVALID')
        target_key=payload['target_key']
        if not isinstance(target_key,str): raise ContractFormatError('target_key must be a concrete string identifier', code='CONTRACT_PAYLOAD_INVALID')
        normalized=target_key.strip().lower()
        if normalized in ('fact','event','memory','scene','unknown','none','context','contextpack','context_pack') or any(token in normalized for token in ('context_pack','contextpack','pack_v','.md','.json')):
            raise ContractFormatError('target_key must identify a concrete character, location, event, or scene fact', code='CONTRACT_PAYLOAD_INVALID')
        if payload['action'] not in ('create','update','delete'): raise ContractFormatError('invalid action', code='CONTRACT_PAYLOAD_INVALID')
        if payload['memory_type'] not in ('scene_fact','narrative_event','world_rule','character_detail'): raise ContractFormatError('invalid memory_type', code='CONTRACT_PAYLOAD_INVALID')
        if payload['target_scope'] not in ('scene_memory','book_memory','character_memory'): raise ContractFormatError('invalid target_scope', code='CONTRACT_PAYLOAD_INVALID')
        if payload['conflict_status'] not in ('none','conflict','resolved'): raise ContractFormatError('invalid conflict_status', code='CONTRACT_PAYLOAD_INVALID')
        if payload['write_policy'] not in ('auto_save','human_confirmation','never_auto_write'): raise ContractFormatError('invalid write_policy', code='CONTRACT_PAYLOAD_INVALID')
        if payload['status'] not in ('pending','approved','rejected','written','conflict'): raise ContractFormatError('invalid status', code='CONTRACT_PAYLOAD_INVALID')
        if payload['memory_type']=='scene_fact' and (payload['target_scope']!='scene_memory' or payload['write_policy']!='auto_save'): raise ContractFormatError('scene_fact permission mapping invalid', code='CONTRACT_PAYLOAD_INVALID')
        if payload['memory_type'] in ('narrative_event','world_rule') and payload['write_policy']!='human_confirmation': raise ContractFormatError('memory type requires human_confirmation', code='CONTRACT_PAYLOAD_INVALID')
        if payload['memory_type']=='narrative_event' and payload['target_scope']!='book_memory': raise ContractFormatError('narrative_event requires book_memory', code='CONTRACT_PAYLOAD_INVALID')
        if payload['memory_type']=='world_rule' and payload['target_scope']!='book_memory': raise ContractFormatError('world_rule requires book_memory', code='CONTRACT_PAYLOAD_INVALID')
        if payload['memory_type']=='character_detail' and payload['target_scope']!='character_memory': raise ContractFormatError('character_detail requires character_memory', code='CONTRACT_PAYLOAD_INVALID')
        if payload['memory_type']=='character_detail' and payload['write_policy']!='human_confirmation': raise ContractFormatError('character_detail requires human_confirmation', code='CONTRACT_PAYLOAD_INVALID')
        if payload['memory_type']=='narrative_event' and payload['target_scope']=='story' and payload['write_policy']=='never_auto_write': raise ContractFormatError('narrative_event story scope cannot default to never_auto_write', code='CONTRACT_PAYLOAD_INVALID')
    if contract_type == 'ProseDraft':
        payload=response['payload']
        if not isinstance(payload['text'], str) or not payload['text'].strip() or payload['word_count'] <= 0 or payload['target_word_count'] <= 0 or payload['complete'] is not True: raise ContractFormatError('ProseDraft is empty or incomplete', code='CONTRACT_PAYLOAD_INVALID')

def _same_structure(left, right):
    return json.dumps(left, ensure_ascii=False, sort_keys=True) == json.dumps(right, ensure_ascii=False, sort_keys=True)


def normalize_reviewer_role(response, agent_task_type):
    """Map assigned task name to formal role only when they are the same string."""
    if not isinstance(response, dict):
        return 0
    audit = response.get('reviewer_role_normalization_audit')
    if isinstance(audit, dict) and audit.get('rule') == REVIEWER_ROLE_NORMALIZATION_RULE:
        return 0
    payload = response.get('payload')
    if not isinstance(payload, dict):
        return 0
    actual = payload.get('reviewer_role')
    expected = REVIEWER_ROLE_BY_TASK.get(agent_task_type)
    if expected is None or actual != agent_task_type:
        return 0
    payload['reviewer_role'] = expected
    response['reviewer_role_normalization_audit'] = {
        'rule': REVIEWER_ROLE_NORMALIZATION_RULE,
        'original_reviewer_role': actual,
        'normalized_reviewer_role': expected,
        'assigned_task_type': agent_task_type,
    }
    response['reviewer_role_normalization_applied'] = True
    response['reviewer_role_normalization_count'] = int(response.get('reviewer_role_normalization_count') or 0) + 1
    return 1


def normalize_reviewer_result(response, agent_task_type):
    """Unwrap one known V4 Flash nesting. Never rewrite business values."""
    if agent_task_type != 'review_plot' or not isinstance(response, dict):
        return False
    payload = response.get('payload')
    if not isinstance(payload, dict) or payload.get('reviewer_role') != 'character_plot':
        return False
    audit = response.get('contract_normalization_audit')
    if isinstance(audit, dict) and audit.get('rule') == REVIEWER_NORMALIZATION_RULE:
        return False
    wrapper = payload.get('character_plot')
    top = payload.get('progression_assessment')
    if wrapper is None:
        return False
    if not isinstance(wrapper, dict):
        if top is None:
            raise ContractFormatError('payload.character_plot is not an object', code='CONTRACT_PAYLOAD_INVALID')
        return False
    nested = wrapper.get('progression_assessment')
    if nested is None:
        return False
    if not isinstance(nested, dict):
        raise ContractFormatError('payload.character_plot.progression_assessment is not an object', code='CONTRACT_PAYLOAD_INVALID')
    if top is not None:
        if not _same_structure(top, nested):
            raise ContractFormatError(
                'progression_assessment conflicts with nested character_plot.progression_assessment',
                code='CONTRACT_PAYLOAD_INVALID',
            )
        return False
    payload['progression_assessment'] = copy.deepcopy(nested)
    response['contract_normalization_audit'] = {
        'rule': REVIEWER_NORMALIZATION_RULE,
        'source_path': 'payload.character_plot.progression_assessment',
        'destination_path': 'payload.progression_assessment',
    }
    return True


def validate_reviewer_result(payload):
    """Enum and shape checks for every ReviewerResult. Role-to-task binding is separate."""
    if payload.get('reviewer_role') not in REVIEWER_ROLES:
        raise ContractFormatError('invalid reviewer_role', code='CONTRACT_PAYLOAD_INVALID')
    if payload.get('result') not in REVIEWER_RESULTS:
        raise ContractFormatError('invalid result', code='CONTRACT_PAYLOAD_INVALID')
    if payload.get('severity') not in REVIEWER_SEVERITIES:
        raise ContractFormatError('invalid severity', code='CONTRACT_PAYLOAD_INVALID')
    if payload.get('impact_scope') not in REVIEWER_IMPACT_SCOPES:
        raise ContractFormatError('invalid impact_scope', code='CONTRACT_PAYLOAD_INVALID')
    findings = payload.get('findings')
    suggestions = payload.get('suggestions')
    if not isinstance(findings, list):
        raise ContractFormatError('findings must be an array', code='CONTRACT_PAYLOAD_INVALID')
    if not isinstance(suggestions, list):
        raise ContractFormatError('suggestions must be an array', code='CONTRACT_PAYLOAD_INVALID')
    issue_count = payload.get('issue_count')
    if not isinstance(issue_count, int) or isinstance(issue_count, bool) or issue_count < 0:
        raise ContractFormatError('invalid issue_count', code='CONTRACT_PAYLOAD_INVALID')
    if issue_count != len(findings):
        raise ContractFormatError('issue_count must equal findings length', code='CONTRACT_PAYLOAD_INVALID')
    if findings:
        if payload.get('result') != 'failed':
            raise ContractFormatError('non-empty findings require result=failed', code='CONTRACT_PAYLOAD_INVALID')
    elif payload.get('result') != 'passed':
        raise ContractFormatError('empty findings require result=passed', code='CONTRACT_PAYLOAD_INVALID')
    if not isinstance(payload.get('true_conflict_candidate'), bool):
        raise ContractFormatError('invalid true_conflict_candidate', code='CONTRACT_PAYLOAD_INVALID')
    scene_state = payload.get('scene_state')
    if not isinstance(scene_state, dict) or any(key not in scene_state for key in REVIEWER_SCENE_STATE_FIELDS):
        raise ContractFormatError('scene_state missing required fields', code='CONTRACT_PAYLOAD_INVALID')
    assessment = payload.get('progression_assessment')
    if payload['reviewer_role'] == 'character_plot':
        _validate_progression_assessment(assessment, required=True)
    elif assessment is not None:
        # Optional on world/style. If supplied it still cannot use illegal statuses,
        # and it never replaces character_plot as the formal progression authority.
        _validate_progression_assessment(assessment, required=False)


def _validate_progression_assessment(assessment, *, required):
    if assessment is None and not required:
        return
    if not isinstance(assessment, dict) or assessment.get('status') not in REVIEWER_PROGRESSION_STATUSES:
        raise ContractFormatError('invalid progression_assessment', code='CONTRACT_PAYLOAD_INVALID')
    if not isinstance(assessment.get('achieved_items', []), list) or not isinstance(assessment.get('missing_items', []), list):
        raise ContractFormatError('invalid progression_assessment items', code='CONTRACT_PAYLOAD_INVALID')
    for item in assessment.get('achieved_items', []):
        if not isinstance(item, dict) or any(key not in item for key in REVIEWER_ACHIEVED_ITEM_FIELDS):
            raise ContractFormatError('invalid achieved progression item', code='CONTRACT_PAYLOAD_INVALID')


def validate_reviewer_result_for_task(response, agent_task_type):
    """Bind ReviewerResult.reviewer_role to the current harness task before success."""
    expected = REVIEWER_ROLE_BY_TASK.get(agent_task_type)
    if expected is None:
        raise ContractFormatError(f'unknown reviewer task type: {agent_task_type}', code='CONTRACT_PAYLOAD_INVALID')
    payload = response.get('payload') if isinstance(response, dict) else None
    if not isinstance(payload, dict):
        raise ContractFormatError('payload missing or invalid', code='CONTRACT_PAYLOAD_INVALID')
    actual = payload.get('reviewer_role')
    if actual != expected:
        raise ContractFormatError(
            f'reviewer_role {actual!r} does not match task {agent_task_type}',
            code='CONTRACT_PAYLOAD_INVALID',
        )


def _input_draft_text(input_payload):
    if not isinstance(input_payload, dict):
        return None
    draft = input_payload.get('draft')
    if isinstance(draft, str):
        return draft
    if not isinstance(draft, dict):
        return None
    payload = draft.get('payload') if isinstance(draft.get('payload'), dict) else draft
    text = payload.get('text')
    return text if isinstance(text, str) else None


def _input_requirements(input_payload):
    if not isinstance(input_payload, dict):
        return []
    plan = input_payload.get('scene_plan')
    if not isinstance(plan, dict):
        return []
    payload = plan.get('payload') if isinstance(plan.get('payload'), dict) else plan
    requirements = payload.get('progression_requirements')
    return requirements if isinstance(requirements, list) else []


def _same_requirement(item, requirement):
    return (item.get('progress_type') == requirement.get('progress_type')
            and item.get('target_key') == requirement.get('target_key'))


def _matching_requirement(item, requirements):
    return next((requirement for requirement in requirements if _same_requirement(item, requirement)), None)


def _item_key(item):
    return (item.get('progress_type'), item.get('target_key'))


def _location_from_plan_or_pack(location):
    if not isinstance(location, str) or not location.strip():
        return True
    normalized = location.lower().replace('_', '').replace('-', '').replace(' ', '')
    return 'contextpack' in normalized or 'sceneplan' in normalized


def _contiguous_draft_evidence(evidence, draft_text):
    return isinstance(evidence, str) and bool(evidence.strip()) and isinstance(draft_text, str) and evidence in draft_text


def _normalize_quote_style(text):
    return text.translate(QUOTE_STYLE_TRANSLATION) if isinstance(text, str) else text


def _unique_quote_normalized_span(evidence, draft_text):
    """Map only quote glyphs, then require exactly one same-length hit in the draft."""
    if not isinstance(evidence, str) or not evidence.strip() or not isinstance(draft_text, str):
        return None
    normalized_evidence = _normalize_quote_style(evidence)
    normalized_draft = _normalize_quote_style(draft_text)
    if len(normalized_evidence) != len(evidence) or len(normalized_draft) != len(draft_text):
        return None
    start = normalized_draft.find(normalized_evidence)
    if start < 0 or normalized_draft.find(normalized_evidence, start + 1) >= 0:
        return None
    return start, start + len(evidence)


def normalize_reviewer_evidence(response, input_payload):
    """Replace quote-style-only evidence with the exact current draft substring."""
    if not isinstance(response, dict):
        return 0
    payload = response.get('payload')
    if not isinstance(payload, dict):
        return 0
    assessment = payload.get('progression_assessment')
    if not isinstance(assessment, dict):
        return 0
    draft_text = _input_draft_text(input_payload)
    count = 0
    for item in assessment.get('achieved_items') or []:
        if not isinstance(item, dict):
            continue
        audit = item.get('evidence_normalization_audit')
        if isinstance(audit, dict) and audit.get('rule') == EVIDENCE_QUOTE_NORMALIZATION_RULE:
            continue
        evidence = item.get('evidence_text')
        if not isinstance(evidence, str) or not evidence.strip():
            continue
        if isinstance(draft_text, str) and evidence in draft_text:
            continue
        span = _unique_quote_normalized_span(evidence, draft_text)
        if span is None:
            continue
        start, end = span
        exact = draft_text[start:end]
        item['evidence_normalization_audit'] = {
            'rule': EVIDENCE_QUOTE_NORMALIZATION_RULE,
            'original_evidence_text': evidence,
            'exact_draft_evidence_text': exact,
            'start_offset': start,
            'end_offset': end,
        }
        item['evidence_text'] = exact
        count += 1
    if count:
        response['reviewer_evidence_normalization_applied'] = True
        response['reviewer_evidence_normalization_count'] = int(response.get('reviewer_evidence_normalization_count') or 0) + count
    return count


def validate_scene_plan_against_input(response, input_payload):
    """Follow-up ScenePlan before_state must copy the previous confirmed baseline."""
    from backend.progression import validate_scene_plan_against_input as _validate
    try:
        _validate(response, input_payload)
    except ValueError as exc:
        from backend.progression import PLAN_BEFORE_STATE_REASON
        reason = PLAN_BEFORE_STATE_REASON if PLAN_BEFORE_STATE_REASON in str(exc) else None
        raise ContractFormatError(str(exc), code='CONTRACT_PAYLOAD_INVALID', planning_reason=reason) from exc


def validate_reviewer_result_against_input(response, agent_task_type, input_payload):
    """Plot-reviewer progression items must match the current ScenePlan and draft text."""
    if agent_task_type != 'review_plot':
        return
    normalize_reviewer_evidence(response, input_payload)
    payload = response.get('payload') if isinstance(response, dict) else None
    if not isinstance(payload, dict) or payload.get('reviewer_role') != 'character_plot':
        raise ContractFormatError('character_plot progression validation requires a plot payload', code='CONTRACT_PAYLOAD_INVALID')
    assessment = payload.get('progression_assessment')
    if not isinstance(assessment, dict):
        raise ContractFormatError('invalid progression_assessment', code='CONTRACT_PAYLOAD_INVALID')
    achieved = assessment.get('achieved_items') or []
    missing = assessment.get('missing_items') or []
    if not isinstance(achieved, list) or not isinstance(missing, list):
        raise ContractFormatError('invalid progression_assessment items', code='CONTRACT_PAYLOAD_INVALID')
    status = assessment.get('status')
    if status == 'achieved' and not achieved:
        raise ContractFormatError('achieved assessment has no achieved_items', code='CONTRACT_PAYLOAD_INVALID')
    if status == 'not_achieved' and not missing:
        raise ContractFormatError('not_achieved assessment has no missing_items', code='CONTRACT_PAYLOAD_INVALID')
    seen = set()
    for item in list(achieved) + list(missing):
        if not isinstance(item, dict):
            raise ContractFormatError('invalid progression item', code='CONTRACT_PAYLOAD_INVALID')
        key = _item_key(item)
        if key in seen:
            raise ContractFormatError('achieved and missing items repeat the same type/key', code='CONTRACT_PAYLOAD_INVALID')
        seen.add(key)
    from backend.progression import canonical
    requirements = _input_requirements(input_payload)
    draft_text = _input_draft_text(input_payload)
    for item in missing:
        if _matching_requirement(item, requirements) is None:
            raise ContractFormatError('missing_item invents progress_type or target_key', code='CONTRACT_PAYLOAD_INVALID')
    for item in achieved:
        requirement = _matching_requirement(item, requirements)
        if requirement is None:
            raise ContractFormatError('achieved_item invents progress_type or target_key', code='CONTRACT_PAYLOAD_INVALID')
        if canonical(item.get('before_state')) != canonical(requirement.get('before_state')):
            raise ContractFormatError('achieved_item.before_state does not match ScenePlan', code='CONTRACT_PAYLOAD_INVALID')
        from backend.progression import contains_state
        if not contains_state(item.get('after_state'), requirement.get('expected_after_state')):
            raise ContractFormatError('achieved_item.after_state does not match expected_after_state', code='CONTRACT_PAYLOAD_INVALID')
        evidence = item.get('evidence_text')
        if not isinstance(evidence, str) or not evidence.strip():
            raise ContractFormatError('achieved_item.evidence_text is empty', code='CONTRACT_PAYLOAD_INVALID')
        if _location_from_plan_or_pack(item.get('evidence_location')):
            raise ContractFormatError('achieved_item.evidence_location is not current draft', code='CONTRACT_PAYLOAD_INVALID')
        if not _contiguous_draft_evidence(evidence, draft_text):
            raise ContractFormatError('achieved_item.evidence_text is not a contiguous draft substring', code='CONTRACT_PAYLOAD_INVALID')


def validate_quality_report_for_task(response, agent_task_type):
    """Arbiter must return a complete, routable QualityReport before success."""
    if agent_task_type != "arbiter":
        return
    payload = response.get("payload") if isinstance(response, dict) else None
    if not isinstance(payload, dict):
        raise ContractFormatError("payload missing or invalid", code="CONTRACT_PAYLOAD_INVALID")
    if payload.get("review_completion_status") != "completed":
        raise ContractFormatError("invalid review_completion_status", code="CONTRACT_PAYLOAD_INVALID")
    if payload.get("status") not in ARBITER_STATUSES:
        raise ContractFormatError("invalid status", code="CONTRACT_PAYLOAD_INVALID")
    if payload.get("routing_recommendation") not in ARBITER_ROUTING:
        raise ContractFormatError("invalid routing_recommendation", code="CONTRACT_PAYLOAD_INVALID")
    if payload.get("needs_arbiter") is not False:
        raise ContractFormatError("arbiter QualityReport must set needs_arbiter false", code="CONTRACT_PAYLOAD_INVALID")


def shape(value):
    if not isinstance(value, dict): return type(value).__name__
    return {k: type(v).__name__ for k,v in value.items()}
