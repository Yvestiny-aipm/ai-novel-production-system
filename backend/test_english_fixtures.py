"""Shared English fixtures for tests. Word count uses whitespace split."""


def words(count, lead="", token="word"):
    extra = max(0, int(count) - (len(lead.split()) if lead else 0))
    tail = " ".join([token] * extra)
    if lead and tail:
        return f"{lead} {tail}"
    return lead or tail


def scene_plan(number=1, **overrides):
    payload = {
        "scene_goal": f"Advance scene {number} by checking shelf {number} and recording mark {number}",
        "entrance_state": {"before": number, "shelf": number},
        "exit_state": {"after": number, "mark": number},
        "characters": ["Lin Zhao"],
        "location": "Archive Room",
        "time_context": "night",
        "conflict": f"investigation mark {number}",
        "action_beats": [f"open drawer {number}", f"copy line {number}", f"leave shelf {number}"],
        "must_happen": [f"find clue {number}"],
        "must_not_happen": ["solve the mystery"],
        "knowledge_boundary": "the lighthouse may only store memory",
        "target_word_count": 1250,
        "acceptance_criteria": [f"advance investigation {number}"],
        "validation_result": {"complete": True},
        "ready_for_writing": True,
        "progression_requirements": [{
            "progress_type": "new_clue",
            "target_key": f"lighthouse clue {number}",
            "before_state": "unknown",
            "expected_after_state": f"found clue {number}",
            "acceptance_criterion": f"the prose shows clue {number}",
        }],
    }
    payload.update(overrides)
    return {"contract_type": "ScenePlan", "contract_version": "v1", "payload": payload}


def prose_draft(text=None, size=1250, reported=1250):
    body = text if text is not None else words(size)
    return {
        "contract_type": "ProseDraft",
        "contract_version": "v1",
        "payload": {
            "text": body,
            "word_count": reported,
            "target_word_count": 1250,
            "complete": True,
            "writer_self_check": {"complete": True},
        },
    }


def reviewer_result(role, evidence="word", number=1):
    return {
        "contract_type": "ReviewerResult",
        "contract_version": "v1",
        "payload": {
            "reviewer_role": role,
            "result": "passed",
            "findings": [],
            "suggestions": [],
            "issue_count": 0,
            "severity": "ordinary",
            "impact_scope": "local",
            "true_conflict_candidate": False,
            "scene_state": {
                "characters": ["Lin Zhao"],
                "location": "Archive Room",
                "time_context": "night",
                "events": [f"found clue {number}"],
                "relationship_changes": [],
                "unresolved_threads": ["Lin Lan missing"],
            },
            "progression_assessment": {
                "status": "achieved",
                "achieved_items": [{
                    "progress_type": "new_clue",
                    "target_key": f"lighthouse clue {number}",
                    "before_state": "unknown",
                    "after_state": f"found clue {number}",
                    "evidence_text": evidence,
                    "evidence_location": "draft.text",
                }],
                "missing_items": [],
                "evidence": evidence,
            },
        },
    }


def memory_proposal():
    return {
        "contract_type": "MemoryProposal",
        "contract_version": "v1",
        "payload": {
            "memory_type": "narrative_event",
            "target_scope": "book_memory",
            "target_key": "linzhao:lighthouse_investigation",
            "action": "create",
            "before_value": None,
            "after_value": "Lin Zhao finished this scene's investigation",
            "evidence": "word",
            "evidence_location": "draft.payload.text",
            "change_reason": "review passed",
            "conflict_status": "none",
            "write_policy": "human_confirmation",
            "status": "pending",
        },
    }
