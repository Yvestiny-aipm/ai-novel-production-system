"""Frozen character canon and conservative draft gate. 20_k sentences only, DB unread."""
import json
import sqlite3
import tempfile
from pathlib import Path

from backend.character_canon import (CHARACTER_CANON_REASON, CHARACTER_CANON_RULE,
    character_canon_instruction, character_canon_snapshot, validate_character_canon)
from backend.context_pack import ContextPackService
from backend.siliconflow import (first_draft_writing_instruction, planning_progression_instruction,
    reviewer_world_instruction)
from integration.run_real_test import run, save_draft, save_plan
from integration.seed_real_test import seed


# Real 20_k sentences, copied out. Tests never open data/real_test_20_k.db.
SCENE14_TA = "林照把油布包放在桌上，没有坐下。他扫了一圈，目光落在桌角那摞册子上。"
SCENE18_SISTER = "“守灯的。”他重复了一遍，语气没有变化，“塔上的人都这么叫。你姐姐也这么叫。”"
SCENE10_SHE = "林照的鞋底陷进湿沙半寸，她停住，没有继续往岸上走。"
SCENE5_MEIMEI = "林照的手停在结上。红线下方的双结是妹妹林澜留下的，左手使力，收尾偏左。"
SCENE14_CHEN = "林照把油布包按在胸口，涉水往回走。老陈在前面带路，步子比来时快，水没过膝盖时他回头看了一眼，确认林照没停。"
CHEN_TA = "老陈说他不敢把这一页留下。"
TEAR_TA = "“他让我撕，我就撕了。”老陈的喉结动了一下"


def expect(text, *, ok):
    result = validate_character_canon(text)
    if ok:
        assert result["status"] == "passed", result
        assert result["reason"] is None
        assert result["conflicts"] == []
    else:
        assert result["status"] == "failed", result
        assert result["reason"] == CHARACTER_CANON_REASON
        assert result["conflicts"]
    return result


expect(SCENE14_TA, ok=False)
expect(SCENE18_SISTER, ok=False)
expect(SCENE10_SHE, ok=True)
expect(SCENE5_MEIMEI, ok=True)
expect(CHEN_TA, ok=True)
expect(TEAR_TA, ok=True)
expect(SCENE14_CHEN, ok=True)
expect("林照没拦他，只把铜牌收回油布包。", ok=True)
expect("林照回头，看见一个五十来岁的男人。他脸上没什么表情。", ok=True)
expect("林照走到他侧面。老人这才抬起头。他年纪很大了。", ok=True)
expect("林照走到他侧面，把册子递到他面前。", ok=True)
expect("一个老人正弯着腰。他听见脚步声。", ok=True)
expect("林照看见一个老人正弯着腰。他听见脚步声。", ok=True)
expect("“门自己关上？”林照问。\n\n“风。”他说，但说得很轻", ok=True)
expect("“门自己关上？”林照问。\n\n“风。”他说，但说得很轻，像自己也不信。他把麻袋甩上肩", ok=True)

canon = character_canon_snapshot()
assert canon["canon_version"] == 1
assert canon["rule"] == CHARACTER_CANON_RULE
names = {item["name"]: item for item in canon["characters"]}
assert names["林照"]["gender"] == "female" and names["林照"]["pronoun"] == "她"
assert names["林照"]["kinship"]["林澜"] == "妹妹"
assert names["林澜"]["relation"] == "林照的妹妹"
assert "老陈" not in names and "守灯的" not in names

for instruction in (
    character_canon_instruction(),
    first_draft_writing_instruction(),
    planning_progression_instruction(),
    reviewer_world_instruction(),
):
    assert "character_canon" in instruction
    assert "禁止写反" in instruction
    assert "妹妹" in instruction


with tempfile.TemporaryDirectory() as directory:
    db = sqlite3.connect(Path(directory) / "pack.db")
    db.executescript((Path(__file__).parents[1] / "db/migrations/001_initial.sql").read_text())
    db.execute("insert into books values ('b','B',null,1,'2026','2026')")
    db.execute("insert into chapters values ('c','b',1,null,'2026','2026')")
    db.execute("insert into scenes values ('s','b','c',1,null,null,'2026','2026')")
    db.commit()
    pack = ContextPackService(db).assemble(
        pack_id="p", book_id="b", chapter_id="c", scene_id="s", version=1,
        target_agent="planning", target_node="planning", brief_version=1, plan_version=1,
        story_state_version=1, canon_version=1, sources=[],
        previous_scene_state={"characters": ["林照改称他"], "events": ["林澜是姐姐"]},
    )
    assert pack["character_canon"] == character_canon_snapshot(version=1)
    assert pack["previous_scene_state"]["characters"] == ["林照改称他"]
    assert pack["character_canon"]["characters"][0]["pronoun"] == "她"
    db.close()


