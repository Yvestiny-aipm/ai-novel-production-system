"""Resume durable checkpoints; only an explicit rework allocates a new revision."""
import json
import os
import sqlite3
import time
import uuid

from backend.context_pack import ContextPackService
from backend.content_similarity import check_draft_repetition, check_plan_repetition
from backend.character_canon import CHARACTER_CANON_REASON, validate_character_canon
from backend.setting_canon import SETTING_CANON_REASON, validate_setting_canon
from backend.progression import (PROGRESSION_RESULT_KEYS, apply_to_quality, plan_before_state_conflict_items,
    progression_baseline_from_state, verify_progression)
from backend.harness import (Harness, required_fields_validator, ContractFormatError,
    ARBITER_PROMPT_VERSION, PLANNING_PROMPT_VERSION, PLANNING_QUALITY_REASONS, REVIEWER_PROMPT_VERSION,
    REVIEWER_ROLE_BY_TASK, classify_scene_plan_quality, normalize_reviewer_evidence,
    normalize_reviewer_result, normalize_reviewer_role, validate_quality_report_for_task,
    validate_scene_plan_against_input, validate_reviewer_result_against_input,
    validate_reviewer_result_for_task)
from backend.model_routing import build_harness_setup
from integration.seed_real_test import auto_confirm_enabled, resolve_scene_count, seed
from backend.prose_length import (LENGTH_FAILURE_REASONS, MAX_LENGTH_FAILURES_IN_PLAN,
    WRITING_PROMPT_VERSION, length_revision_feedback)
from backend.progression import quality_revision_feedback, reviewer_findings_from_payload
from integration.run_real_test import (TYPES, aggregate_quality, save_plan, save_draft,
    save_report, save_proposal, save_task_result, prior_scenes_completed,
    policy_correction_needed, validate_policy_correction, prose_length_validation,
    persisted_draft_validation, draft_payload_for_downstream)


def one(db, sql, args=()):
    cur = db.execute(sql, args)
    row = cur.fetchone()
    return dict(zip([c[0] for c in cur.description], row)) if row is not None else None


def _error_code(error):
    if isinstance(error, ContractFormatError):
        return getattr(error, 'code', None) or 'CONTRACT_FORMAT_INVALID'
    code = getattr(error, 'error_code', None)
    if code:
        return code
    return 'TECHNICAL_ERROR'


def planning_quality_failure_reason(error):
    explicit = getattr(error, 'planning_reason', None)
    if explicit in PLANNING_QUALITY_REASONS:
        return explicit
    text = str(error)
    if 'plan_before_state_conflicts_previous_scene' in text or 'before_state_conflicts_previous_scene' in text:
        return 'plan_before_state_conflicts_previous_scene'
    if 'missing payload fields' in text:
        return 'plan_required_fields_missing'
    if 'empty required fields' in text:
        return 'plan_required_fields_empty'
    if 'ready_for_writing' in text:
        return 'plan_not_ready'
    if 'target_word_count' in text:
        return 'plan_target_word_count_invalid'
    if 'progression' in text:
        return 'plan_progression_missing'
    return None


def planning_quality_field_lists(error=None, message=''):
    missing = list(getattr(error, 'missing_fields', None) or [])
    empty = list(getattr(error, 'empty_fields', None) or [])
    text = message or (str(error) if error is not None else '')
    if not missing and 'missing payload fields:' in text:
        missing = [part.strip() for part in text.split('missing payload fields:', 1)[1].split(',') if part.strip()]
    if not empty and 'empty required fields:' in text:
        empty = [part.strip() for part in text.split('empty required fields:', 1)[1].split(',') if part.strip()]
    return missing, empty


def _exception_call_id(error, db, task_id, out=None):
    call_id = getattr(error, 'call_id', None)
    if call_id:
        return call_id
    row = one(db, """select harness_call_id from harness_calls
                     where task_id=? and status in ('failed','contract_invalid')
                     order by started_at desc limit 1""", (task_id,))
    if row:
        return row['harness_call_id']
    calls = (out or {}).get('calls') or []
    return calls[-1] if calls else None


SOURCE_NODE_BY_AGENT = {
    'planning': 'planning',
    'writing': 'writing',
    'arbiter': 'arbiter',
    'memory_extraction': 'memory_processing',
}


def _source_node_for_agent(agent_type):
    if agent_type in SOURCE_NODE_BY_AGENT:
        return SOURCE_NODE_BY_AGENT[agent_type]
    if isinstance(agent_type, str) and agent_type.startswith('review_'):
        return 'reviewing'
    return agent_type or 'exception_handling'


def _is_reviewer_correction(payload):
    return isinstance(payload, dict) and isinstance(payload.get('reviewer_contract_correction'), dict)


def _error_from_harness(row):
    blob = json.loads(row.get('error_json') or '{}')
    if not isinstance(blob, dict):
        blob = {'error': str(blob)}
    if row.get('status') == 'contract_invalid':
        return blob.get('error') or 'CONTRACT_FORMAT_INVALID', blob.get('reason') or str(blob.get('error') or 'contract_invalid')
    return 'TECHNICAL_ERROR', blob.get('error') or blob.get('reason') or 'TECHNICAL_ERROR'


def _open_exception(db, task_id):
    return one(db, """select * from exception_queue
                      where task_id=? and status in ('pending','handling')
                      order by created_at desc limit 1""", (task_id,))


def _task_event(db, task_id, event_type, payload, *, from_node=None, from_status=None,
                to_node=None, to_status=None, reason=None):
    db.execute(
        """insert into task_events(event_id,task_id,event_type,from_node,from_status,to_node,to_status,
           payload_json,actor_id,reason,created_at) values (?,?,?,?,?,?,?,?,?,?,?)""",
        ('evt_'+uuid.uuid4().hex, task_id, event_type, from_node, from_status, to_node, to_status,
         json.dumps(payload, ensure_ascii=False), 'runner', reason, str(time.time())))


def _bump_task_version(db, task_id):
    task = one(db, 'select state_version from task_states where task_id=?', (task_id,))
    version = int(task['state_version'] if task else 0) + 1
    db.execute('update task_states set state_version=?,updated_at=? where task_id=?',
               (version, str(time.time()), task_id))
    return version


def queue_technical_exception(db, task_id, *, source_node, error, call_id=None, checkpoint=None, out=None):
    """Atomically enqueue one open technical exception. Same capture never inserts twice."""
    code = _error_code(error)
    message = str(error)
    call_id = call_id or _exception_call_id(error, db, task_id, out)
    harness_row = one(db, 'select status,error_json from harness_calls where harness_call_id=?', (call_id,)) if call_id else None
    harness_error = None
    if harness_row and harness_row.get('status') in ('failed', 'contract_invalid'):
        try:
            harness_error = json.loads(harness_row.get('error_json') or '{}')
        except json.JSONDecodeError:
            harness_error = {'error': harness_row.get('error_json')}
        if not isinstance(harness_error, dict):
            harness_error = {'error': harness_error}
        if code == 'TECHNICAL_ERROR':
            stored = harness_error.get('error_code') or harness_error.get('error')
            if stored in ('MODEL_RESPONSE_JSON_INVALID', 'MODEL_OUTPUT_TRUNCATED', 'MODEL_RESPONSE_REFUSED'):
                code = stored
            _, harness_message = _error_from_harness(harness_row)
            if harness_message:
                message = harness_message
    details = {
        'exception_type': type(error).__name__,
        'harness_call_id': call_id,
        'checkpoint': checkpoint or {},
    }
    if harness_error is not None:
        details['harness_error'] = harness_error
    if hasattr(error, 'to_audit'):
        details['parse_audit'] = error.to_audit()
    summary = {'error_code': code, 'error_message': message, 'source_node': source_node}
    with db:
        existing = _open_exception(db, task_id)
        if existing:
            summary['exception_id'] = existing['exception_id']
            db.execute(
                """update exception_queue set source_node=?,status=?,error_code=?,error_message=?,details_json=?,resolved_at=null
                   where exception_id=?""",
                (source_node, 'pending', code, message, json.dumps(details, ensure_ascii=False), existing['exception_id']))
            db.execute(
                """update task_states set current_node=?,status=?,next_action=?,exception_id=?,last_error_json=?
                   where task_id=?""",
                ('exception_handling', 'exception_pending', 'handle_exception',
                 existing['exception_id'], json.dumps(summary, ensure_ascii=False), task_id))
            _bump_task_version(db, task_id)
            _task_event(db, task_id, 'technical_retry_failed', {
                'exception_id': existing['exception_id'], 'source_node': source_node,
                'error_code': code, 'harness_call_id': call_id,
                'retry_count': existing.get('retry_count'),
            }, from_node=existing.get('source_node'), to_node=source_node,
               to_status='exception_pending', reason=code)
            return existing['exception_id']
        exception_id = 'exq_' + uuid.uuid4().hex
        summary['exception_id'] = exception_id
        db.execute(
            """insert into exception_queue(exception_id,task_id,source_node,error_code,error_message,details_json,
               status,retry_count,created_at) values (?,?,?,?,?,?,?,?,?)""",
            (exception_id, task_id, source_node, code, message, json.dumps(details, ensure_ascii=False),
             'pending', 0, str(time.time())))
        db.execute(
            """update task_states set current_node=?,status=?,next_action=?,exception_id=?,last_error_json=?
               where task_id=?""",
            ('exception_handling', 'exception_pending', 'handle_exception',
             exception_id, json.dumps(summary, ensure_ascii=False), task_id))
        _bump_task_version(db, task_id)
        _task_event(db, task_id, 'technical_exception_queued', {
            'source_node': source_node, 'exception_id': exception_id, 'error_code': code,
        }, from_node=source_node, to_node='exception_handling', to_status='exception_pending', reason=code)
    return exception_id


