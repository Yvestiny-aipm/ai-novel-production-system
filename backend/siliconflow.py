"""硅基流动 OpenAI 兼容接口适配器。密钥只从环境变量读取。"""
import json, os, urllib.request

def parse_contract_content(content):
    if not isinstance(content,str): return content
    text=content.strip()
    if '```' in text:
        text=text.replace('```json','').replace('```','').strip()
    try: return json.loads(text)
    except json.JSONDecodeError:
        start,end=text.find('{'),text.rfind('}')
        if start>=0 and end>start: return json.loads(text[start:end+1])
        raise RuntimeError('MODEL_RESPONSE_NOT_JSON')

class SiliconFlowAdapter:
    def __init__(self, *, api_url=None, api_key_env="SILICONFLOW_API_KEY", model="deepseek-ai/DeepSeek-V3", timeout=60):
        self.api_url=api_url or os.getenv("SILICONFLOW_API_URL", "https://api.siliconflow.cn/v1/chat/completions")
        self.api_key_env=api_key_env; self.model=model; self.timeout=timeout
    def complete(self, request, timeout_seconds):
        key=os.getenv(self.api_key_env)
        if not key: raise RuntimeError("SILICONFLOW_API_KEY_MISSING")
        expected=request.get("contract_type")
        fields={'ScenePlan':'scene_goal, entrance_state, exit_state, characters, location, time_context, conflict, action_beats, must_happen, must_not_happen, knowledge_boundary, target_word_count, acceptance_criteria, validation_result, ready_for_writing','ProseDraft':'text (non-empty Chinese prose, about 1250 Chinese characters), word_count (>0), target_word_count (1250), complete (true), writer_self_check; never return empty text or incomplete=true','ReviewerResult':'reviewer_role, result, findings, issue_count, severity, impact_scope, true_conflict_candidate, scene_state with characters, location, time_context, events, relationship_changes, unresolved_threads extracted from the current draft','QualityReport':'review_completion_status, reviewer_results, deduped_issue_count, ordinary_issue_count, serious_issue_count, has_true_conflict, needs_arbiter, routing_recommendation, accepted_scene_state must contain characters, location, time_context, events, relationship_changes, unresolved_threads, status','MemoryProposal':'either (A) one complete proposal with memory_type, target_scope, target_key, action, before_value, after_value, evidence, evidence_location, change_reason, conflict_status (none|conflict|resolved), write_policy (auto_save|human_confirmation|never_auto_write), status (pending|approved|rejected|written|conflict), or (B) no durable memory change: payload exactly contains status="skipped" and a non-empty reason; never return empty proposal fields or a proposals array'}.get(expected,'')
        scene_plan_rule = " For ScenePlan, generate a concrete scene goal, entrance_state, exit_state, characters, location, time_context, conflict, action_beats, must_happen, must_not_happen, knowledge_boundary, target_word_count, acceptance_criteria, and validation_result. Do not copy the ContextPack as the plan. validation_result must state that every required field is complete and valid; set ready_for_writing to true only after this self-check passes. If any required field is missing or empty, do not claim a complete plan." if expected == 'ScenePlan' else ''
        instruction=f"Return only valid JSON. The business Contract type MUST be exactly {expected!r}; this is different from the internal task_type. Use keys contract_type, contract_version, payload. Set contract_type to {expected!r}, contract_version to 'v1', and include every required payload field: {fields}.{scene_plan_rule} For MemoryProposal, choose exactly one outcome: a complete single proposal, or payload {{\"status\":\"skipped\",\"reason\":\"...\"}} when the passed draft has no durable new fact. The skipped outcome must contain no proposal fields and does not need target_key. If submitting a proposal, target_key is mandatory and must be a specific, stable identifier for the fact's real subject: e.g. character:linlan:archive_discovery, location:lighthouse_archive, event:linzhao:memory_projection, or scene_fact:lighthouse:memory_only. It must identify a character, place, event, or scene fact from the current draft or ContextPack; never use a ContextPack/fixture filename, context_pack, pack_v*, a generic label such as fact/event/memory/scene, or a vague description. For a proposal, action MUST be exactly create for a new memory, update for changing an existing memory, or delete for removing an existing memory. Never use add, modify, remove, append, or any other action value. memory_type MUST be exactly one of scene_fact, narrative_event, world_rule, character_detail, and target_scope MUST be exactly one of scene_memory, book_memory, character_memory. Mapping is mandatory: scene_fact→scene_memory + auto_save; narrative_event→book_memory + human_confirmation; world_rule→book_memory + human_confirmation; character_detail→character_memory + human_confirmation. Never use story, chapter, chapter_summary, fact, narrative, event, or never_auto_write for ordinary extracted events. Do not return a proposals array. Do not use Markdown fences or explanatory text.\n"
        body={"model":self.model,"messages":[{"role":"user","content":instruction+json.dumps(request["input"],ensure_ascii=False)}],"max_tokens":request.get("max_output_tokens",4096),"temperature":0}
        req=urllib.request.Request(self.api_url,data=json.dumps(body).encode(),headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},method="POST")
        with urllib.request.urlopen(req,timeout=timeout_seconds or self.timeout) as res:
            result=json.loads(res.read())
        if result.get("contract"):
            return result["contract"]
        content = (((result.get("choices") or [{}])[0].get("message") or {}).get("content"))
        if isinstance(content, str):
            return parse_contract_content(content)
        return result
