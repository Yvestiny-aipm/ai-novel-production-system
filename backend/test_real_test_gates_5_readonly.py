"""Stable, read-only audit of data/real_test_gates_5.db."""
raise SystemExit("skip: Chinese archive, pre-English cutover")
import hashlib
import json
import sqlite3
from pathlib import Path


PATH = Path(__file__).parents[1] / "data/real_test_gates_5.db"
assert PATH.is_file(), "真实测试尚未产生新库"
before_hash = hashlib.sha256(PATH.read_bytes()).hexdigest()
db = sqlite3.connect(f"file:{PATH.resolve()}?mode=ro", uri=True)
db.row_factory = sqlite3.Row
db.execute("pragma query_only=ON")


def rows(sql, args=()):
    return [dict(row) for row in db.execute(sql, args)]


tasks = rows("""
    select scene_id,current_node,status,next_action,content_attempt_in_plan,
           content_attempt_total,active_contract_refs_json
      from task_states order by scene_id
""")
plans = rows("select scene_id,plan_version,payload_json from scene_plans order by scene_id,plan_version")
drafts = rows("""
    select scene_id,draft_version,plan_version,content_attempt_in_plan,content_attempt_total,
           model_reported_word_count,actual_character_count,length_validation_status,
           length_validation_reason
      from prose_drafts order by scene_id,draft_version
""")
calls = rows("select task_id,agent_type,status,error_json,response_json from harness_calls order by started_at")
reworks = rows("""
    select t.scene_id,e.payload_json
      from task_events e join task_states t on t.task_id=e.task_id
     where e.event_type='rework_requested' order by e.created_at
""")
quality = rows("select scene_id,accepted_scene_state_json,reviewer_results_json from quality_reports order by scene_id")
progression_checks = rows("select scene_id,result,failure_reason from scene_progression_checks order by created_at")
similarity_checks = rows("select current_scene_id,result,failure_reason from content_similarity_checks order by created_at")
proposals = rows("select scene_id,memory_type,write_policy,status from memory_proposals order by created_at")
records = rows("select scene_id,memory_type,approval_status from memory_records order by created_at")

assert len(tasks) == 5
assert [len([plan for plan in plans if plan["scene_id"] == task["scene_id"]]) for task in tasks] == [4, 0, 0, 0, 0]
assert [len([draft for draft in drafts if draft["scene_id"] == task["scene_id"]]) for task in tasks] == [9, 0, 0, 0, 0]
assert [draft["actual_character_count"] for draft in drafts] == [615, 840, 448, 426, 679, 825, 567, 643, 725]
assert all(draft["model_reported_word_count"] == 1250 for draft in drafts)
assert all(draft["length_validation_status"] == "failed" and draft["length_validation_reason"] == "under_length" for draft in drafts)
assert len(reworks) == 9
assert not quality and not progression_checks and not similarity_checks
assert not proposals and not records
assert [call["agent_type"] for call in calls].count("review_plot") == 0
assert [call["agent_type"] for call in calls].count("memory_extraction") == 0
assert [(call["agent_type"], call["status"]) for call in calls].count(("writing", "failed")) == 1

