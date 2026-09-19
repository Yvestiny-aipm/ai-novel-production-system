"""Deterministic regression coverage for the adjacent-scene repetition gate."""
import json
import sqlite3
import tempfile
from pathlib import Path

import backend.content_similarity as similarity
from backend.content_similarity import (BODY_THRESHOLD, OPENING_LENGTH, OPENING_THRESHOLD,
    check_draft_repetition, check_plan_repetition, ngram_similarity, plan_similarity)
from integration.run_real_test import run, save_draft, save_plan
from integration.seed_real_test import seed


def plan(goal, action, conflict="调查线索", must="发现线索"):
    return {"contract_type": "ScenePlan", "contract_version": "v1", "payload": {
        "scene_goal": goal, "entrance_state": {"ready": True}, "exit_state": {"changed": True},
        "characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚", "conflict": conflict,
        "action_beats": [action], "must_happen": [must], "must_not_happen": ["谜团解决"],
        "knowledge_boundary": "灯塔只能保存记忆", "target_word_count": 1250,
        "acceptance_criteria": ["推进剧情"], "validation_result": {"complete": True}, "ready_for_writing": True,
        "progression_requirements": [{"progress_type":"new_clue","target_key":"潮痕线索","before_state":"未知","expected_after_state":"发现线索","acceptance_criterion":"正文写明线索"}],
    }}


def draft(text):
    return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
        "text": text, "word_count": 1250, "target_word_count": 1250,
        "complete": True, "writer_self_check": {"complete": True},
    }}


def confirmed(db, book, number, plan_response, text):
    scene, chapter = f"{book}_scene_{number}", f"{book}_chapter_1"
    plan_id = save_plan(db, book, chapter, scene, plan_response, f"hc_plan_{number}", number, 1)
    draft_id, draft_hash = save_draft(db, book, chapter, scene, draft(text), f"hc_draft_{number}")
    db.execute("insert into quality_reports values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        f"{scene}_report_v1", book, chapter, scene, draft_id, draft_hash, 1, "completed", "[]", 0, 0, 0,
        0, 0, "complete", json.dumps({"characters":["林照"],"location":"灯塔档案室","time_context":"夜晚","events":["调查"],"relationship_changes":[],"unresolved_threads":[]}), "passed", "2026"))
    db.execute("update task_states set status='completed',current_node='memory_processing' where scene_id=?", (scene,))
    db.commit()
    return plan_id, draft_id


# Exact, opening-only, and body-only cases use character n-grams; names and
# locations alone are far below threshold and cannot cause a rejection.
opening = "夜色如墨灯塔档案室内林照翻开潮湿档案" * 10
opening = opening[:OPENING_LENGTH]
assert ngram_similarity(opening + "甲" * 1000, opening + "乙" * 1000) >= OPENING_THRESHOLD
shared_body = "".join(chr(0x4E00 + index) for index in range(800))
assert ngram_similarity("甲" * 120 + shared_body, "乙" * 120 + shared_body) >= BODY_THRESHOLD
assert ngram_similarity("林照在灯塔档案室调查" * 60, "林照在灯塔档案室修复航标" * 60) < BODY_THRESHOLD
assert plan_similarity(plan("寻找失踪档案", "翻阅同一批档案")["payload"], plan("寻找失踪档案", "翻阅同一批档案")["payload"])["failed"]
assert not plan_similarity(plan("修复失明航标", "拆解损坏透镜")["payload"], plan("追查失踪船员", "比对潮汐航线")["payload"])["failed"]


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "similarity.db"
    db, book = seed(path)
    previous_text = opening + "旧场独有的潮声事件" * 120
    previous_plan_id, previous_draft_id = confirmed(db, book, 1, plan("解读潮痕档案", "逐页比对潮汐记录"), previous_text)

    # Same cast/place but a different objective and action passes planning.
    current_plan = plan("修复失明航标", "拆解破损透镜", "风暴将至", "恢复警示光")
    current_plan_id = save_plan(db, book, book + "_chapter_1", book + "_scene_2", current_plan, "hc_p2", 2, 1)
    result = check_plan_repetition(db, book_id=book, current_scene_id=book + "_scene_2", current_plan_id=current_plan_id, payload=current_plan["payload"])
    assert result["status"] == "passed"

    # Opening-only repetition: full body differs, but the first 120 chars do not.
    opening_only = opening + "新场完全不同的航标修复过程" * 120
    current_draft_id, _ = save_draft(db, book, book + "_chapter_1", book + "_scene_2", draft(opening_only), "hc_d2")
    result = check_draft_repetition(db, book_id=book, current_scene_id=book + "_scene_2", current_draft_id=current_draft_id, text=opening_only)
    assert any(item["failure_reason"] == "opening_repetition" for item in result["failures"])
    assert not any(item["failure_reason"] == "body_repetition" for item in result["failures"])
    first_count = db.execute("select count(*) from content_similarity_checks").fetchone()[0]
    reused = check_draft_repetition(db, book_id=book, current_scene_id=book + "_scene_2", current_draft_id=current_draft_id, text=opening_only)
    assert all(item["reused"] for item in reused["checks"])
    assert db.execute("select count(*) from content_similarity_checks").fetchone()[0] == first_count
    original_version = similarity.ALGORITHM_VERSION
    similarity.ALGORITHM_VERSION = "char_ngram_jaccard_v2_test"
    check_draft_repetition(db, book_id=book, current_scene_id=book + "_scene_2", current_draft_id=current_draft_id, text=opening_only)
    similarity.ALGORITHM_VERSION = original_version
    assert db.execute("select count(*) from content_similarity_checks").fetchone()[0] > first_count

    # The same string in another book must never become a comparison target.
    db.execute("insert into books values ('other','其他作品',null,1,'2026','2026')")
    db.execute("insert into chapters values ('other_chapter','other',1,null,'2026','2026')")
    db.execute("insert into scenes values ('other_scene','other','other_chapter',1,null,null,'2026','2026')")
    db.execute("insert into task_states(task_id,task_scope,book_id,chapter_id,scene_id,current_node,status,next_action,active_contract_refs_json,state_history_json,idempotency_key,created_at,updated_at) values ('other_task','scene','other','other_chapter','other_scene','planning','completed','none','[]','[]','other_key','2026','2026')")
    db.commit()
    assert all(item["compared_scene_id"] != "other_scene" for item in result["checks"])
    db.close()


