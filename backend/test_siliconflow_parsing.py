import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

from siliconflow import (ModelResponseParseError, PARSE_EXCERPT_LIMIT, PARSE_SUFFIX_LIMIT,
    PLAIN_PROSE_WRAP_RULE, TRIM_SINGLE_REDUNDANT_BRACE_RULE, parse_contract_content)
from harness import ContractFormatError, Harness, ModelProfile, required_fields_validator

valid='{"contract_type":"ScenePlan","contract_version":"v1","payload":{"scene_goal":"x"}}'
clean = parse_contract_content('说明文字\n```json\n'+valid+'\n```\n结束')
assert clean['contract_type']=='ScenePlan'
assert 'contract_parse_normalization_audit' not in clean
direct = parse_contract_content(valid)
assert direct['payload']['scene_goal']=='x'
assert 'contract_parse_normalization_audit' not in direct


def expect_parse(content, *, finish_reason=None, usage=None, code="MODEL_RESPONSE_JSON_INVALID"):
    try:
        parse_contract_content(content, finish_reason=finish_reason, usage=usage)
    except ModelResponseParseError as error:
        audit = error.to_audit()
        assert error.error_code == code
        assert audit["error_code"] == code
        assert audit["content_length"] == len(content)
        assert audit["content_hash"] == hashlib.sha256(content.encode()).hexdigest()
        assert audit["response_excerpt"]
        assert len(audit["response_excerpt"]) <= PARSE_EXCERPT_LIMIT + 1
        assert audit["response_suffix"] == content[-PARSE_SUFFIX_LIMIT:]
        assert len(audit["response_suffix"]) <= PARSE_SUFFIX_LIMIT
        assert audit["finish_reason"] == finish_reason
        assert audit["usage"] == usage
        assert audit["parse_error"]
        return error
    raise AssertionError("invalid JSON was accepted")


# Extra data: two JSON objects are not silently accepted.
extra = valid + valid
error = expect_parse(extra)
assert "Extra data" in str(error.parse_error) or "Extra data" in str(error)


# Unterminated string is not repaired.
unterminated = '{"contract_type":"ProseDraft","payload":{"text":"未闭合'
error = expect_parse(unterminated)
assert "Unterminated string" in str(error.parse_error) or "Unterminated" in str(error)


# finish_reason=length is recorded as truncation, not a content failure.
long_content = '{"text":"' + ("潮" * 80)
error = expect_parse(long_content, finish_reason="length", usage={"completion_tokens": 12},
                     code="MODEL_OUTPUT_TRUNCATED")
assert error.to_audit()["finish_reason"] == "length"
assert error.to_audit()["usage"] == {"completion_tokens": 12}


# 2 / 3 / 4. One extra closing brace is trimmed; payload stays identical.
payload = {"scene_goal": "x", "ready": True}
envelope = {"contract_type": "ScenePlan", "contract_version": "v1", "payload": payload}
encoded = json.dumps(envelope, ensure_ascii=False)
trimmed = parse_contract_content(encoded + "}")
assert trimmed["payload"] == payload
assert json.dumps(trimmed["payload"], sort_keys=True) == json.dumps(payload, sort_keys=True)
audit = trimmed["contract_parse_normalization_audit"]
assert audit == {
    "rule": TRIM_SINGLE_REDUNDANT_BRACE_RULE,
    "trailing_character": "}",
    "original_content_length": len(encoded + "}"),
    "original_content_hash": hashlib.sha256((encoded + "}").encode()).hexdigest(),
}


# 5. Trailing explanation stays invalid.
expect_parse(encoded + "} 这是说明")
expect_parse(valid + " extra text")


# 6. A second JSON object stays invalid.
expect_parse(encoded + '{"more":true}')


# 7. Two extra braces stay invalid.
expect_parse(encoded + "}}")


# 8. Unclosed string stays invalid (already covered above).
expect_parse('{"contract_type":"ScenePlan","payload":{"text":"未闭合')


# 9. finish_reason=length never trims an extra brace.
error = expect_parse(encoded + "}", finish_reason="length", code="MODEL_OUTPUT_TRUNCATED")
assert "Extra data" in str(error.parse_error) or "Extra data" in str(error)


# 10. A JSON array plus "}" is not an object.
expect_parse('[1,2]}')


# 11. Failed audit keeps the tail.
tail = "x" * 80 + valid + valid
error = expect_parse(tail)
assert error.to_audit()["response_suffix"] == tail[-PARSE_SUFFIX_LIMIT:]
assert valid[-20:] in error.to_audit()["response_suffix"]


# 12. Normalized success still goes through full Contract validation.
draft = {
    "contract_type": "ProseDraft", "contract_version": "v1",
    "payload": {
        "text": "潮" * 1000, "word_count": 1250, "target_word_count": 1250,
        "complete": True, "writer_self_check": {"complete": True},
    },
}
normalized_draft = parse_contract_content(json.dumps(draft, ensure_ascii=False) + "}")
required_fields_validator(normalized_draft, "ProseDraft")
assert normalized_draft["payload"]["text"] == draft["payload"]["text"]
assert normalized_draft["contract_parse_normalization_audit"]["rule"] == TRIM_SINGLE_REDUNDANT_BRACE_RULE


