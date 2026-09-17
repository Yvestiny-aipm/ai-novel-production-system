"""统一 Harness：Agent 只提交任务类型和输入，供应商差异留在适配器内。"""
from __future__ import annotations
import json, sqlite3, time, uuid
from dataclasses import dataclass
from typing import Protocol
from datetime import datetime, timezone

def stamp(): return datetime.now(timezone.utc).isoformat()

class Adapter(Protocol):
    def complete(self, request: dict, timeout_seconds: float) -> dict: ...

@dataclass(frozen=True)
class ModelProfile:
    provider: str; model: str; timeout_seconds: float = 60; technical_retries: int = 1; max_output_tokens: int = 4096; budget_limit: float | None = None; prompt_version: str = "v1"

class ContractFormatError(ValueError):
    def __init__(self, message, *, call_id=None, response=None, code='CONTRACT_FORMAT_INVALID'):
        super().__init__(message); self.call_id=call_id; self.response=response; self.code=code

class Harness:
    def __init__(self, db_path, routes: dict[str, ModelProfile], adapters: dict[str, Adapter], fallback: dict[str, str] | None = None):
        self.db = sqlite3.connect(str(db_path), check_same_thread=False); self.routes=routes; self.adapters=adapters; self.fallback=fallback or {}

    def run(self, *, task_id, agent_task_type, input_payload, contract_type, contract_validator):
        if agent_task_type not in self.routes: raise ValueError("NO_MODEL_ROUTE")
        profile=self.routes[agent_task_type]; call_id="hc_"+uuid.uuid4().hex; started=stamp(); request={"task_type":agent_task_type,"contract_type":contract_type,"contract_version":"v1","input":input_payload,"max_output_tokens":profile.max_output_tokens,"prompt_version":profile.prompt_version}
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
                        contract_validator(response, contract_type)
                    except ContractFormatError as exc:
                        self.db.execute("UPDATE harness_calls SET response_json=? WHERE harness_call_id=?", (json.dumps(response, ensure_ascii=False),call_id)); self.db.commit()
                        raise ContractFormatError(str(exc), call_id=call_id, response=response, code=exc.code) from exc
                    self.db.execute("UPDATE harness_calls SET response_json=?,status=?,completed_at=? WHERE harness_call_id=?", (json.dumps(response),"success",stamp(),call_id)); self.db.commit(); return {"harness_call_id":call_id,"response":response,"provider":provider}
                except ContractFormatError as exc:
                    self._finish(call_id,"contract_invalid",{"error":exc.code,"reason":str(exc),"response_shape":shape(exc.response)}); raise
                except Exception as exc: last=exc; time.sleep(0)
        self._finish(call_id,"failed",{"error":str(last) if last else "TECHNICAL_ERROR"}); raise RuntimeError("TECHNICAL_ERROR")

    def _finish(self, call_id, status, error):
        self.db.execute("UPDATE harness_calls SET status=?,error_json=?,completed_at=? WHERE harness_call_id=?", (status,json.dumps(error),stamp(),call_id)); self.db.commit()
    def close(self): self.db.close()

class MockAdapter:
    def __init__(self, response): self.response=response
    def complete(self, request, timeout_seconds): return self.response

def required_fields_validator(response, contract_type):
    if not isinstance(response, dict): raise ContractFormatError("response is not an object")
    if response.get("contract_type") != contract_type: raise ContractFormatError(f"contract_type mismatch: expected {contract_type}, got {response.get('contract_type')!r}")
    if not isinstance(response.get("contract_version"), str): raise ContractFormatError("contract_version missing or invalid")
    if not isinstance(response.get("payload"), dict): raise ContractFormatError("payload missing or invalid", code='CONTRACT_PAYLOAD_INVALID')
    # Memory extraction has one explicit non-proposal outcome.  It is valid
    # only when the model says no durable fact was found and explains why.
    if contract_type == 'MemoryProposal' and response['payload'].get('status') == 'skipped':
        reason = response['payload'].get('reason')
        if not isinstance(reason, str) or not reason.strip():
            raise ContractFormatError('no_memory_needed requires a non-empty reason', code='CONTRACT_PAYLOAD_INVALID')
        return
    required = {
        'CreativeBrief': ['title','genre','theme','target_length','main_characters','character_relationships','world_background','core_rules','main_conflict','style_requirements','ending_direction','special_requirements'],
        'ScenePlan': ['scene_goal','entrance_state','exit_state','characters','location','time_context','conflict','action_beats','must_happen','must_not_happen','knowledge_boundary','target_word_count','acceptance_criteria','validation_result','ready_for_writing'],
        'ProseDraft': ['text','word_count','target_word_count','complete','writer_self_check'],
        'QualityReport': ['review_completion_status','reviewer_results','deduped_issue_count','ordinary_issue_count','serious_issue_count','has_true_conflict','needs_arbiter','routing_recommendation','accepted_scene_state','status'],
        'MemoryProposal': ['memory_type','target_scope','target_key','action','before_value','after_value','evidence','evidence_location','change_reason','conflict_status','write_policy','status']
        ,'ReviewerResult': ['reviewer_role','result','findings','issue_count','severity','impact_scope','true_conflict_candidate']
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
    if contract_type == 'ScenePlan':
        payload=response['payload']
        if not isinstance(payload['target_word_count'], int) or payload['target_word_count'] <= 0: raise ContractFormatError('ScenePlan target_word_count invalid', code='CONTRACT_PAYLOAD_INVALID')
        if payload['ready_for_writing'] is not True: raise ContractFormatError('ScenePlan is not ready_for_writing', code='CONTRACT_PAYLOAD_INVALID')
        nonempty=('scene_goal','entrance_state','exit_state','characters','location','time_context','conflict','action_beats','must_happen','must_not_happen','knowledge_boundary','acceptance_criteria','validation_result')
        if any(payload.get(key) in (None,'',[],{}) for key in nonempty): raise ContractFormatError('ScenePlan contains empty required fields', code='CONTRACT_PAYLOAD_INVALID')
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

def shape(value):
    if not isinstance(value, dict): return type(value).__name__
    return {k: type(v).__name__ for k,v in value.items()}
