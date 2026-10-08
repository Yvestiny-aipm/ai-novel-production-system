"""Read-only proof that the frozen rerun_25 drafts fail the new length gate."""
raise SystemExit("skip: Chinese archive, pre-English cutover")
import hashlib
import sqlite3
from pathlib import Path

from backend.prose_length import validate_prose_length

path = Path(__file__).parents[1] / "data/real_test_rerun_25.db"
before = hashlib.sha256(path.read_bytes()).hexdigest()
db = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
observed = []
for scene_id, text in db.execute("select scene_id,text from prose_drafts order by scene_id,draft_version"):
    result = validate_prose_length(text)
    observed.append((scene_id.rsplit("_", 1)[-1], result["actual_character_count"], result["length_validation_status"], result["length_validation_reason"]))
db.close()
assert observed == [
    ("1", 346, "failed", "under_length"),
    ("2", 676, "failed", "under_length"),
    ("3", 583, "failed", "under_length"),
    ("4", 358, "failed", "under_length"),
    ("5", 519, "failed", "under_length"),
]
assert hashlib.sha256(path.read_bytes()).hexdigest() == before
print("rerun_25 length regression (read-only) ok")