# 13. A bad ProseDraft cannot pass by riding the brace trim.
bad_draft = {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {"text": ""}}
normalized_bad = parse_contract_content(json.dumps(bad_draft, ensure_ascii=False) + "}")
assert normalized_bad["payload"] == bad_draft["payload"]
try:
    required_fields_validator(normalized_bad, "ProseDraft")
except ContractFormatError as exc:
    assert exc.code == "CONTRACT_PAYLOAD_INVALID"
else:
    raise AssertionError("invalid ProseDraft passed after brace trim")


# 14. Re-parsing a stored normalized object does not stack another audit.
stored = json.dumps(trimmed, ensure_ascii=False)
reused = parse_contract_content(stored)
assert reused["contract_parse_normalization_audit"] == audit
assert "contract_parse_normalization_audit" not in reused["payload"]
restored = parse_contract_content(stored + "}")
assert restored["contract_parse_normalization_audit"] == audit
assert list(restored).count("contract_parse_normalization_audit") == 1


# 12 / 14. Harness still Contract-validates the trimmed object; stored reuse does not restack audit.
full_plan = {
    "contract_type": "ScenePlan", "contract_version": "v1",
    "payload": {
        "scene_goal": "推进调查", "entrance_state": {"location": "灯塔"}, "exit_state": {"clue": "异常记录"},
        "characters": ["林照"], "location": "灯塔", "time_context": "夜晚", "conflict": "寻找线索",
        "action_beats": ["翻阅档案"], "must_happen": ["发现线索"], "must_not_happen": ["谜团解决"],
        "knowledge_boundary": "灯塔只能展示记忆", "target_word_count": 1250,
        "acceptance_criteria": ["推进剧情"], "validation_result": {"complete": True},
        "ready_for_writing": True,
        "progression_requirements": [{
            "progress_type": "new_clue", "target_key": "异常记录", "before_state": "未知",
            "expected_after_state": "发现记录", "acceptance_criterion": "正文发现记录",
        }],
    },
}


class ExtraBraceAdapter:
    def complete(self, request, timeout_seconds):
        return parse_contract_content(json.dumps(full_plan, ensure_ascii=False) + "}")


with tempfile.TemporaryDirectory() as directory:
    db = Path(directory) / "brace.db"
    con = sqlite3.connect(db)
    con.executescript((Path(__file__).parents[1] / "db/migrations/001_initial.sql").read_text())
    con.execute("INSERT INTO books VALUES ('b','B',NULL,1,'2026','2026')")
    con.execute(
        "INSERT INTO task_states(task_id,task_scope,book_id,current_node,status,next_action,"
        "active_contract_refs_json,state_history_json,idempotency_key,created_at,updated_at) "
        "VALUES ('t','book','b','planning','queued','start_planning','[]','[]','k','2026','2026')"
    )
    con.commit(); con.close()
    harness = Harness(db, {"planning": ModelProfile("mock", "m")}, {"mock": ExtraBraceAdapter()})
    result = harness.run(
        task_id="t", agent_task_type="planning", input_payload={},
        contract_type="ScenePlan", contract_validator=required_fields_validator,
    )
    stored = json.loads(harness.db.execute(
        "select response_json from harness_calls where harness_call_id=?",
        (result["harness_call_id"],),
    ).fetchone()[0])
    assert result["response"]["payload"] == full_plan["payload"]
    assert stored["contract_parse_normalization_audit"]["rule"] == TRIM_SINGLE_REDUNDANT_BRACE_RULE
    reused = parse_contract_content(json.dumps(stored, ensure_ascii=False))
    assert reused["contract_parse_normalization_audit"] == stored["contract_parse_normalization_audit"]
    assert "contract_parse_normalization_audit" not in reused["payload"]
    harness.close()


# Writing may return raw scene prose. Only wrap it for ProseDraft, never for other contracts.
plain = "潮声刚刚退到最低点，礁石上还残留着黏湿的海沫。" * 8
wrapped = parse_contract_content(plain, finish_reason="stop", expected="ProseDraft")
assert wrapped["contract_type"] == "ProseDraft"
assert wrapped["payload"]["text"] == plain
assert wrapped["payload"]["complete"] is True
assert wrapped["payload"]["target_word_count"] == 1250
assert wrapped["contract_parse_normalization_audit"]["rule"] == PLAIN_PROSE_WRAP_RULE
try:
    parse_contract_content(plain, expected="ScenePlan")
except ModelResponseParseError as error:
    assert error.error_code == "MODEL_RESPONSE_JSON_INVALID"
else:
    raise AssertionError("plain prose was wrapped for ScenePlan")
try:
    parse_contract_content(plain, finish_reason="length", expected="ProseDraft")
except ModelResponseParseError as error:
    assert error.error_code == "MODEL_OUTPUT_TRUNCATED"
else:
    raise AssertionError("truncated prose was wrapped as a complete draft")


print('siliconflow response parsing ok')
