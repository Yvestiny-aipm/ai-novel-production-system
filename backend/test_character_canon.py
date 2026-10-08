"""Frozen character canon and conservative draft gate. 20_k sentences only, DB unread."""
import json
import sqlite3
import tempfile
from pathlib import Path
from backend.test_english_fixtures import memory_proposal, reviewer_result, scene_plan, words

from backend.character_canon import (CHARACTER_CANON_REASON, CHARACTER_CANON_RULE,
    character_canon_instruction, character_canon_snapshot, validate_character_canon)
from backend.context_pack import ContextPackService
from backend.siliconflow import (first_draft_writing_instruction, planning_progression_instruction,
    reviewer_world_instruction)
from integration.run_real_test import run, save_draft, save_plan
from integration.seed_real_test import seed


SCENE14_TA = "Lin Zhao set the oilcloth bundle on the table and did not sit. He scanned the room, eyes on the stack at the corner."
SCENE18_SISTER = '"The lamp keeper," he repeated, unchanged. "Everyone on the tower says that. Your older sister said it too."'
SCENE40A_HANDOFF = "Need the brass plate. Lin Zhao handed it over, and he only checked the number line."
SCENE40A_WATCHMAN = "Lin Zhao stood, knees stiff. She watched the night watchman put the chip back in the numbered slot. He opened one drawer."
SCENE40B_ENTER = "Lin Zhao at the door. When she came in, he was wiping the bright edge with a soft cloth."
SCENE10_SHE = "Lin Zhao's soles sank into the wet sand. She stopped and did not walk farther up the shore."
SCENE5_MEIMEI = "Lin Zhao's hand stopped on the knot. The double knot below the red thread was left by her younger sister Lin Lan."
SCENE14_CHEN = "Lin Zhao held the bundle to her chest and waded back. Old Chen led the way. When the water reached his knees he looked back to be sure Lin Zhao had not stopped."
CHEN_TA = "Old Chen said he did not dare leave that page."
TEAR_TA = '"He told me to tear it, so I tore it." Old Chen swallowed.'


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
expect("Lin Zhao did not stop him. She put the brass plate back in the bundle.", ok=True)
expect("Lin Zhao turned and saw a man about fifty. He had little expression.", ok=True)
expect("Lin Zhao walked to his side. The old man raised his head. He was very old.", ok=True)
expect("Lin Zhao walked to his side and held the register out to him.", ok=True)
expect("An old man was bent over. He heard footsteps.", ok=True)
expect("Lin Zhao saw an old man bent over. He heard footsteps.", ok=True)
expect('"Did the door close by itself?" Lin Zhao asked.\n\n"Wind," he said, very softly', ok=True)
expect(SCENE40A_HANDOFF, ok=True)
expect(SCENE40A_WATCHMAN, ok=True)
expect("Lin Zhao gave the register to the other person, and he only checked the number.", ok=True)
expect("Lin Zhao handed it over, and he caught it with both hands.", ok=True)
expect(SCENE40B_ENTER, ok=True)
expect("When she came in, he was already at the retrieval desk.", ok=True)
expect("In front of Lin Zhao, he wrote a line in the register.", ok=True)
expect("He carried a lamp and walked Lin Zhao down the tower. At the base he took a scrap from his coat.", ok=True)
expect("Lin Zhao watched the line, waiting for him to read on. He did not stop.", ok=True)
expect("Lin Zhao asked whether the next round still took the small book up the tower. He answered as before.", ok=True)
expect("Zhou Shouli. Lin Zhao did not open the original register again. She numbered the questions. He had seen what with his own eyes.", ok=True)
expect("Lin Zhao asked him if he had walked the side path that night. He answered at once: no.", ok=True)
expect("Lin Zhao found Liang Min. He did not look up.", ok=True)
expect("Lin Zhao sat down happily. He scanned the room.", ok=False)
expect("Lin Zhao thought of Lin Lan still in town. He scanned the room.", ok=False)
expect("林照把油布包放在桌上，没有坐下。他扫了一圈", ok=True)