def reconstruct_orphaned_exception(db, task_id):
    """Rebuild a pre-fix exception_pending task that has no exception_queue row."""
    task = one(db, 'select * from task_states where task_id=?', (task_id,))
    if not task or task.get('status') != 'exception_pending':
        return None
    if _open_exception(db, task_id):
        return None
    call = one(db, """select harness_call_id,agent_type,request_json,error_json,status
                      from harness_calls where task_id=? and status in ('failed','contract_invalid')
                      order by started_at desc limit 1""", (task_id,))
    if not call:
        return None
    request = json.loads(call.get('request_json') or '{}')
    checkpoint = (request.get('input') or {}).get('checkpoint') if isinstance(request.get('input'), dict) else {}
    if not isinstance(checkpoint, dict):
        checkpoint = {}
    source_node = _source_node_for_agent(call.get('agent_type'))
    code, message = _error_from_harness(call)
    details = {
        'reconstructed_from_orphaned_state': True,
        'harness_call_id': call['harness_call_id'],
        'checkpoint': checkpoint,
    }
    summary = {'error_code': code, 'error_message': message, 'source_node': source_node}
    with db:
        if _open_exception(db, task_id):
            return None
        exception_id = 'exq_' + uuid.uuid4().hex
        summary['exception_id'] = exception_id
        db.execute(
            """insert into exception_queue(exception_id,task_id,source_node,error_code,error_message,details_json,
               status,retry_count,created_at) values (?,?,?,?,?,?,?,?,?)""",
            (exception_id, task_id, source_node, code, message, json.dumps(details, ensure_ascii=False),
             'pending', 0, str(time.time())))
        db.execute(
            """update task_states set exception_id=?,last_error_json=? where task_id=?""",
            (exception_id, json.dumps(summary, ensure_ascii=False), task_id))
        _bump_task_version(db, task_id)
        _task_event(db, task_id, 'technical_exception_reconstructed', {
            'source_node': source_node, 'exception_id': exception_id, 'error_code': code,
            'harness_call_id': call['harness_call_id'], 'checkpoint': checkpoint,
        }, from_node='exception_handling', from_status='exception_pending',
           to_node='exception_handling', to_status='exception_pending', reason='reconstructed')
    return exception_id


def start_technical_retry(db, task_id):
    """An explicit runner re-entry is one technical retry of the open exception."""
    reconstruct_orphaned_exception(db, task_id)
    with db:
        existing = _open_exception(db, task_id)
        if not existing:
            return None
        retry_count = int(existing['retry_count'] or 0) + 1
        db.execute(
            'update exception_queue set status=?,retry_count=? where exception_id=?',
            ('handling', retry_count, existing['exception_id']))
        db.execute(
            'update task_states set technical_retry_count=technical_retry_count+1 where task_id=?',
            (task_id,))
        _bump_task_version(db, task_id)
        _task_event(db, task_id, 'technical_retry_started', {
            'exception_id': existing['exception_id'], 'retry_count': retry_count,
            'source_node': existing['source_node'],
        }, from_status='exception_pending', to_status='exception_pending', reason='technical_retry')
        return existing['exception_id']


def resolve_technical_exception(db, task_id):
    """Clear the open exception after a technical retry reaches a normal business result."""
    with db:
        existing = _open_exception(db, task_id)
        if not existing:
            return None
        db.execute(
            'update exception_queue set status=?,resolved_at=? where exception_id=?',
            ('resolved', str(time.time()), existing['exception_id']))
        db.execute(
            'update task_states set exception_id=null,last_error_json=null where task_id=?',
            (task_id,))
        _bump_task_version(db, task_id)
        _task_event(db, task_id, 'technical_exception_resolved', {
            'exception_id': existing['exception_id'], 'source_node': existing['source_node'],
        }, from_node='exception_handling', reason='resolved')
        return existing['exception_id']


def _latest_planning_contract_invalid(db, task_id):
    return one(db, """select * from harness_calls
                      where task_id=? and agent_type='planning' and status='contract_invalid'
                      order by completed_at desc, started_at desc, harness_call_id desc""", (task_id,))


def planning_quality_details_from_call(row):
    """Read a stored planning contract_invalid response. Never invent missing top-level fields."""
    try:
        response = json.loads(row.get('response_json') or '')
    except json.JSONDecodeError:
        return None
    if not isinstance(response, dict):
        return None
    if response.get('contract_type') != 'ScenePlan':
        return None
    if not isinstance(response.get('payload'), dict):
        return None
    classification = classify_scene_plan_quality(response)
    if classification:
        return {
            'reason': classification['reason'],
            'missing_fields': classification['missing_fields'],
            'empty_fields': classification['empty_fields'],
            'response': response,
        }
    blob = json.loads(row.get('error_json') or '{}')
    if not isinstance(blob, dict):
        blob = {}
    message = blob.get('reason') or blob.get('error') or ''
    explicit = blob.get('planning_reason')
    reason = explicit if explicit in PLANNING_QUALITY_REASONS else planning_quality_failure_reason(ContractFormatError(str(message)))
    if not reason:
        return None
    missing, empty = planning_quality_field_lists(message=message)
    missing = list(blob.get('missing_fields') or missing)
    empty = list(blob.get('empty_fields') or empty)
    return {
        'reason': reason,
        'missing_fields': missing,
        'empty_fields': empty,
        'response': response,
    }


def reclassify_orphaned_planning_exception(db, task_id, out=None):
    """Turn a stored planning-quality contract_invalid into Planning rework. No model call."""
    task = one(db, 'select * from task_states where task_id=?', (task_id,))
    if not task:
        return False
    existing = _open_exception(db, task_id)
    if task.get('status') != 'exception_pending' and not existing:
        return False
    if not existing and task.get('status') == 'exception_pending':
        reconstruct_orphaned_exception(db, task_id)
        existing = _open_exception(db, task_id)
        task = one(db, 'select * from task_states where task_id=?', (task_id,))
    if not task or task.get('status') != 'exception_pending':
        return False
    if existing and existing.get('source_node') not in (None, '', 'planning'):
        return False
    if existing and existing.get('error_code') in ('MODEL_RESPONSE_JSON_INVALID', 'MODEL_OUTPUT_TRUNCATED', 'MODEL_RESPONSE_REFUSED'):
        return False
    call = None
    exception_call_id = None
    if existing:
        try:
            blob = json.loads(existing.get('details_json') or '{}')
        except json.JSONDecodeError:
            blob = {}
        if isinstance(blob, dict):
            exception_call_id = blob.get('harness_call_id')
    if exception_call_id:
        call = one(db, 'select * from harness_calls where harness_call_id=?', (exception_call_id,))
    else:
        call = _latest_planning_contract_invalid(db, task_id)
    if not call or call.get('agent_type') != 'planning' or call.get('status') != 'contract_invalid':
        return False
    later_success = one(
        db,
        """select harness_call_id from harness_calls
           where task_id=? and agent_type='planning' and status='success'
             and coalesce(started_at,'') > coalesce(?, '')""",
        (task_id, call.get('started_at')),
    )
    if later_success:
        return False
    details = planning_quality_details_from_call(call)
    if not details:
        return False
    request = json.loads(call.get('request_json') or '{}')
    checkpoint = request.get('checkpoint') if isinstance(request.get('checkpoint'), dict) else {}
    if not checkpoint:
        incoming = request.get('input') if isinstance(request.get('input'), dict) else {}
        checkpoint = incoming.get('checkpoint') if isinstance(incoming.get('checkpoint'), dict) else {}
    plan_version = max(int(checkpoint.get('plan_version') or 1), 1)
    scene = task['scene_id']
    saved = one(db, 'select plan_id from scene_plans where scene_id=? and plan_version=?', (scene, plan_version))
    if not saved:
        save_plan(db, task['book_id'], task['chapter_id'], scene, details['response'],
                  call['harness_call_id'], 1, plan_version)
    now = str(time.time())
    with db:
        if existing:
            db.execute('update exception_queue set status=?,resolved_at=? where exception_id=?',
                       ('resolved', now, existing['exception_id']))
        db.execute('update task_states set exception_id=null,last_error_json=null where task_id=?', (task_id,))
        _bump_task_version(db, task_id)
        _task_event(db, task_id, 'planning_exception_reclassified', {
            'exception_id': existing['exception_id'] if existing else None,
            'harness_call_id': call['harness_call_id'],
            'reason': details['reason'],
            'missing_fields': details['missing_fields'],
            'empty_fields': details['empty_fields'],
            'failed_plan_version': plan_version,
        }, from_node='exception_handling', from_status='exception_pending',
           to_node='planning', to_status='reworking_planning', reason=details['reason'])
    apply_planning_failure(
        db, task_id, details['reason'], failed_plan_version=plan_version,
        missing_fields=details['missing_fields'], empty_fields=details['empty_fields'],
    )
    if out is not None:
        out['planning_failure_reason'] = details['reason']
        out['missing_fields'] = details['missing_fields']
        out['empty_fields'] = details['empty_fields']
        out['planning_exception_reclassified'] = True
    return True


