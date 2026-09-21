"""Conservative ReviewerResult repair for bare ASCII quotes inside strings."""
import hashlib
import json

from backend.siliconflow import (ESCAPE_UNESCAPED_QUOTES_IN_REVIEWER_STRINGS_RULE,
    ModelResponseParseError, contract_system_prompt, parse_contract_content)


BARE_QUOTE = '结尾"我会再来"略显直白'


def reviewer(*, suggestions=None, findings=None):
    return {
        "contract_type": "ReviewerResult",
        "contract_version": "v1",
        "payload": {
            "reviewer_role": "character_plot",
            "result": "passed",
            "findings": findings or [],
            "suggestions": suggestions if suggestions is not None else [BARE_QUOTE],
            "issue_count": 0,
            "severity": "ordinary",
            "impact_scope": "local",
            "true_conflict_candidate": False,
            "scene_state": {
                "characters": ["林照"],
                "location": "灯塔",
                "time_context": "夜晚",
                "events": [],
                "relationship_changes": [],
                "unresolved_threads": [],
            },
        },
    }


def expect_invalid(content, *, expected="ReviewerResult", finish_reason=None,
                   code="MODEL_RESPONSE_JSON_INVALID"):
    try:
        parse_contract_content(content, expected=expected, finish_reason=finish_reason)
    except ModelResponseParseError as error:
        assert error.error_code == code
        return error
    raise AssertionError("invalid JSON was accepted")


legal = json.dumps(reviewer(), ensure_ascii=False)
legal_parsed = parse_contract_content(legal, expected="ReviewerResult")
assert legal_parsed["payload"]["suggestions"] == [BARE_QUOTE]
assert "contract_parse_normalization_audit" not in legal_parsed

broken = legal.replace('\\"', '"')
assert broken != legal
assert '结尾"我会再来"略显直白' in broken
repaired = parse_contract_content(broken, expected="ReviewerResult")
assert repaired["payload"] == legal_parsed["payload"]
assert repaired["payload"]["suggestions"] == [BARE_QUOTE]
audit = repaired["contract_parse_normalization_audit"]
assert audit["rule"] == ESCAPE_UNESCAPED_QUOTES_IN_REVIEWER_STRINGS_RULE
assert audit["original_content_length"] == len(broken)
assert audit["original_content_hash"] == hashlib.sha256(broken.encode()).hexdigest()

prompt = contract_system_prompt("ReviewerResult")
assert "禁止裸 ASCII" in prompt
assert "「」" in prompt or "中文引号" in prompt

expect_invalid(broken, expected="ScenePlan")
expect_invalid(broken, expected="ProseDraft")
expect_invalid('{"contract_type":"ReviewerResult","payload":{"suggestions":["结尾',
               expected="ReviewerResult")
expect_invalid(legal + legal, expected="ReviewerResult")
error = expect_invalid(broken, expected="ReviewerResult", finish_reason="length",
                       code="MODEL_OUTPUT_TRUNCATED")
assert error.to_audit()["finish_reason"] == "length"

print("reviewer unescaped quotes ok")