su_wan = {
    "canon_version": 1,
    "rule": CHARACTER_CANON_RULE,
    "characters": [{"name": "Su Wan", "gender": "female", "pronoun": "she"}],
    "male_others": ["old man", "man"],
}
assert validate_character_canon("Su Wan set the bundle on the table and did not sit. He scanned the room.", su_wan)["status"] == "failed"
assert validate_character_canon("In front of Su Wan, he wrote a line.", su_wan)["status"] == "passed"
assert validate_character_canon("sent Su Wan to the door, and he turned to close it", su_wan)["status"] == "passed"
su_instruction = character_canon_instruction(su_wan)
assert "Su Wan is female. Use she. Do not use He to continue Su Wan." in su_instruction
assert "Lin Zhao" not in su_instruction

canon = character_canon_snapshot()
assert canon["canon_version"] == 1
assert canon["rule"] == CHARACTER_CANON_RULE
names = {item["name"]: item for item in canon["characters"]}
assert names["Lin Zhao"]["gender"] == "female" and names["Lin Zhao"]["pronoun"] == "she"
assert names["Lin Zhao"]["kinship"]["Lin Lan"] == "younger sister"
assert names["Lin Lan"]["relation"] == "Lin Zhao's younger sister"
assert "Old Chen" not in names
assert canon["male_others"] == ["Old Chen", "the lamp keeper", "the night watchman"]

for instruction in (
    character_canon_instruction(),
    first_draft_writing_instruction(),
    planning_progression_instruction(),
    reviewer_world_instruction(),
):
    assert "character_canon" in instruction
    assert "Do not reverse them" in instruction
    assert "younger sister" in instruction
    assert "the night watchman is male. He does not refer to Lin Zhao" in instruction
    assert "Name the person before switching reference" in instruction
    assert "use names" in instruction


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
    assert pack["character_canon"]["characters"][0]["pronoun"] == "she"
    db.close()


def plan(number):
    return scene_plan(number)


def prose(text):
    return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
        "text": text, "word_count": 1250, "target_word_count": 1250,
        "complete": True, "writer_self_check": {"complete": True},
    }}


def reviewer(role, number=1):
    return reviewer_result(role, number=number)


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
            return prose(self.texts.pop(0) if self.texts else words(1000, lead=SCENE10_SHE + " " + SCENE5_MEIMEI + " word", token="beta"))
        if role == "memory_extraction":
            return {"contract_type": "MemoryProposal", "contract_version": "v1", "payload": {
                "memory_type": "narrative_event", "target_scope": "book_memory", "target_key": "林照-灯塔调查",
                "action": "create", "before_value": None, "after_value": "林照完成本场调查", "evidence": "word",
                "evidence_location": "draft.payload.text", "change_reason": "审查通过", "conflict_status": "none",
                "write_policy": "human_confirmation", "status": "pending",
            }}
        return reviewer({
            "review_world": "world_consistency", "review_plot": "character_plot",
            "review_style": "language_experience",
        }[role], number)


def confirm_scene1(db, book):
    scene, chapter = book + "_scene_1", book + "_chapter_1"
    save_plan(db, book, chapter, scene, plan(1), "hc_p1")
    save_draft(db, book, chapter, scene, prose(words(1000)), "hc_d1")
    db.execute("insert into quality_reports values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        scene + "_report_v1", book, chapter, scene, scene + "_draft_v1", "h", 1, "completed", "[]",
        0, 0, 0, 0, 0, "complete",
        json.dumps({"characters": ["林照"], "location": "灯塔", "time_context": "夜",
                    "events": ["调查"], "relationship_changes": [], "unresolved_threads": []},
                   ensure_ascii=False),
        "passed", "2026"))
    db.execute("update task_states set status='completed',current_node='memory_processing' where scene_id=?", (scene,))
    db.commit()


failing = words(1000, lead=SCENE14_TA, token="alpha")
passing = words(1000, lead=SCENE10_SHE + " " + SCENE5_MEIMEI + " word", token="beta")
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
    assert planning["input"]["context_pack"]["character_canon"]["characters"][0]["pronoun"] == "she"
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
