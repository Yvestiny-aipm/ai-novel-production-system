"""Read-only adjacent-scene similarity regression for the frozen rerun_25 DB."""
raise SystemExit("skip: Chinese archive, pre-English cutover")
import hashlib
import json
import sqlite3
from pathlib import Path

from backend.content_similarity import (BODY_THRESHOLD, OPENING_LENGTH, OPENING_THRESHOLD,
    PLAN_ACTION_THRESHOLD, PLAN_GOAL_THRESHOLD, PLAN_OVERALL_THRESHOLD,
    ngram_similarity, normalize_for_similarity, plan_similarity)

path = Path(__file__).parents[1] / "data/real_test_rerun_25.db"
before = hashlib.sha256(path.read_bytes()).hexdigest()
db = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
rows = db.execute("""
    select s.scene_number,s.scene_id,p.payload_json,d.text
      from scenes s join scene_plans p on p.scene_id=s.scene_id
      join prose_drafts d on d.scene_id=s.scene_id and d.plan_version=p.plan_version
     order by s.scene_number
""").fetchall()
summary = []
for index in range(1, len(rows)):
    current, previous = rows[index], rows[index - 1]
    plan = plan_similarity(json.loads(current[2]), json.loads(previous[2]))
    opening = ngram_similarity(normalize_for_similarity(current[3])[:OPENING_LENGTH], normalize_for_similarity(previous[3])[:OPENING_LENGTH])
    body = ngram_similarity(current[3], previous[3])
    summary.append({"scene": current[0], "compared_scene": previous[0], "plan": plan,
                    "opening": opening, "body": body,
                    "would_fail": bool(plan["failed"] or opening >= OPENING_THRESHOLD or body >= BODY_THRESHOLD)})
db.close()

assert [(item["scene"], item["plan"]["overall"], item["opening"], item["body"], item["would_fail"]) for item in summary] == [
    (2, 0.081712, 0.103286, 0.051613, False),
    (3, 0.188679, 0.340909, 0.101869, False),
    (4, 0.415301, 0.277174, 0.157068, False),
    (5, 0.182243, 0.382353, 0.187588, False),
]
# Scene 3/4 has a similar goal (0.875) but not similar action beats (0.128205)
# and not similar combined plan (0.415301), so it correctly passes.
assert summary[2]["plan"]["scene_goal"] == 0.875
assert summary[2]["plan"]["action_beats"] == 0.128205
assert hashlib.sha256(path.read_bytes()).hexdigest() == before
print(json.dumps(summary, ensure_ascii=False))
print("rerun_25 similarity regression (read-only) ok")