def envelope(kind, payload):
    result = {'contract_type': kind, 'contract_version': 'v1', 'payload': payload}
    required_fields_validator(result, kind)
    return result


def _content_failure_already_recorded(db, task_id, draft_id):
    if not draft_id:
        return None
    for event_type, payload_json in db.execute(
            "select event_type,payload_json from task_events where task_id=? and event_type in ('rework_requested','content_failure_blocked') order by created_at",
            (task_id,)):
        if json.loads(payload_json or '{}').get('failed_draft_id') != draft_id:
            continue
        if event_type == 'content_failure_blocked':
            return 'blocked'
        task = one(db, 'select status from task_states where task_id=?', (task_id,))
        return task['status'] if task and task['status'] in ('reworking_writing', 'reworking_planning', 'blocked') else 'reworking_writing'
    return None


def _length_failure_already_recorded(db, task_id, draft_id):
    if not draft_id:
        return None
    for event_type, payload_json in db.execute(
            "select event_type,payload_json from task_events where task_id=? and event_type in ('length_rework_requested','length_failure_blocked') order by created_at",
            (task_id,)):
        if json.loads(payload_json or '{}').get('failed_draft_id') != draft_id:
            continue
        if event_type == 'length_failure_blocked':
            return 'blocked'
        task = one(db, 'select status from task_states where task_id=?', (task_id,))
        return task['status'] if task and task['status'] in ('reworking_writing', 'blocked') else 'reworking_writing'
    return None


def _task_plan_version(db, task):
    saved = db.execute('select coalesce(max(plan_version),0) from scene_plans where scene_id=?', (task['scene_id'],)).fetchone()[0]
    return max(int(saved or 0), _latest_directive_plan_version(task), 1)


def length_failure_count_in_plan(db, task_id, plan_version=None):
    """Failed length drafts in the current scene plan. TaskState content counts stay separate."""
    task = one(db, 'select * from task_states where task_id=?', (task_id,))
    pv = int(plan_version) if plan_version is not None else _task_plan_version(db, task)
    reasons = tuple(sorted(LENGTH_FAILURE_REASONS))
    return db.execute(
        f"select count(*) from prose_drafts where scene_id=? and plan_version=? and length_validation_status=? and length_validation_reason in ({','.join('?' * len(reasons))})",
        (task['scene_id'], pv, 'failed', *reasons)).fetchone()[0]


def length_failure_count_total(db, task_id):
    task = one(db, 'select * from task_states where task_id=?', (task_id,))
    reasons = tuple(sorted(LENGTH_FAILURE_REASONS))
    return db.execute(
        f"select count(*) from prose_drafts where scene_id=? and length_validation_status=? and length_validation_reason in ({','.join('?' * len(reasons))})",
        (task['scene_id'], 'failed', *reasons)).fetchone()[0]


def semantic_failure_count_in_plan(db, task_id):
    task = one(db, 'select content_attempt_in_plan from task_states where task_id=?', (task_id,))
    return int((task or {}).get('content_attempt_in_plan') or 0)


def semantic_failure_count_total(db, task_id):
    task = one(db, 'select content_attempt_total from task_states where task_id=?', (task_id,))
    return int((task or {}).get('content_attempt_total') or 0)


def failure_count_snapshot(db, task_id):
    return {
        'length_failure_count_in_plan': length_failure_count_in_plan(db, task_id),
        'length_failure_count_total': length_failure_count_total(db, task_id),
        'semantic_failure_count_in_plan': semantic_failure_count_in_plan(db, task_id),
        'semantic_failure_count_total': semantic_failure_count_total(db, task_id),
    }


def _planning_failure_already_recorded(db, task_id, failed_plan_version):
    for event_type, payload_json in db.execute(
            "select event_type,payload_json from task_events where task_id=? and event_type in ('rework_requested','planning_failure_blocked') order by created_at",
            (task_id,)):
        payload = json.loads(payload_json or '{}')
        if payload.get('failed_plan_version') != failed_plan_version:
            continue
        if event_type == 'planning_failure_blocked':
            return 'blocked'
        task = one(db, 'select status from task_states where task_id=?', (task_id,))
        return task['status'] if task and task['status'] in ('reworking_planning', 'blocked') else 'reworking_planning'
    return None


def _planning_quality_rework_used(db, task_id):
    """True after a planning-quality rework or planning-quality block. Content replans do not count."""
    for event_type, payload_json in db.execute(
            "select event_type,payload_json from task_events where task_id=? and event_type in ('rework_requested','planning_failure_blocked') order by created_at",
            (task_id,)):
        payload = json.loads(payload_json or '{}')
        if event_type == 'planning_failure_blocked':
            return True
        if event_type == 'rework_requested' and payload.get('content_failure') is False and payload.get('failed_plan_version') is not None:
            return True
    return False


def _latest_directive_plan_version(task):
    latest = 0
    for item in json.loads(task.get('active_contract_refs_json') or '[]'):
        if 'rework' in item:
            latest = max(latest, int(item['rework'].get('plan_version') or 0))
    return latest


def _next_plan_version(db, task, failed_plan_version=None):
    # plan_version is history only. Invalid ScenePlans may not be persisted, so
    # the next version comes from saved rows, the current directive, and the
    # failed plan version — never from plan_attempt.
    saved = db.execute('select coalesce(max(plan_version),0) from scene_plans where scene_id=?', (task['scene_id'],)).fetchone()[0]
    return max(int(saved or 0), _latest_directive_plan_version(task), int(failed_plan_version or 0)) + 1