# Different starts plus one large shared body trigger body, not opening.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "body.db"; db, book = seed(path)
    large_shared = "".join(chr(0x4E00 + index) for index in range(1000))
    confirmed(db, book, 1, plan("第一场独特目标", "第一场独特动作"), "甲" * 120 + large_shared)
    p2 = plan("第二场独特目标", "第二场独特动作")
    p2_id = save_plan(db, book, book + "_chapter_1", book + "_scene_2", p2, "hc_body_plan", 2, 1)
    d2_id, _ = save_draft(db, book, book + "_chapter_1", book + "_scene_2", draft("乙" * 120 + large_shared), "hc_body_draft")
    body_result = check_draft_repetition(db, book_id=book, current_scene_id=book + "_scene_2", current_draft_id=d2_id, text="乙" * 120 + large_shared)
    assert any(item["failure_reason"] == "body_repetition" for item in body_result["failures"])
    assert not any(item["failure_reason"] == "opening_repetition" for item in body_result["failures"])
    db.close()


class ExactAdapter:
    def __init__(self, text): self.text=text; self.calls=[]
    def complete(self, request, timeout_seconds):
        self.calls.append(request); role=request["task_type"]; number=int(request["input"]["checkpoint"]["scene_id"].rsplit("_",1)[-1])
        if role == "planning": return plan(f"第{number}场不同目标", f"第{number}场不同动作")
        if role == "writing": return draft(self.text)
        raise AssertionError("repetition must prevent reviewers and memory")


class PlanRepeatAdapter:
    def __init__(self, repeated): self.repeated=repeated; self.calls=[]
    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        if request["task_type"] == "planning": return self.repeated
        raise AssertionError("plan repetition must prevent writing")