report = []
previous_confirmed = True
for task in tasks:
    scene_id = task["scene_id"]
    scene_plans = [plan for plan in plans if plan["scene_id"] == scene_id]
    scene_drafts = [draft for draft in drafts if draft["scene_id"] == scene_id]
    scene_calls = [call for call in calls if call["task_id"] == scene_id + "_task"]
    scene_reworks = [json.loads(row["payload_json"]) for row in reworks if row["scene_id"] == scene_id]
    scene_quality = [row for row in quality if row["scene_id"] == scene_id]
    plot_assessments = []
    for call in scene_calls:
        if call["agent_type"] == "review_plot" and call["response_json"]:
            payload = json.loads(call["response_json"]).get("payload", {})
            plot_assessments.append(payload.get("progression_assessment"))
    accepted = json.loads(scene_quality[-1]["accepted_scene_state_json"]) if scene_quality else None
    requirements = [
        {"plan_version": plan["plan_version"],
         "progression_requirements": json.loads(plan["payload_json"]).get("progression_requirements", [])}
        for plan in scene_plans
    ]
    if scene_drafts:
        length = {
            "gate_status": "failed",
            "attempts": [
                {key: draft[key] for key in (
                    "draft_version", "plan_version", "content_attempt_in_plan",
                    "content_attempt_total", "model_reported_word_count",
                    "actual_character_count", "length_validation_status", "length_validation_reason"
                )}
                for draft in scene_drafts
            ],
        }
        repetition = {
            "plan": "no_confirmed_same_book_comparison_target",
            "draft": "not_reached_due_to_length_failure",
            "failure_reasons": [],
        }
        progression = {
            "status": "not_reached_due_to_length_failure",
            "reviewer_assessments": plot_assessments,
            "verified_items": [],
            "missing_items": [],
            "failure_reason": None,
        }
        overall = "failed_at_length_gate"
    else:
        length = {"gate_status": "not_started", "attempts": []}
        repetition = {"plan": "not_started", "draft": "not_started", "failure_reasons": []}
        progression = {
            "status": "not_started", "reviewer_assessments": [], "verified_items": [],
            "missing_items": [], "failure_reason": None,
        }
        overall = "not_started_due_to_dependency"
    failed_calls = [
        {"agent_type": call["agent_type"], "error": json.loads(call["error_json"])}
        for call in scene_calls if call["status"] == "failed"
    ]
    report.append({
        "scene_id": scene_id,
        "plan_versions": [plan["plan_version"] for plan in scene_plans],
        "latest_plan_version": scene_plans[-1]["plan_version"] if scene_plans else None,
        "draft_versions": [draft["draft_version"] for draft in scene_drafts],
        "latest_persisted_draft_version": scene_drafts[-1]["draft_version"] if scene_drafts else None,
        "rework_count": len(scene_reworks),
        "length": length,
        "repetition": repetition,
        "progression_requirements": requirements,
        "progression": progression,
        "accepted_scene_state": accepted,
        "accepted_state_additions": None,
        "memory_agent_call_count": sum(call["agent_type"] == "memory_extraction" for call in scene_calls),
        "memory_proposals": [row for row in proposals if row["scene_id"] == scene_id],
        "task_state": {key: task[key] for key in (
            "current_node", "status", "next_action", "content_attempt_in_plan", "content_attempt_total"
        )},
        "previous_scene_confirmed_before_start": "not_applicable" if scene_id.endswith("_scene_1") else previous_confirmed,
        "current_scene_has_valid_confirmation": bool(scene_quality and scene_quality[-1]),
        "failed_calls": failed_calls,
        "overall": overall,
    })
    previous_confirmed = bool(scene_quality)

assert report[0]["task_state"] == {
    "current_node": "exception_handling", "status": "exception_pending", "next_action": "handle_exception",
    "content_attempt_in_plan": 0, "content_attempt_total": 9,
}
assert all(item["task_state"] == {
    "current_node": "planning", "status": "queued", "next_action": "start_planning",
    "content_attempt_in_plan": 0, "content_attempt_total": 0,
} for item in report[1:])
assert all(not item["current_scene_has_valid_confirmation"] for item in report)
assert all(item["memory_agent_call_count"] == 0 for item in report)

db.close()
after_hash = hashlib.sha256(PATH.read_bytes()).hexdigest()
assert after_hash == before_hash
print(json.dumps({
    "database": str(PATH),
    "sha256_before": before_hash,
    "sha256_after": after_hash,
    "scene_count": 5,
    "completed_scene_count": 0,
    "scenes": report,
}, ensure_ascii=False, indent=2))
print("real_test_gates_5 read-only audit ok")