def request_rework(db, task_id, node, reason, *, content_failure=False, draft_id=None, increment=None, failed_plan_version=None, details=None):
    """Formal revision boundary: persist its IDs before making any new call."""
    if node not in ('planning', 'writing') or not reason.strip():
        raise ValueError('REWORK_REQUIRES_NODE_AND_REASON')
    task = one(db, 'select * from task_states where task_id=?', (task_id,))
    scene = task['scene_id']
    pv = db.execute('select coalesce(max(plan_version),0) from scene_plans where scene_id=?', (scene,)).fetchone()[0]
    dv = db.execute('select coalesce(max(draft_version),0)+1 from prose_drafts where scene_id=?', (scene,)).fetchone()[0]
    cpv = db.execute('select coalesce(max(context_pack_version),0)+1 from context_packs where scene_id=?', (scene,)).fetchone()[0]
    plan_version = _next_plan_version(db, task, failed_plan_version) if node == 'planning' else pv
    directive = {'plan_version': plan_version, 'draft_version': dv, 'context_pack_version': cpv, 'reason': reason,
                 'content_failure': bool(content_failure), 'failed_draft_id': draft_id,
                 'failed_plan_version': failed_plan_version}
    if details:
        for key, value in details.items():
            if value not in (None, [], {}):
                directive[key] = value
    if directive['plan_version'] < 1:
        raise ValueError('REWORK_WRITING_REQUIRES_PLAN')
    add = 1 if (content_failure and increment is None) else (increment or 0)
    current_plan_attempt = int(task.get('plan_attempt') or 1)
    if node == 'planning' and content_failure:
        # Formal return to Planning after three content failures starts a new
        # content-planning cycle. plan_version still increments separately.
        attempts_in_plan = 0
        attempts_total = int(task.get('content_attempt_total') or 0) + add
        plan_attempt = current_plan_attempt + 1
    elif node == 'planning':
        # Planning-quality rework revises the plan only.
        attempts_in_plan = int(task.get('content_attempt_in_plan') or 0)
        attempts_total = int(task.get('content_attempt_total') or 0)
        plan_attempt = current_plan_attempt
    else:
        attempts_in_plan = int(task.get('content_attempt_in_plan') or 0) + add
        attempts_total = int(task.get('content_attempt_total') or 0) + add
        plan_attempt = current_plan_attempt
    with db:
        db.execute('insert into task_events(event_id,task_id,event_type,payload_json,reason,created_at) values (?,?,?,?,?,?)',
                   ('evt_'+uuid.uuid4().hex, task_id, 'rework_requested', json.dumps(directive), reason, str(time.time())))
        db.execute('update task_states set status=?,current_node=?,next_action=?,active_contract_refs_json=?,content_attempt_in_plan=?,content_attempt_total=?,plan_attempt=? where task_id=?',
                   ('reworking_'+node, node, 'replan' if node == 'planning' else 'rewrite', json.dumps([{'rework':directive}]), attempts_in_plan, attempts_total, plan_attempt, task_id))
    return directive


def apply_planning_failure(db, task_id, reason, *, failed_plan_version=1, missing_fields=None, empty_fields=None):
    """Planning-quality failures get one automatic replan, then block. Never count as content failures."""
    version = max(int(failed_plan_version or 1), 1)
    recorded = _planning_failure_already_recorded(db, task_id, version)
    if recorded:
        return recorded
    task = one(db, 'select * from task_states where task_id=?', (task_id,))
    plan_attempt = int(task.get('plan_attempt') or 1)
    extras = {}
    if missing_fields:
        extras['missing_fields'] = list(missing_fields)
    if empty_fields:
        extras['empty_fields'] = list(empty_fields)
    # One planning-quality revision is allowed. The second illegal plan blocks.
    # plan_attempt is the content-planning cycle and must not move here.
    if _planning_quality_rework_used(db, task_id) or version >= 2:
        payload = {'reason': reason, 'failed_plan_version': version, 'content_failure': False,
                   'content_attempt_in_plan': int(task.get('content_attempt_in_plan') or 0),
                   'content_attempt_total': int(task.get('content_attempt_total') or 0),
                   'plan_attempt': plan_attempt, **extras}
        with db:
            db.execute('insert into task_events(event_id,task_id,event_type,payload_json,reason,created_at) values (?,?,?,?,?,?)',
                       ('evt_'+uuid.uuid4().hex, task_id, 'planning_failure_blocked', json.dumps(payload), reason, str(time.time())))
            db.execute('update task_states set status=?,current_node=?,next_action=?,block_reason=?,active_contract_refs_json=? where task_id=?',
                       ('blocked', 'planning', 'none', reason, '[]', task_id))
        return 'blocked'
    request_rework(db, task_id, 'planning', reason, content_failure=False, failed_plan_version=version, details=extras or None)
    return 'reworking_planning'


def apply_content_failure(db, task_id, reason, *, draft_id=None, force_block=False):
    """One content-failed draft is one attempt. A later content-planning cycle blocks on the next failure."""
    recorded = _content_failure_already_recorded(db, task_id, draft_id)
    if recorded:
        return recorded
    task = one(db, 'select * from task_states where task_id=?', (task_id,))
    plan_attempt = int(task.get('plan_attempt') or 1)
    in_plan = int(task.get('content_attempt_in_plan') or 0) + 1
    total = int(task.get('content_attempt_total') or 0) + 1
    if force_block or plan_attempt >= 2:
        block_reason = reason if force_block else 'content_attempts_exhausted'
        payload = {'reason': reason, 'failed_draft_id': draft_id, 'content_failure': True,
                   'content_attempt_in_plan': in_plan, 'content_attempt_total': total, 'plan_attempt': plan_attempt,
                   'force_block': bool(force_block), 'block_reason': block_reason}
        with db:
            db.execute('insert into task_events(event_id,task_id,event_type,payload_json,reason,created_at) values (?,?,?,?,?,?)',
                       ('evt_'+uuid.uuid4().hex, task_id, 'content_failure_blocked', json.dumps(payload), reason, str(time.time())))
            db.execute('update task_states set status=?,current_node=?,next_action=?,block_reason=?,content_attempt_in_plan=?,content_attempt_total=?,active_contract_refs_json=? where task_id=?',
                       ('blocked', 'writing', 'none', block_reason, in_plan, total, '[]', task_id))
        return 'blocked'
    if in_plan >= 3:
        request_rework(db, task_id, 'planning', reason, content_failure=True, draft_id=draft_id)
        return 'reworking_planning'
    request_rework(db, task_id, 'writing', reason, content_failure=True, draft_id=draft_id)
    return 'reworking_writing'


def apply_length_failure(db, task_id, reason, draft_id):
    """Length is format quality. One draft counts once; never increments content or plan_attempt."""
    recorded = _length_failure_already_recorded(db, task_id, draft_id)
    if recorded:
        return recorded
    task = one(db, 'select * from task_states where task_id=?', (task_id,))
    scene = task['scene_id']
    plan_version = _task_plan_version(db, task)
    in_plan = length_failure_count_in_plan(db, task_id, plan_version)
    total = length_failure_count_total(db, task_id)
    payload = {
        'reason': reason, 'failed_draft_id': draft_id, 'content_failure': False, 'length_failure': True,
        'plan_version': plan_version,
        'length_failure_count_in_plan': in_plan, 'length_failure_count_total': total,
        'content_attempt_in_plan': int(task.get('content_attempt_in_plan') or 0),
        'content_attempt_total': int(task.get('content_attempt_total') or 0),
        'plan_attempt': int(task.get('plan_attempt') or 1),
    }
    if in_plan >= MAX_LENGTH_FAILURES_IN_PLAN:
        payload['block_reason'] = 'length_attempts_exhausted'
        with db:
            db.execute('insert into task_events(event_id,task_id,event_type,payload_json,reason,created_at) values (?,?,?,?,?,?)',
                       ('evt_'+uuid.uuid4().hex, task_id, 'length_failure_blocked', json.dumps(payload), reason, str(time.time())))
            db.execute('update task_states set status=?,current_node=?,next_action=?,block_reason=?,active_contract_refs_json=? where task_id=?',
                       ('blocked', 'writing', 'none', 'length_attempts_exhausted', '[]', task_id))
        return 'blocked'
    pv = db.execute('select coalesce(max(plan_version),0) from scene_plans where scene_id=?', (scene,)).fetchone()[0]
    dv = db.execute('select coalesce(max(draft_version),0)+1 from prose_drafts where scene_id=?', (scene,)).fetchone()[0]
    cpv = db.execute('select coalesce(max(context_pack_version),0)+1 from context_packs where scene_id=?', (scene,)).fetchone()[0]
    directive = {
        'plan_version': max(int(pv or 0), 1), 'draft_version': dv, 'context_pack_version': cpv,
        'reason': reason, 'content_failure': False, 'length_failure': True, 'failed_draft_id': draft_id,
    }
    payload['plan_version'] = directive['plan_version']
    with db:
        db.execute('insert into task_events(event_id,task_id,event_type,payload_json,reason,created_at) values (?,?,?,?,?,?)',
                   ('evt_'+uuid.uuid4().hex, task_id, 'length_rework_requested', json.dumps({**directive, **payload}), reason, str(time.time())))
        db.execute('update task_states set status=?,current_node=?,next_action=?,active_contract_refs_json=? where task_id=?',
                   ('reworking_writing', 'writing', 'rewrite', json.dumps([{'rework': directive}]), task_id))
    return 'reworking_writing'


def _reviewer_item_payload(item):
    if not isinstance(item, dict):
        return {}
    payload = item.get('payload') if isinstance(item.get('payload'), dict) else item
    return payload if isinstance(payload, dict) else {}


