-- v0.1.3: append-only progression evidence audits. QualityReport keeps the
-- structured result in its immutable reviewer-results snapshot; this avoids
-- rewriting legacy report rows or changing their positional table contract.
CREATE TABLE scene_progression_checks (
 check_id TEXT PRIMARY KEY, book_id TEXT NOT NULL REFERENCES books(book_id), chapter_id TEXT NOT NULL REFERENCES chapters(chapter_id), scene_id TEXT NOT NULL REFERENCES scenes(scene_id),
 plan_id TEXT NOT NULL REFERENCES scene_plans(plan_id), draft_id TEXT NOT NULL REFERENCES prose_drafts(draft_id), report_id TEXT NOT NULL,
 previous_scene_id TEXT, progress_type TEXT NOT NULL, target_key TEXT NOT NULL, before_state_json TEXT NOT NULL, expected_after_state_json TEXT NOT NULL,
 actual_after_state_json TEXT NOT NULL, evidence_text TEXT NOT NULL, evidence_location TEXT NOT NULL, evidence_verified INTEGER NOT NULL CHECK(evidence_verified IN (0,1)),
 result TEXT NOT NULL CHECK(result IN ('passed','failed')), failure_reason TEXT, algorithm_version TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX idx_progression_reuse ON scene_progression_checks(plan_id,draft_id,algorithm_version);
INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES ('004_scene_progression_checks', datetime('now'));
