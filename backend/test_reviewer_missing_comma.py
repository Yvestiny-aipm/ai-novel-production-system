"""Conservative ReviewerResult repair for one missing member comma."""
import hashlib
import json

from backend.siliconflow import (INSERT_MISSING_COMMA_IN_REVIEWER_RESULT_RULE,
    ModelResponseParseError, parse_contract_content)


def reviewer(*, result="passed", findings=None, suggestions=None):
    items = findings if findings is not None else []
    return {
        "contract_type": "ReviewerResult",
        "contract_version": "v1",
        "payload": {
            "reviewer_role": "character_plot",
            "result": result,
            "findings": items,
            "suggestions": suggestions if suggestions is not None else [],
            "issue_count": len(items),
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


def drop_comma_between(legal, left, right):
    token = f'{left},{right}'
    broken = legal.replace(token, f'{left}{right}', 1)
    assert broken != legal
    return broken


legal = json.dumps(reviewer(), ensure_ascii=False)
legal_parsed = parse_contract_content(legal, expected="ReviewerResult")
assert legal_parsed["payload"]["result"] == "passed"
assert "contract_parse_normalization_audit" not in legal_parsed

# 40_c / 40_d style: adjacent members missing one comma.
broken = drop_comma_between(legal, '"result": "passed"', ' "findings"')
try:
    json.loads(broken)
except json.JSONDecodeError as exc:
    assert "Expecting ',' delimiter" in exc.msg
else:
    raise AssertionError("fixture still parsed without a comma")
repaired = parse_contract_content(broken, expected="ReviewerResult")
assert repaired["payload"] == legal_parsed["payload"]
assert repaired["payload"]["result"] == "passed"
audit = repaired["contract_parse_normalization_audit"]
assert audit["rule"] == INSERT_MISSING_COMMA_IN_REVIEWER_RESULT_RULE
assert audit["original_content_length"] == len(broken)
assert audit["original_content_hash"] == hashlib.sha256(broken.encode()).hexdigest()

nested = drop_comma_between(legal, '"location": "灯塔"', ' "time_context"')
repaired_nested = parse_contract_content(nested, expected="ReviewerResult")
assert repaired_nested["payload"] == legal_parsed["payload"]
assert repaired_nested["contract_parse_normalization_audit"]["rule"] == INSERT_MISSING_COMMA_IN_REVIEWER_RESULT_RULE

failed_legal = json.dumps(reviewer(result="failed", findings=["缺推进证据"]), ensure_ascii=False)
failed_broken = drop_comma_between(failed_legal, '"result": "failed"', ' "findings"')
failed_repaired = parse_contract_content(failed_broken, expected="ReviewerResult")
assert failed_repaired["payload"]["result"] == "failed"
assert failed_repaired["payload"]["findings"] == ["缺推进证据"]
assert failed_repaired["contract_parse_normalization_audit"]["rule"] == INSERT_MISSING_COMMA_IN_REVIEWER_RESULT_RULE

expect_invalid('{"contract_type":"ReviewerResult","payload":{"result":"failed"',
               expected="ReviewerResult")
expect_invalid('{"contract_type":"ReviewerResult","payload":{"suggestions":["结尾',
               expected="ReviewerResult")
plan = '{"contract_type":"ScenePlan","contract_version":"v1","payload":{"scene_goal":"x" "ready_for_writing":true}}'
expect_invalid(plan, expected="ScenePlan")
draft = '{"contract_type":"ProseDraft","contract_version":"v1","payload":{"text":"潮" "complete":true}}'
expect_invalid(draft, expected="ProseDraft")
error = expect_invalid(broken, expected="ReviewerResult", finish_reason="length",
                       code="MODEL_OUTPUT_TRUNCATED")
assert error.to_audit()["finish_reason"] == "length"

print("reviewer missing comma ok")
