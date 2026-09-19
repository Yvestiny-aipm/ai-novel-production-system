-- v0.1.1: model-reported prose length is audit-only; backend records actual count.
ALTER TABLE prose_drafts ADD COLUMN model_reported_word_count INTEGER;
ALTER TABLE prose_drafts ADD COLUMN actual_character_count INTEGER;
ALTER TABLE prose_drafts ADD COLUMN length_validation_status TEXT CHECK(length_validation_status IN ('passed','failed'));
ALTER TABLE prose_drafts ADD COLUMN length_validation_reason TEXT;

INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES ('002_prose_draft_length_validation', datetime('now'));