def plan(number):
    return {"contract_type": "ScenePlan", "contract_version": "v1", "payload": {
        "scene_goal": f"场次{number}推进", "entrance_state": {"before": number}, "exit_state": {"after": number},
        "characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚", "conflict": "调查",
        "action_beats": ["查阅档案"], "must_happen": ["发现线索"], "must_not_happen": ["谜团解决"],
        "knowledge_boundary": "灯塔只能保存记忆", "target_word_count": 1250,
        "acceptance_criteria": ["推进调查"], "validation_result": {"complete": True}, "ready_for_writing": True,
        "progression_requirements": [{"progress_type": "new_clue", "target_key": "灯塔线索", "before_state": "未知",
                                      "expected_after_state": "发现线索", "acceptance_criterion": "正文出现线索"}],
    }}


def prose(text):
    return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
        "text": text, "word_count": 1250, "target_word_count": 1250,
        "complete": True, "writer_self_check": {"complete": True},
    }}


def reviewer(role):
    return {"contract_type": "ReviewerResult", "contract_version": "v1", "payload": {
        "reviewer_role": role, "result": "passed", "findings": [], "suggestions": [], "issue_count": 0,
        "severity": "ordinary", "impact_scope": "local", "true_conflict_candidate": False,
        "scene_state": {"characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚",
                        "events": ["发现线索"], "relationship_changes": [], "unresolved_threads": ["林澜失踪"]},
        "progression_assessment": {"status": "achieved", "achieved_items": [{
            "progress_type": "new_clue", "target_key": "灯塔线索", "before_state": "未知",
            "after_state": "发现线索", "evidence_text": "潮", "evidence_location": "draft.text",
        }], "missing_items": [], "evidence": "潮"},
    }}


class CanonDraftAdapter:
    def __init__(self, texts):
        self.texts, self.calls = list(texts), []

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        if role == "planning":
            return plan(number)
        if role == "writing":
            return prose(self.texts.pop(0) if self.texts else SCENE10_SHE + SCENE5_MEIMEI + "潮" * 1000)
        if role == "memory_extraction":
            return {"contract_type": "MemoryProposal", "contract_version": "v1", "payload": {
                "memory_type": "narrative_event", "target_scope": "book_memory", "target_key": "林照-灯塔调查",
                "action": "create", "before_value": None, "after_value": "林照完成本场调查", "evidence": "潮",
                "evidence_location": "draft.payload.text", "change_reason": "审查通过", "conflict_status": "none",
                "write_policy": "human_confirmation", "status": "pending",
            }}
        return reviewer({
            "review_world": "world_consistency", "review_plot": "character_plot",
            "review_style": "language_experience",
        }[role])


def confirm_scene1(db, book):
    scene, chapter = book + "_scene_1", book + "_chapter_1"
    save_plan(db, book, chapter, scene, plan(1), "hc_p1")
    save_draft(db, book, chapter, scene, prose("潮" * 1000), "hc_d1")
    db.execute("insert into quality_reports values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        scene + "_report_v1", book, chapter, scene, scene + "_draft_v1", "h", 1, "completed", "[]",
        0, 0, 0, 0, 0, "complete",
        json.dumps({"characters": ["林照"], "location": "灯塔", "time_context": "夜",
                    "events": ["调查"], "relationship_changes": [], "unresolved_threads": []},
                   ensure_ascii=False),
        "passed", "2026"))
    db.execute("update task_states set status='completed',current_node='memory_processing' where scene_id=?", (scene,))
    db.commit()


failing = SCENE14_TA + "潮" * 1000
passing = SCENE10_SHE + SCENE5_MEIMEI + "潮" * 1000
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "canon-fail.db"
    db, book = seed(path)
    confirm_scene1(db, book)
    db.close()
    adapter = CanonDraftAdapter([failing, passing])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    scene = result["scenes"][1]
    assert scene.get("technical_error") is None
    assert scene.get("block_reason") != CHARACTER_CANON_REASON
    assert scene["final_status"] == "waiting_confirmation"
    roles = [call["task_type"] for call in adapter.calls]
    assert roles.count("planning") == 1
    assert roles.count("writing") == 2
    assert any(role.startswith("review_") for role in roles)
    planning = next(call for call in adapter.calls if call["task_type"] == "planning")
    assert planning["input"]["context_pack"]["character_canon"]["characters"][0]["pronoun"] == "她"
    assert planning["input"]["context_pack"]["character_canon"] != planning["input"]["context_pack"]["previous_scene_state"]
    db = sqlite3.connect(path)
    reasons = [row[0] for row in db.execute(
        "select reason from task_events where task_id=? and event_type='rework_requested' order by created_at",
        (book + "_scene_2_task",))]
    assert CHARACTER_CANON_REASON in reasons
    assert db.execute(
        "select current_node,content_attempt_in_plan from task_states where scene_id=?",
        (book + "_scene_2",)).fetchone()[1] == 1
    db.close()


print("character canon ok")
