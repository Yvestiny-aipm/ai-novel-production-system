"""Read-only progression audit of the frozen five-scene rerun_25 database."""
raise SystemExit("skip: Chinese archive, pre-English cutover")
import hashlib
import json
import sqlite3
from pathlib import Path


path = Path(__file__).parents[1] / "data/real_test_rerun_25.db"
before_hash = hashlib.sha256(path.read_bytes()).hexdigest()
db = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
rows = db.execute("""
    select s.scene_number,p.payload_json,d.text,q.accepted_scene_state_json,q.reviewer_results_json
      from scenes s
      join scene_plans p on p.scene_id=s.scene_id
      join prose_drafts d on d.scene_id=s.scene_id and d.plan_version=p.plan_version
      join quality_reports q on q.draft_id=d.draft_id
     order by s.scene_number
""").fetchall()
db.close()

expected_goals = [
    "林照在灯塔档案中寻找关于林澜失踪的线索，发现灯塔只能保存和展示记忆的真相。",
    "林照在灯塔档案室发现关键线索，指向林澜失踪的真相",
    "林照在灯塔档案室发现异常维护记录，试图从灯塔管理员口中获取更多关于林澜失踪的线索，同时察觉管理员的隐瞒行为。",
    "林照在灯塔档案室发现异常维护记录，试图从灯塔管理员口中获取更多关于林澜失踪的线索，同时察觉管理员的紧张和隐瞒行为。",
    "林照在灯塔档案室发现关键线索，揭示林澜失踪与灯塔异常报告之间的联系",
]
scene2_evidence = [
    "正是林澜失踪的那天",
    "信号异常，需立即处理。勿让外人知晓。",
    "灯塔管理员的呼吸明显急促起来",
    "我想我们需要好好谈谈",
]

audits = []
previous = None
for index, (number, plan_json, text, state_json, reviewers_json) in enumerate(rows):
    plan, accepted, reviewers = json.loads(plan_json), json.loads(state_json), json.loads(reviewers_json)
    assert plan["scene_goal"] == expected_goals[index]
    assert "progression_requirements" not in plan
    assert not any(
        isinstance(review, dict) and "progression_assessment" in review.get("payload", review)
        for review in reviewers
    )
    additions = {
        field: list(accepted.get(field, [])) if previous is None else [
            item for item in accepted.get(field, []) if item not in previous.get(field, [])
        ]
        for field in ("events", "relationship_changes", "unresolved_threads")
    }
    if number == 1:
        evidence = ["灯塔只能保存和展示记忆"]
        assert all(snippet in text for snippet in evidence)
        verdict = "cannot_verify_under_new_rules"
        reason = "legacy_plan_and_reviews_lack_progression_requirements_and_draft_evidence_fields"
        substantive_progress_observed = None
    elif number == 2:
        evidence = scene2_evidence
        assert all(snippet in text for snippet in evidence)
        assert additions == {
            "events": ["林照发现异常灯塔维护记录", "灯塔管理员表现出紧张和隐瞒行为"],
            "relationship_changes": ["林照与灯塔管理员之间的紧张关系升级"],
            "unresolved_threads": ["灯塔异常报告背后的秘密"],
        }
        verdict = "legacy_advance_observed_but_cannot_verify_new_contract"
        reason = "substantive_state_delta_and_prose_evidence_exist_but_required_new_fields_are_absent"
        substantive_progress_observed = True
    else:
        evidence = []
        assert additions == {"events": [], "relationship_changes": [], "unresolved_threads": []}
        assert accepted == previous
        verdict = "stalled_repeated_state"
        reason = "no_new_event_relationship_decision_conflict_consequence_or_thread_change"
        substantive_progress_observed = False
    audits.append({
        "scene": number,
        "plan_goal": plan["scene_goal"],
        "accepted_state_additions": additions,
        "prose_evidence": evidence,
        "accepted_scene_state_recorded_change": any(additions.values()),
        "substantive_progress_observed": substantive_progress_observed,
        "new_rule_verdict": verdict,
        "failure_reason": reason,
    })
    previous = accepted

# The unresolved threads only expand in scene 2; scenes 3-5 repeat them verbatim.
assert [audit["accepted_state_additions"]["unresolved_threads"] for audit in audits] == [
    ["林澜失踪的真相"],
    ["灯塔异常报告背后的秘密"],
    [],
    [],
    [],
]
assert [audit["new_rule_verdict"] for audit in audits] == [
    "cannot_verify_under_new_rules",
    "legacy_advance_observed_but_cannot_verify_new_contract",
    "stalled_repeated_state",
    "stalled_repeated_state",
    "stalled_repeated_state",
]
assert hashlib.sha256(path.read_bytes()).hexdigest() == before_hash
print(json.dumps(audits, ensure_ascii=False, indent=2))
print("rerun_25 progression regression (read-only) ok")