# A repeated goal/action plan creates a durable planning checkpoint and one new
# version, without a Writing call or overwriting the historical plan.
with tempfile.TemporaryDirectory() as directory:
    path=Path(directory)/"plan-repeat.db"; db, book=seed(path)
    repeated=plan("解读潮痕档案","逐页比对潮汐记录")
    confirmed(db,book,1,repeated,"第一场不同正文" * 200); db.close()
    adapter=PlanRepeatAdapter(repeated); result=run(db_path=path,adapter=adapter,execution_mode="sequential")
    db=sqlite3.connect(path)
    scene=book+"_scene_2"
    assert result["scenes"][1]["final_status"] == "reworking_planning"
    assert [call["task_type"] for call in adapter.calls] == ["planning"]
    assert adapter.calls[0]["input"]["checkpoint"]["plan_version"] == 1
    assert db.execute("select count(*) from scene_plans where scene_id=?",(scene,)).fetchone()[0] == 1
    assert db.execute("select count(*) from prose_drafts where scene_id=?",(scene,)).fetchone()[0] == 0
    assert db.execute("select status,current_node,plan_attempt,content_attempt_in_plan,content_attempt_total from task_states where scene_id=?",(scene,)).fetchone() == ("reworking_planning","planning",1,0,0)
    db.close()
    second = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert second["scenes"][1]["final_status"] == "blocked"
    assert second["scenes"][1]["current_node"] == "planning"
    assert [call["task_type"] for call in adapter.calls] == ["planning", "planning"]
    assert adapter.calls[1]["input"]["checkpoint"]["plan_version"] == 2
    assert not second["scenes"][1]["reused_calls"]
    assert db.execute("select coalesce(max(plan_version),0) from scene_plans where scene_id=?",(scene,)).fetchone()[0] == 2
    assert db.execute("select count(*) from prose_drafts where scene_id=?",(scene,)).fetchone()[0] == 0
    assert db.execute("select status,current_node,plan_attempt,content_attempt_in_plan,content_attempt_total from task_states where scene_id=?",(scene,)).fetchone() == ("blocked","planning",1,0,0)
    db.close()


# An exact draft from a completed adjacent scene is blocked, never reviewed.
with tempfile.TemporaryDirectory() as directory:
    path=Path(directory)/"exact.db"; db, book=seed(path)
    text="完全相同正文" * 200
    confirmed(db,book,1,plan("第一场独特目标","第一场独特动作"),text); db.close()
    adapter=ExactAdapter(text); result=run(db_path=path,adapter=adapter,execution_mode="sequential")
    db=sqlite3.connect(path)
    assert result["scenes"][1]["final_status"] == "blocked"
    assert result["scenes"][1]["block_reason"] == "duplicate_draft_content"
    assert [call["task_type"] for call in adapter.calls] == ["planning", "writing"]
    assert db.execute("select count(*) from quality_reports where scene_id like '%scene_2'").fetchone()[0] == 0
    assert db.execute("select plan_attempt,content_attempt_in_plan,content_attempt_total,status from task_states where scene_id like '%scene_2'").fetchone() == (1, 1, 1, "blocked")
    db.close()
    second = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert second["scenes"][1]["final_status"] == "blocked"
    assert [call["task_type"] for call in adapter.calls] == ["planning", "writing"]
    assert db.execute("select plan_attempt,content_attempt_in_plan,content_attempt_total,status from task_states where scene_id like '%scene_2'").fetchone() == (1, 1, 1, "blocked")
    db.close()


class RepeatingOpeningAdapter:
    def __init__(self, prefix): self.prefix=prefix; self.calls=[]; self.attempt=0
    def complete(self, request, timeout_seconds):
        self.calls.append(request); role=request["task_type"]; number=int(request["input"]["checkpoint"]["scene_id"].rsplit("_",1)[-1])
        if role == "planning": return plan(f"第{number}场新目标", f"第{number}场新动作")
        if role == "writing":
            self.attempt += 1
            return draft(self.prefix + (f"第{self.attempt}次不同尾段" * 150))
        raise AssertionError("repeated opening must prevent reviewers and memory")


# Two semantic repetitions rewrite; the third replans. The new plan's first
# repeated draft is blocked instead of opening Plan v3.
with tempfile.TemporaryDirectory() as directory:
    path=Path(directory)/"rework.db"; db, book=seed(path)
    prior_prefix="档案室开头高度一致" * 14
    confirmed(db,book,1,plan("第一场独特目标","第一场独特动作"),prior_prefix + "旧场尾段" * 180); db.close()
    adapter=RepeatingOpeningAdapter(prior_prefix); result=run(db_path=path,adapter=adapter,execution_mode="sequential")
    db=sqlite3.connect(path)
    scene=book+"_scene_2"
    assert result["scenes"][1]["final_status"] == "blocked"
    assert db.execute("select count(*) from prose_drafts where scene_id=?",(scene,)).fetchone()[0] == 4
    assert db.execute("select count(*) from quality_reports where scene_id=?",(scene,)).fetchone()[0] == 0
    assert [call["task_type"] for call in adapter.calls].count("writing") == 4
    assert [call["task_type"] for call in adapter.calls].count("planning") == 2
    assert not any(call["task_type"].startswith("review_") or call["task_type"] == "memory_extraction" for call in adapter.calls)
    task=db.execute("select status,current_node,plan_attempt,content_attempt_in_plan,content_attempt_total from task_states where scene_id=?",(scene,)).fetchone()
    assert task == ("blocked","writing",2,1,4)
    db.close()

print("content similarity gate ok")