def _nonempty_reviewer_list(value):
    if isinstance(value, list):
        return [part for part in value if str(part).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _copy_reviewer_list(value):
    if isinstance(value, list):
        return list(value)
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def restore_reviewer_findings(arbiter_results, original_reviews):
    """Keep original reviewer findings/suggestions when the Arbiter returns empty lists."""
    originals_by_role = {}
    for item in original_reviews or []:
        role = _reviewer_item_payload(item).get('reviewer_role')
        if role:
            originals_by_role[role] = item
    if not arbiter_results:
        return list(original_reviews or [])

    def has_findings(items):
        return any(_nonempty_reviewer_list(_reviewer_item_payload(item).get('findings')) for item in items)

    restored = []
    seen = set()
    for item in arbiter_results:
        payload = dict(_reviewer_item_payload(item))
        role = payload.get('reviewer_role')
        original = _reviewer_item_payload(originals_by_role.get(role)) if role else {}
        if not _nonempty_reviewer_list(payload.get('findings')) and _nonempty_reviewer_list(original.get('findings')):
            payload['findings'] = _copy_reviewer_list(original.get('findings'))
            if not payload.get('issue_count'):
                payload['issue_count'] = original.get('issue_count') or len(_nonempty_reviewer_list(payload['findings']))
            if payload.get('result') != 'failed':
                payload['result'] = original.get('result') or 'failed'
        if not _nonempty_reviewer_list(payload.get('suggestions')) and _nonempty_reviewer_list(original.get('suggestions')):
            payload['suggestions'] = _copy_reviewer_list(original.get('suggestions'))
        if role:
            seen.add(role)
        if isinstance(item, dict) and isinstance(item.get('payload'), dict):
            restored.append({**item, 'payload': payload})
        else:
            restored.append(payload)
    for role, item in originals_by_role.items():
        if role not in seen:
            restored.append(item)
    if not has_findings(restored) and has_findings(original_reviews or []):
        return list(original_reviews)
    return restored


class SceneRecovery:
    def __init__(self, db, harness, book, number, out):
        self.db, self.harness, self.book, self.number, self.out = db, harness, book, number, out
        self.scene, self.task = out['scene_id'], out['task_id']
        scene_row = one(db, 'select chapter_id from scenes where scene_id=?', (self.scene,))
        self.chapter = scene_row['chapter_id'] if scene_row else book+'_chapter_1'
        self.node = 'planning'
        self.out.setdefault('reviewer_correction_called', False)
        self.out.setdefault('reviewer_correction_succeeded', False)
        self.out.setdefault('corrected_reviewer_role', None)
        self.out.setdefault('reviewer_normalization_applied', False)
        self.out.setdefault('reviewer_normalization_rule', None)
        self.out.setdefault('reviewer_evidence_normalization_applied', False)
        self.out.setdefault('reviewer_evidence_normalization_count', 0)
        self.out.setdefault('reviewer_role_normalization_applied', False)
        self.out.setdefault('reviewer_role_normalization_count', 0)
        self.out.setdefault('length_failure_count_in_plan', 0)
        self.out.setdefault('length_failure_count_total', 0)
        self.out.setdefault('semantic_failure_count_in_plan', 0)
        self.out.setdefault('semantic_failure_count_total', 0)

    def call(self, role, kind, payload):
        # Exact request matching prevents reuse across scenes, drafts or rework versions.
        payload = {**payload, 'checkpoint': self.checkpoint}
        for row in self.db.execute('select harness_call_id,request_json,response_json,model from harness_calls where task_id=? and agent_type=? and status=? order by started_at desc', (self.task,role,'success')):
            request = json.loads(row[1])
            expected_prompt = self.harness.routes[role].prompt_version
            expected_model = self.harness.routes[role].model
            recorded_model = request.get('model')
            if recorded_model is None:
                recorded_model = row[3]
            if (request.get('input') == payload and request.get('contract_type') == kind
                    and request.get('prompt_version', 'v1') == expected_prompt
                    and recorded_model == expected_model):
                response = json.loads(row[2])
                if kind == 'ReviewerResult':
                    normalize_reviewer_role(response, role)
                    normalize_reviewer_result(response, role)
                    normalize_reviewer_evidence(response, payload)
                required_fields_validator(response, kind)
                if kind == 'ScenePlan':
                    try:
                        validate_scene_plan_against_input(response, payload)
                    except ContractFormatError:
                        continue
                if kind == 'ReviewerResult':
                    try:
                        validate_reviewer_result_for_task(response, role)
                        validate_reviewer_result_against_input(response, role, payload)
                    except ContractFormatError:
                        continue
                if kind == 'QualityReport':
                    validate_quality_report_for_task(response, role)
                if kind == 'ReviewerResult':
                    self._note_reviewer_normalization(response)
                self.out['reused_calls'].append(row[0])
                return {'harness_call_id':row[0], 'response':response}
        before = {r[0] for r in self.db.execute('select harness_call_id from harness_calls where task_id=?',(self.task,))}
        try:
            try:
                result = self.harness.run(task_id=self.task,agent_task_type=role,input_payload=payload,contract_type=kind,contract_validator=required_fields_validator)
                if kind == 'ReviewerResult':
                    self._note_reviewer_normalization(result['response'])
                return result
            except ContractFormatError as error:
                if kind == 'ReviewerResult' and not _is_reviewer_correction(payload):
                    return self._correct_reviewer(role, payload, error)
                raise
        finally:
            self.out['calls'].extend(r[0] for r in self.db.execute('select harness_call_id from harness_calls where task_id=? order by started_at',(self.task,)) if r[0] not in before)

    def _correct_reviewer(self, role, payload, error):
        from backend.siliconflow import reviewer_correction_instruction
        self.out['reviewer_correction_called'] = True
        self.out['reviewer_correction_succeeded'] = False
        self.out['corrected_reviewer_role'] = REVIEWER_ROLE_BY_TASK.get(role)
        correction = {**payload, 'reviewer_contract_correction': {
            'original_response': error.response,
            'original_call_id': error.call_id,
            'validation_error': {'code': error.code, 'reason': str(error)},
            'scene_plan': payload.get('scene_plan'),
            'draft': payload.get('draft'),
            'allowed_status': ['achieved', 'not_achieved', 'unclear'],
            'required_achieved_fields': ['progress_type', 'target_key', 'before_state', 'after_state', 'evidence_text', 'evidence_location'],
            'correction_attempt': 1,
            'instruction': reviewer_correction_instruction(),
        }}
        result = self.harness.run(task_id=self.task, agent_task_type=role, input_payload=correction,
                                 contract_type='ReviewerResult', contract_validator=required_fields_validator)
        self._note_reviewer_normalization(result['response'])
        self.out['reviewer_correction_succeeded'] = True
        return result

    def _note_reviewer_normalization(self, response):
        audit = response.get('contract_normalization_audit') if isinstance(response, dict) else None
        if isinstance(audit, dict) and audit.get('rule'):
            self.out['reviewer_normalization_applied'] = True
            self.out['reviewer_normalization_rule'] = audit['rule']
        if isinstance(response, dict) and response.get('reviewer_evidence_normalization_applied'):
            self.out['reviewer_evidence_normalization_applied'] = True
            self.out['reviewer_evidence_normalization_count'] = int(response.get('reviewer_evidence_normalization_count') or 0)
        if isinstance(response, dict) and response.get('reviewer_role_normalization_applied'):
            self.out['reviewer_role_normalization_applied'] = True
            self.out['reviewer_role_normalization_count'] = int(response.get('reviewer_role_normalization_count') or 0)

    def _route_content_failure(self, reason, *, draft_id=None, force_block=False):
        status = apply_content_failure(self.db, self.task, reason, draft_id=draft_id, force_block=force_block)
        self.out.update(failure_count_snapshot(self.db, self.task))
        if status == 'blocked':
            self.node = 'writing'
            task = one(self.db, 'select block_reason from task_states where task_id=?', (self.task,))
            self.out['block_reason'] = (task or {}).get('block_reason') or reason
            return 'blocked'
        self.node = 'planning' if status == 'reworking_planning' else 'writing'
        return self.execute()

    def _route_length_failure(self, reason, draft_id):
        status = apply_length_failure(self.db, self.task, reason, draft_id)
        self.out.update(failure_count_snapshot(self.db, self.task))
        if status == 'blocked':
            self.node = 'writing'
            self.out['block_reason'] = 'length_attempts_exhausted'
            return 'blocked'
        self.node = 'writing'
        return self.execute()

    def _clear_draft_scoped_output(self):
        for key in ('report_id','progression_status','planned_progression_count','achieved_progression_count',
                    'verified_progression_items','missing_progression_items','progression_failure_reason',
                    'accepted_scene_state','synced_progression_states','passed_review'):
            self.out.pop(key, None)

    def _same_scene_duplicate_hash(self, draft_hash):
        if not draft_hash or not self.out.get('draft_id'):
            return None
        return one(self.db,
                   'select draft_id from prose_drafts where scene_id=? and draft_hash=? and draft_id<>? limit 1',
                   (self.scene, draft_hash, self.out['draft_id']))

    def _writing_length_feedback(self, plan_version):
        previous = one(self.db,'select * from prose_drafts where scene_id=? and plan_version=? order by draft_version desc limit 1',(self.scene,plan_version))
        return length_revision_feedback(previous) if previous else None

    def _quality_payload_from_report(self, report):
        blob = json.loads(report.get('reviewer_results_json') or '[]')
        if not blob:
            return {}
        first = blob[0]
        if isinstance(first, dict) and isinstance(first.get('payload'), dict):
            return first['payload']
        return first if isinstance(first, dict) else {}

    def _failed_quality_report_for_draft(self, draft_id):
        report = one(self.db,'select * from quality_reports where draft_id=? order by review_attempt desc limit 1',(draft_id,))
        if not report:
            return None
        payload = self._quality_payload_from_report(report)
        if report.get('status') != 'failed' and payload.get('status') != 'failed':
            return None
        return report, payload

    def _writing_quality_feedback(self, plan_version, planning):
        previous = one(self.db,'select * from prose_drafts where scene_id=? and plan_version=? order by draft_version desc limit 1',(self.scene,plan_version))
        source = None
        found = None
        if previous and previous.get('length_validation_status') == 'passed':
            found = self._failed_quality_report_for_draft(previous['draft_id'])
            if found:
                source = previous
        if source is None:
            source = one(
                self.db,
                'select d.* from prose_drafts d join quality_reports q on q.draft_id=d.draft_id '
                'where d.scene_id=? and d.plan_version=? and d.length_validation_status=? and q.status=? '
                'order by d.draft_version desc, q.review_attempt desc limit 1',
                (self.scene, plan_version, 'passed', 'failed'),
            )
            if not source:
                return None
            found = self._failed_quality_report_for_draft(source['draft_id'])
        if not found:
            return None
        report, payload = found
        findings = reviewer_findings_from_payload(payload)
        progression_status = payload.get('progression_status')
        missing = payload.get('missing_progression_items') or []
        reason = payload.get('progression_failure_reason')
        if progression_status == 'passed':
            missing = []
            reason = None
        return quality_revision_feedback(
            previous_draft_id=source['draft_id'], previous_text=source.get('text') or '',
            plan_id=self.out.get('plan_id') or planning.get('payload', {}).get('plan_id'),
            plan_version=plan_version,
            reviewer_findings=findings,
            progression_status=progression_status,
            progression_failure_reason=reason,
            planned_progression_requirements=planning['payload'].get('progression_requirements') or [],
            missing_progression_items=missing,
            routing_recommendation=payload.get('routing_recommendation') or report.get('routing_recommendation'),
        )

    def _keep_rejected_plan(self, error, story_version, plan_version):
        """Keep an illegal generated ScenePlan as an immutable old version."""
        if planning_quality_failure_reason(error) not in PLANNING_QUALITY_REASONS:
            return
        response = getattr(error, 'response', None)
        if not isinstance(response, dict) or response.get('contract_type') != 'ScenePlan':
            return
        if not isinstance(response.get('payload'), dict):
            return
        existing = one(self.db, 'select plan_id from scene_plans where scene_id=? and plan_version=?',
                       (self.scene, plan_version))
        if existing:
            self.out['plan_id'] = existing['plan_id']
            return
        self.out['plan_id'] = save_plan(
            self.db, self.book, self.chapter, self.scene, response,
            getattr(error, 'call_id', None) or 'rejected_plan', story_version, plan_version,
        )

    def _planning_revision_feedback(self, directive, planning_input):
        """Quality-rework only. First planning and content replans omit this field."""
        if not isinstance(directive, dict) or directive.get('content_failure'):
            return None
        failed_pv = directive.get('failed_plan_version')
        reason = directive.get('reason')
        if failed_pv is None or not reason:
            return None
        failed = one(self.db, 'select payload_json from scene_plans where scene_id=? and plan_version=?',
                     (self.scene, failed_pv))
        requirements = []
        if failed:
            payload = json.loads(failed['payload_json'] or '{}')
            if isinstance(payload, dict):
                requirements = payload.get('progression_requirements') or []
        return {
            'reason': reason,
            'failed_plan_version': int(failed_pv),
            'failed_items': plan_before_state_conflict_items(
                requirements, planning_input.get('progression_baseline') or {},
            ),
        }

    def _route_planning_failure(self, reason, failed_plan_version, error=None):
        missing, empty = planning_quality_field_lists(error)
        self.out['planning_failure_reason'] = reason
        if missing:
            self.out['missing_fields'] = missing
        if empty:
            self.out['empty_fields'] = empty
        status = apply_planning_failure(
            self.db, self.task, reason, failed_plan_version=failed_plan_version,
            missing_fields=missing, empty_fields=empty,
        )
        self.node = 'planning'
        if status == 'blocked':
            self.out['block_reason'] = reason
            return 'blocked'
        return 'reworking_planning'

    def execute(self):
        task = one(self.db,'select * from task_states where task_id=?',(self.task,))
        directives = [r['rework'] for r in json.loads(task['active_contract_refs_json']) if 'rework' in r]
        directive = directives[-1] if directives else {}
        plan = one(self.db,'select * from scene_plans where scene_id=? order by plan_version desc limit 1',(self.scene,))
        draft = one(self.db,'select * from prose_drafts where scene_id=? order by draft_version desc limit 1',(self.scene,))
        saved_pv = plan['plan_version'] if plan else 0
        pv = directive.get('plan_version', max(saved_pv, 1))
        dv = directive.get('draft_version', draft['draft_version'] if draft else 1)
        cv = directive.get('context_pack_version', draft['context_pack_version'] if draft else 1)
        if plan and plan['plan_version'] != pv: plan = None
        if draft and (draft['draft_version'] != dv or draft['plan_version'] != pv): draft = None
        self.checkpoint = {'scene_id':self.scene,'plan_version':pv,'draft_version':dv,'context_pack_version':cv}
        previous = {}
        if self.number > 1:
            prior = one(self.db,'select q.*,p.story_state_version from quality_reports q join prose_drafts d on d.draft_id=q.draft_id join scene_plans p on p.scene_id=d.scene_id and p.plan_version=d.plan_version where q.scene_id=? and q.status=? order by d.draft_version desc limit 1', (f'{self.book}_scene_{self.number-1}','passed'))
            if not prior: raise ValueError('PREVIOUS_CONFIRMED_STATE_MISSING')
            previous = json.loads(prior['accepted_scene_state_json'])
            story_version = prior['story_state_version']+1
        else: story_version = 1
        sources = [{'source_id':'brief_real_v1','source_type':'brief','book_id':self.book,'version':1,'content':'潮痕档案：林照调查林澜失踪与灯塔档案；灯塔只能保存和展示记忆。'}]
        if previous: sources.append({'source_id':f'accepted_scene_{self.number-1}','source_type':'scene_memory','book_id':self.book,'version':story_version-1,'content':previous})
        cp = ContextPackService(self.db).assemble(pack_id=f'{self.scene}_pack_v{cv}',book_id=self.book,chapter_id=self.chapter,scene_id=self.scene,version=cv,target_agent='planning',target_node='planning',brief_version=1,plan_version=pv,story_state_version=story_version,canon_version=1,sources=sources,previous_scene_state=previous)
        planning_input={'scene_number':self.number,'context_pack':cp}
        if self.number > 1:
            planning_input['progression_baseline']=progression_baseline_from_state(previous)
        revision = self._planning_revision_feedback(directive, planning_input)
        if revision:
            planning_input['planning_revision_feedback'] = revision
        if plan:
            try:
                planning = envelope('ScenePlan',json.loads(plan['payload_json']))
                validate_scene_plan_against_input(planning, planning_input)
                self.out['plan_id'] = plan['plan_id']
            except ContractFormatError as error:
                reason = planning_quality_failure_reason(error)
                if not reason:
                    raise
                self.out['plan_id'] = plan['plan_id']
                self.node = 'planning'
                self.out.update(progression_status='failed', progression_failure_reason=reason)
                return self._route_planning_failure(reason, plan['plan_version'], error)
        else:
            try:
                result = self.call('planning','ScenePlan',planning_input)
            except ContractFormatError as error:
                # Parseable ScenePlan business failures return to Planning.
                # Technical parse/shape errors stay exceptions.
                reason = planning_quality_failure_reason(error)
                if not reason:
                    raise
                self._keep_rejected_plan(error, story_version, pv)
                self.node='planning'; self.out.update(progression_status='failed',progression_failure_reason=reason)
                return self._route_planning_failure(reason, pv, error)
            planning = result['response']
            self.out['plan_id'] = save_plan(self.db,self.book,self.chapter,self.scene,planning,result['harness_call_id'],story_version,pv)
        plan_repetition = check_plan_repetition(self.db, book_id=self.book, current_scene_id=self.scene,
                                                current_plan_id=self.out['plan_id'], payload=planning['payload'])
        self.out.update(repetition_check_status=plan_repetition['status'],
                        repetition_failure_reason=[item['failure_reason'] for item in plan_repetition['failures']],
                        compared_scene_id=(plan_repetition['failures'][0]['compared_scene_id'] if plan_repetition['failures'] else None),
                        similarity_scores=plan_repetition['checks'])
        if plan_repetition['status'] == 'failed':
            reason = 'plan_repetition:' + json.dumps(plan_repetition['failures'], ensure_ascii=False)
            # Planning retries are intentionally a new runner checkpoint: a
            # single invocation never loops forever on repeated plans.
            return self._route_planning_failure(reason, pv)
        self.node = 'writing'
        if draft:
            call = one(self.db,'select response_json from harness_calls where harness_call_id=? and status=?',(draft['harness_call_id'],'success'))
            if not call: raise ValueError('DRAFT_SOURCE_CALL_MISSING')
            writing = json.loads(call['response_json']); required_fields_validator(writing,'ProseDraft')
            if writing['payload']['text'] != draft['text']: raise ValueError('DRAFT_SOURCE_MISMATCH')
            self.out['draft_id'], dh = draft['draft_id'], draft['draft_hash']
            length = persisted_draft_validation(draft)
        else:
            self._clear_draft_scoped_output()
            writing_input={'context_pack':cp,'scene_plan':planning}
            revision=self._writing_length_feedback(pv)
            if revision:
                writing_input['revision_feedback']=revision
            quality_revision=self._writing_quality_feedback(pv, planning)
            if quality_revision:
                writing_input['quality_revision_feedback']=quality_revision
            result = self.call('writing','ProseDraft',writing_input)
            writing = result['response']
            self.out['draft_id'], dh = save_draft(self.db,self.book,self.chapter,self.scene,writing,result['harness_call_id'],dv,pv,cv)
            length = prose_length_validation(writing['payload'])
        self.out.update(model_reported_word_count=writing['payload'].get('word_count'),
                        actual_character_count=length['actual_character_count'],
                        target_word_count=length['target_word_count'],
                        length_validation_status=length['length_validation_status'],
                        length_validation_reason=length['length_validation_reason'])
        # Same-scene exact copies are duplicate_draft_content even when short.
        # Do not spend a length attempt on an unchanged resubmission.
        if self._same_scene_duplicate_hash(dh):
            self.out.update(passed_review=False, rework=True, repetition_rework=True)
            return self._route_content_failure('duplicate_draft_content', draft_id=self.out['draft_id'], force_block=True)
        # This deterministic gate intentionally precedes all reviewers and
        # memory processing.  It is a content rework, never a technical error.
        if length['length_validation_status'] != 'passed':
            self.out.update(passed_review=False,rework=True,length_rework=True)
            reason='length_validation_failed:'+length['length_validation_reason']+f":{length['actual_character_count']}"
            return self._route_length_failure(reason, self.out['draft_id'])
        # Reviews receive only the authoritative count, while the original
        # Harness response remains immutable audit evidence.
        writing = {**writing, 'payload': draft_payload_for_downstream(writing['payload'], length)}
        repetition = check_draft_repetition(self.db, book_id=self.book, current_scene_id=self.scene,
                                            current_draft_id=self.out['draft_id'], text=writing['payload']['text'])
        self.out.update(repetition_check_status=repetition['status'],
                        repetition_failure_reason=[item['failure_reason'] for item in repetition['failures']],
                        compared_scene_id=(repetition['failures'][0]['compared_scene_id'] if repetition['failures'] else None),
                        similarity_scores=repetition['checks'])
        exact = [item for item in repetition['failures'] if item['check_type'] == 'exact']
        if exact:
            self.out.update(passed_review=False, rework=True, repetition_rework=True)
            return self._route_content_failure('duplicate_draft_content', draft_id=self.out['draft_id'], force_block=True)
        if repetition['status'] == 'failed':
            self.out.update(passed_review=False, rework=True, repetition_rework=True)
            reason = 'draft_repetition:' + json.dumps(repetition['failures'], ensure_ascii=False)
            return self._route_content_failure(reason, draft_id=self.out['draft_id'])
        canon = validate_character_canon(writing['payload']['text'])
        self.out['character_canon_status'] = canon['status']
        if canon['status'] == 'failed':
            self.out.update(passed_review=False, rework=True,
                            character_canon_failure_reason=CHARACTER_CANON_REASON,
                            character_canon_conflicts=canon.get('conflicts') or [])
            return self._route_content_failure(CHARACTER_CANON_REASON, draft_id=self.out['draft_id'])
        setting = validate_setting_canon(writing['payload']['text'])
        self.out['setting_canon_status'] = setting['status']
        if setting['status'] == 'failed':
            self.out.update(passed_review=False, rework=True,
                            setting_canon_failure_reason=SETTING_CANON_REASON,
                            setting_canon_conflicts=setting.get('conflicts') or [])
            return self._route_content_failure(SETTING_CANON_REASON, draft_id=self.out['draft_id'])
        self.node = 'reviewing'
        report = one(self.db,'select * from quality_reports where draft_id=? order by review_attempt desc limit 1',(self.out['draft_id'],))
        if report:
            if report['draft_hash'] != dh: raise ValueError('REPORT_DRAFT_HASH_MISMATCH')
            report_payload = {k:report[k] for k in ('review_completion_status','deduped_issue_count','ordinary_issue_count','serious_issue_count','has_true_conflict','needs_arbiter','routing_recommendation','status')}
            report_payload.update(reviewer_results=json.loads(report['reviewer_results_json']),accepted_scene_state=json.loads(report['accepted_scene_state_json']))
            quality = envelope('QualityReport',report_payload)
            self.out['report_id'] = report['report_id']
        else:
            reviewer_input={'context_pack':cp,'draft':writing,'scene_plan':planning,'plan_id':self.out['plan_id'],'plan_version':pv}
            reviews = [self.call(role,'ReviewerResult',reviewer_input)['response'] for role in ('review_world','review_plot','review_style')]
            quality = aggregate_quality(reviews)
            arb = None
            if quality['payload']['needs_arbiter']:
                self.node = 'arbiter'
                # Mark the attempt before the call so a contract failure is not
                # reported as "Arbiter never ran".
                self.out['arbiter_called'] = True
                self.out['arbiter_succeeded'] = False
                preliminary = {'contract_type':quality['contract_type'],'contract_version':quality['contract_version'],
                               'payload':{key:value for key,value in quality['payload'].items() if key not in PROGRESSION_RESULT_KEYS}}
                original_reviews = quality['payload'].get('reviewer_results') or []
                quality = self.call('arbiter','QualityReport',{
                    'context_pack':cp,'scene_plan':planning,'plan_id':self.out['plan_id'],'plan_version':pv,
                    'draft':writing,'reviewer_results':reviews,'preliminary_quality':preliminary,
                    'progression_requirements':planning['payload']['progression_requirements'],
                })['response']
                quality['payload']['reviewer_results'] = restore_reviewer_findings(
                    quality['payload'].get('reviewer_results') or [], original_reviews)
                self.out['arbiter_succeeded'] = True
                arb = [quality]
            report_id=f'{self.scene}_report_v{self.out["draft_id"].rsplit("_v",1)[-1]}'
            # Formal progression audit happens once, after any Arbiter state is known.
            progression=verify_progression(self.db,book_id=self.book,chapter_id=self.chapter,scene_id=self.scene,plan_id=self.out['plan_id'],draft_id=self.out['draft_id'],report_id=report_id,requirements=planning['payload']['progression_requirements'],reviews=reviews,text=writing['payload']['text'],previous_scene_id=(f'{self.book}_scene_{self.number-1}' if self.number>1 else None),previous_state=previous,accepted_scene_state=quality['payload']['accepted_scene_state'])
            quality=apply_to_quality(quality,progression); self.out.update(**progression)
            required_fields_validator(quality,'QualityReport')
            self.out['report_id'], _, _ = save_report(self.db,self.book,self.chapter,self.scene,self.out['draft_id'],dh,[quality],arb)
        if quality['payload']['status'] != 'passed':
            self.out['passed_review'] = False
            self.out['rework'] = True
            reason = 'validated QualityReport failed: ' + self.out['report_id']
            return self._route_content_failure(reason, draft_id=self.out['draft_id'])
        self.out['passed_review'] = True
        self.node = 'memory_processing'
        proposal = one(self.db,'select * from memory_proposals where source_draft_id=? and source_report_id=? order by proposal_version desc limit 1',(self.out['draft_id'],self.out['report_id']))
        if proposal:
            self.out['proposal_id'] = proposal['proposal_id']
            record = one(self.db,'select * from memory_records where source_proposal_id=?',(proposal['proposal_id'],))
            if record:
                if proposal['status'] not in ('approved','written'): raise ValueError('MEMORY_STATUS_MISMATCH')
                if (record['book_id'],record['scene_id'],record['value_json']) != (proposal['book_id'],proposal['scene_id'],proposal['after_value_json']): raise ValueError('MEMORY_SOURCE_MISMATCH')
                self.out['formal_memory_written']=True; return 'completed'
            if proposal['write_policy'] != 'auto_save': self.node='human_confirmation'; return 'waiting_confirmation'
            raise ValueError('MEMORY_WRITE_INCOMPLETE_REQUIRES_REPAIR')
        proposal_version = self.db.execute('select coalesce(max(proposal_version),0)+1 from memory_proposals where scene_id=?',(self.scene,)).fetchone()[0]
        memory_input = {'context_pack':cp,'draft':writing,'quality_report':quality}
        try:
            result = self.call('memory_extraction','MemoryProposal',memory_input)
        except ContractFormatError as error:
            if not policy_correction_needed(error.response): raise
            original = error.response
            # Raw v1 stays in harness_calls; correction request references its ID and revision.
            corrected = self.call('memory_extraction','MemoryProposal',{**memory_input,'policy_correction':{'original':original,'source_call_id':error.call_id,'original_version':proposal_version,'corrected_version':proposal_version+1,'instruction':'Change only write_policy; all other fields must remain identical.'}})
            validate_policy_correction(original,corrected['response'])
            result=corrected; proposal_version+=1
        if result['response']['payload'].get('status') == 'skipped':
            self.out.update(memory_status='skipped',memory_skip_reason=result['response']['payload']['reason']); return 'completed'
        self.out['proposal_id'],self.out['formal_memory_written'] = save_proposal(self.db,self.book,self.chapter,self.scene,self.out['draft_id'],self.out['report_id'],result['response'],proposal_version)
        if self.out['formal_memory_written']: return 'completed'
        self.node = 'human_confirmation'; return 'waiting_confirmation'


def confirm_pending_memory(db, scene_id, actor_id='real_test_operator'):
    from backend.memory_confirmation import confirm_proposal

    old_factory = db.row_factory
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute(
            "select proposal_id from memory_proposals where scene_id=? and status='pending' and write_policy='human_confirmation'",
            (scene_id,),
        ).fetchall()
        confirmed = []
        for row in rows:
            confirm_proposal(db, row['proposal_id'], actor_id)
            confirmed.append(row['proposal_id'])
        return confirmed
    finally:
        db.row_factory = old_factory


def _prompt_version(role):
    if role == 'writing':
        return WRITING_PROMPT_VERSION
    if role in REVIEWER_ROLE_BY_TASK:
        return REVIEWER_PROMPT_VERSION
    if role == 'arbiter':
        return ARBITER_PROMPT_VERSION
    if role == 'planning':
        return PLANNING_PROMPT_VERSION
    return 'v1'


def run_recovery(path, adapter, mode, *, mock=False, model_environ=None, timeout_environ=None):
    if mode not in ('sequential','independent_test'): raise ValueError('INVALID_EXECUTION_MODE')
    env = model_environ if model_environ is not None else ({} if mock else os.environ)
    scene_count = resolve_scene_count(env)
    db, book = seed(path, scene_count=scene_count)
    timeout_env = timeout_environ if timeout_environ is not None else env
    routes, adapters = build_harness_setup(
        TYPES, env, mock=mock, siliconflow_adapter=adapter, timeout_environ=timeout_env,
        prompt_versions={role: _prompt_version(role) for role in TYPES},
    )
    harness = Harness(path, routes, adapters)
    start = time.time(); results = []
    try:
        for number in range(1, scene_count + 1):
            scene = f'{book}_scene_{number}'; task_id = scene+'_task'
            task = one(db,'select * from task_states where task_id=?',(task_id,))
            out = {'scene_id':scene,'task_id':task_id,'execution_mode':mode,'calls':[],'reused_calls':[],'rework':False,'arbiter_called':False,'arbiter_succeeded':False,'reviewer_correction_called':False,'reviewer_correction_succeeded':False,'corrected_reviewer_role':None,'reviewer_normalization_applied':False,'reviewer_normalization_rule':None,'reviewer_evidence_normalization_applied':False,'reviewer_evidence_normalization_count':0,'reviewer_role_normalization_applied':False,'reviewer_role_normalization_count':0,'length_failure_count_in_plan':0,'length_failure_count_total':0,'semantic_failure_count_in_plan':0,'semantic_failure_count_total':0,'proposal_id':None,'formal_memory_written':False,'final_status':task['status'],'current_node':task['current_node']}
            results.append(out)
            if task['status']=='completed': out['skipped_existing']=True; out.update(failure_count_snapshot(db, task_id)); continue
            if task['status']=='waiting_confirmation' and auto_confirm_enabled(env):
                confirmed = confirm_pending_memory(db, scene)
                if confirmed:
                    task = one(db,'select * from task_states where task_id=?',(task_id,))
                    out['auto_confirmed'] = True
                    out['auto_confirmed_proposals'] = confirmed
                    out['final_status'] = task['status']
                    out['current_node'] = task['current_node']
                    out.update(failure_count_snapshot(db, task_id))
                    continue
            if task['status'] in ('waiting_confirmation','blocked','paused','cancelled','skipped'):
                out['paused_existing']=True; out.update(failure_count_snapshot(db, task_id)); continue
            if mode=='sequential' and not prior_scenes_completed(db,book,number):
                out['skipped_due_to_dependency']=True; continue
            recovery = SceneRecovery(db,harness,book,number,out)
            try:
                if reclassify_orphaned_planning_exception(db, task_id, out=out):
                    task = one(db,'select * from task_states where task_id=?',(task_id,))
                    out['final_status'] = task['status']
                    out['current_node'] = task['current_node']
                    out.update(failure_count_snapshot(db, task_id))
                    save_task_result(db,task_id,out['final_status'],out['current_node'],reason=out.get('planning_failure_reason','planning_exception_reclassified'),block_reason=out.get('block_reason'),execution_mode=mode)
                    continue
                start_technical_retry(db, task_id)
                out['final_status'] = recovery.execute()
                out['current_node'] = recovery.node
                resolve_technical_exception(db, task_id)
            except Exception as exc:
                exception_id = queue_technical_exception(
                    db, task_id, source_node=recovery.node, error=exc,
                    checkpoint=getattr(recovery, 'checkpoint', None), out=out)
                out.update(final_status='exception_pending',current_node='exception_handling',
                           technical_error=str(exc),failed_node=recovery.node,exception_id=exception_id)
            if out.get('final_status') == 'waiting_confirmation' and auto_confirm_enabled(env):
                confirmed = confirm_pending_memory(db, scene)
                if confirmed:
                    task = one(db, 'select * from task_states where task_id=?', (task_id,))
                    out['auto_confirmed'] = True
                    out['auto_confirmed_proposals'] = confirmed
                    out['final_status'] = task['status']
                    out['current_node'] = task['current_node']
            out.update(failure_count_snapshot(db, task_id))
            save_task_result(db,task_id,out['final_status'],out['current_node'],reason=out.get('technical_error','checkpoint recovery'),block_reason=out.get('block_reason'),execution_mode=mode)
            if scene_count > 5:
                print(f"scene {number}/{scene_count} status={out.get('final_status')}", flush=True)
    finally:
        harness.close(); db.close()
    return {'status':'completed','execution_mode':mode,'book_id':book,'database':str(path),'scenes':results,'call_count':sum(len(x['calls']) for x in results),'total_seconds':round(time.time()-start,2)}
