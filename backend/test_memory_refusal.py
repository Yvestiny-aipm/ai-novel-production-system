"""Memory extraction refusal is a technical exception, not empty JSON."""
import json

from backend.azure_foundry import (
    AzureFoundryAdapter, extract_refusal_reason, extract_text_content,
)
from backend.siliconflow import (
    MEMORY_REFUSAL_RETRY_NOTE, ModelResponseParseError, build_chat_messages,
    contract_system_prompt, memory_proposal_instruction,
    memory_refusal_retry_instruction, parse_contract_content,
    slim_memory_refusal_retry_input,
)


class FakeBlock:
    def __init__(self, text, type="text"):
        self.type = type
        self.text = text


class FakeUsage:
    def __init__(self, input_tokens=20, output_tokens=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeMessage:
    def __init__(self, text, stop_reason="end_turn", extra_blocks=None, usage=None):
        self.content = list(extra_blocks or []) + [FakeBlock(text)]
        self.stop_reason = stop_reason
        self.usage = usage or FakeUsage()


class RefusalMessage:
    def __init__(self, reason="I cannot extract personal memories."):
        self.content = [FakeBlock(reason, type="refusal")]
        self.stop_reason = "refusal"
        self.usage = FakeUsage(output_tokens=0)


class QueueClient:
    def __init__(self, messages):
        self.calls = []
        self.messages = self
        self.queue = list(messages)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.queue.pop(0)


DRAFT_TEXT = "林照推开灯塔门，潮气从石缝里涌出来。"
CONTEXT_PACK = {
    "character_canon": {"characters": [{"name": "林照", "pronoun": "她"}]},
    "setting_canon": {"places": [{"name": "档案室", "layer": "保存层"}]},
    "approved_facts": [{"source_id": "a", "content": "灯塔只展示记忆"}],
    "previous_scene_state": {"location": "岸边"},
    "chapter_summary": "不应出现在瘦身重试里的章摘要",
    "fixture_id": "book:scene",
}
ACCEPTED_STATE = {
    "characters": ["林照"],
    "location": "灯塔",
    "time_context": "夜晚",
    "events": ["推门"],
    "relationship_changes": [],
    "unresolved_threads": ["林澜失踪"],
}
QUALITY_REPORT = {
    "contract_type": "QualityReport",
    "contract_version": "v1",
    "payload": {
        "review_completion_status": "completed",
        "reviewer_results": [{"reviewer_role": "world_consistency", "findings": ["完整审查意见不应再寄"]}],
        "deduped_issue_count": 0,
        "ordinary_issue_count": 0,
        "serious_issue_count": 0,
        "has_true_conflict": False,
        "needs_arbiter": False,
        "routing_recommendation": "complete",
        "accepted_scene_state": ACCEPTED_STATE,
        "status": "passed",
    },
}
MEMORY_REQUEST = {
    "task_type": "memory_extraction",
    "contract_type": "MemoryProposal",
    "model": "claude-opus-5",
    "input": {
        "context_pack": CONTEXT_PACK,
        "draft": {"contract_type": "ProseDraft", "payload": {"text": DRAFT_TEXT, "word_count": 18}},
        "quality_report": QUALITY_REPORT,
    },
}

SKIPPED = {
    "contract_type": "MemoryProposal",
    "contract_version": "v1",
    "payload": {"status": "skipped", "reason": "本场没有可记账的虚构事实变化"},
}


# 1. finish_reason=refusal is MODEL_RESPONSE_REFUSED; empty string is not json.loads'd.
try:
    parse_contract_content("", finish_reason="refusal")
except ModelResponseParseError as error:
    assert error.error_code == "MODEL_RESPONSE_REFUSED"
    assert error.finish_reason == "refusal"
    audit = error.to_audit()
    assert audit["error_code"] == "MODEL_RESPONSE_REFUSED"
    assert audit["finish_reason"] == "refusal"
else:
    raise AssertionError("empty refusal was not reported as MODEL_RESPONSE_REFUSED")

try:
    parse_contract_content('{"contract_type":"MemoryProposal"}', finish_reason="refusal")
except ModelResponseParseError as error:
    assert error.error_code == "MODEL_RESPONSE_REFUSED"
else:
    raise AssertionError("refusal with leftover text was parsed as JSON")


# 2. Empty string + end_turn is still JSON_INVALID.
try:
    parse_contract_content("", finish_reason="end_turn")
except ModelResponseParseError as error:
    assert error.error_code == "MODEL_RESPONSE_JSON_INVALID"
    assert error.finish_reason == "end_turn"
    assert "Expecting value" in str(error.parse_error) or "Expecting value" in str(error)
else:
    raise AssertionError("empty end_turn was not JSON_INVALID")


# 3. Refusal blocks stay out of visible text and enter the audit.
refusal_message = RefusalMessage("I cannot extract personal memories.")
assert extract_text_content(refusal_message) == ""
assert extract_refusal_reason(refusal_message) == "I cannot extract personal memories."
try:
    parse_contract_content(
        "",
        finish_reason="refusal",
        usage={"input_tokens": 20, "output_tokens": 0},
        refusal_reason=extract_refusal_reason(refusal_message),
    )
except ModelResponseParseError as error:
    audit = error.to_audit()
    assert audit["refusal_reason"] == "I cannot extract personal memories."
    assert audit["error_code"] == "MODEL_RESPONSE_REFUSED"
    assert audit["usage"]["output_tokens"] == 0
    assert "personal memories" in audit["response_excerpt"]
else:
    raise AssertionError("refusal reason was not audited")

client = QueueClient([RefusalMessage(), RefusalMessage()])
try:
    AzureFoundryAdapter(client=client).complete(MEMORY_REQUEST, 1)
except ModelResponseParseError as error:
    assert error.error_code == "MODEL_RESPONSE_REFUSED"
    assert error.to_audit()["refusal_reason"] == "I cannot extract personal memories."
    assert error.to_audit()["finish_reason"] == "refusal"
else:
    raise AssertionError("double refusal was converted to skipped success")
assert len(client.calls) == 2
assert DRAFT_TEXT in client.calls[0]["messages"][0]["content"]
assert DRAFT_TEXT not in client.calls[1]["messages"][0]["content"]
assert MEMORY_REFUSAL_RETRY_NOTE in [item["content"] for item in client.calls[1]["messages"]]


# 4. Slim retry once then succeeds. First request still has full draft text.
success = FakeMessage(json.dumps(SKIPPED, ensure_ascii=False), usage=FakeUsage(output_tokens=12))
client = QueueClient([RefusalMessage(), success])
result = AzureFoundryAdapter(client=client).complete(MEMORY_REQUEST, 1)
assert result["payload"]["status"] == "skipped"
assert result["payload"]["reason"]
assert len(client.calls) == 2
first_dump = client.calls[0]["messages"][0]["content"]
assert DRAFT_TEXT in first_dump
assert "review_completion_status" in first_dump
assert "完整审查意见不应再寄" in first_dump
retry_dump = json.loads(client.calls[1]["messages"][0]["content"])
assert retry_dump == {
    "context_pack": {
        "character_canon": CONTEXT_PACK["character_canon"],
        "setting_canon": CONTEXT_PACK["setting_canon"],
        "approved_facts": CONTEXT_PACK["approved_facts"],
        "previous_scene_state": CONTEXT_PACK["previous_scene_state"],
    },
    "accepted_scene_state": ACCEPTED_STATE,
}
retry_blob = json.dumps(retry_dump, ensure_ascii=False)
assert DRAFT_TEXT not in retry_blob
assert "review_completion_status" not in retry_blob
assert "完整审查意见不应再寄" not in retry_blob
assert "chapter_summary" not in retry_blob
assert "draft" not in retry_dump
assert "quality_report" not in retry_dump
retry_texts = [item["content"] for item in client.calls[1]["messages"]]
assert MEMORY_REFUSAL_RETRY_NOTE in retry_texts
assert memory_refusal_retry_instruction() in retry_texts
assert retry_texts[-1] == memory_refusal_retry_instruction()
assert "虚构作品的场次状态记账" in retry_texts[-1]


# Planning refusal stays technical and does not consume the memory retry.
planning = QueueClient([RefusalMessage("refused the plan")])
try:
    AzureFoundryAdapter(client=planning).complete(
        {"task_type": "planning", "contract_type": "ScenePlan", "input": {}}, 1
    )
except ModelResponseParseError as error:
    assert error.error_code == "MODEL_RESPONSE_REFUSED"
else:
    raise AssertionError("planning refusal was accepted")
assert len(planning.calls) == 1


prompt = contract_system_prompt("MemoryProposal")
assert "记录本场已确认的虚构事实变化" in prompt
assert "fictional-work scene-state bookkeeping" in prompt
assert "extracting or storing a real person's memory" in prompt
assert "ordinary extracted events" not in prompt
assert "ordinary recorded fictional facts" in prompt
assert "MemoryProposal" not in contract_system_prompt("ScenePlan")

instruction = memory_proposal_instruction()
assert "这是虚构作品的场次状态记账，不是提取或保存真人记忆。" in instruction
assert "记录本场已确认的虚构事实变化" in instruction
assert "不要提取、交出或写入真人记忆" in instruction

first_messages = build_chat_messages(MEMORY_REQUEST)
assert first_messages[-1]["content"] == instruction
assert memory_refusal_retry_instruction() not in [item["content"] for item in first_messages]
assert DRAFT_TEXT in first_messages[1]["content"]
assert "review_completion_status" in first_messages[1]["content"]
assert MEMORY_REFUSAL_RETRY_NOTE not in [item["content"] for item in first_messages]

retry_messages = build_chat_messages({**MEMORY_REQUEST, "memory_refusal_retry": True})
assert retry_messages[-1]["content"] == memory_refusal_retry_instruction()
assert retry_messages[-2]["content"] == MEMORY_REFUSAL_RETRY_NOTE
assert retry_messages[-3]["content"] == instruction
retry_payload = json.loads(retry_messages[1]["content"])
assert slim_memory_refusal_retry_input(MEMORY_REQUEST["input"]) == retry_payload
assert DRAFT_TEXT not in retry_messages[1]["content"]
assert "quality_report" not in retry_payload
assert "draft" not in retry_payload

print("memory refusal ok")
