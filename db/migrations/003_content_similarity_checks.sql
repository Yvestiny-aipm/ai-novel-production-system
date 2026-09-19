-- v0.1.2: append-only audit trail for deterministic same-book repetition checks.
CREATE TABLE content_similarity_checks (
  check_id TEXT PRIMARY KEY,
  book_id TEXT NOT NULL REFERENCES books(book_id),
  current_scene_id TEXT NOT NULL REFERENCES scenes(scene_id),
  current_plan_id TEXT REFERENCES scene_plans(plan_id),
  current_draft_id TEXT REFERENCES prose_drafts(draft_id),
  compared_scene_id TEXT NOT NULL REFERENCES scenes(scene_id),
  compared_plan_id TEXT REFERENCES scene_plans(plan_id),
  compared_draft_id TEXT REFERENCES prose_drafts(draft_id),
  check_type TEXT NOT NULL CHECK(check_type IN ('plan','opening','body','exact')),
  algorithm_version TEXT NOT NULL,
  similarity_score REAL NOT NULL CHECK(similarity_score >= 0 AND similarity_score <= 1),
  threshold REAL NOT NULL CHECK(threshold >= 0 AND threshold <= 1),
  result TEXT NOT NULL CHECK(result IN ('passed','failed')),
  failure_reason TEXT,
  created_at TEXT NOT NULL,
  CHECK ((current_plan_id IS NOT NULL) != (current_draft_id IS NOT NULL))
);
CREATE INDEX idx_similarity_current ON content_similarity_checks(book_id,current_scene_id,algorithm_version);
INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES ('003_content_similarity_checks', datetime('now'));
