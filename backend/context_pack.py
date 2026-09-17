"""ContextPack 组装：固定筛选顺序、来源快照和冲突标记。"""
import hashlib, json
from datetime import datetime, timezone

PRIORITY = {"brief": 100, "world_rule": 90, "book_memory": 80, "scene_memory": 70, "chapter": 60, "reference": 10}
def stamp(): return datetime.now(timezone.utc).isoformat()
def digest(value): return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

class ContextPackService:
    def __init__(self, db): self.db=db
    def assemble(self, *, pack_id, book_id, chapter_id, scene_id, version, target_agent, target_node, brief_version, plan_version, story_state_version, canon_version, sources, keywords=(), excluded_sources=(), missing_sources=(), previous_scene_state=None, chapter_summary=''):
        allowed=[]; excluded=set(excluded_sources); seen={}
        for source in sources:
            sid=source.get("source_id")
            if sid in excluded or source.get("status")=="pending": continue
            if source.get("book_id") not in (None, book_id): continue
            text=json.dumps(source.get("content", source.get("value", "")), ensure_ascii=False)
            score=PRIORITY.get(source.get("source_type"), 0) + sum(text.lower().count(k.lower()) for k in keywords)
            item={"source_id":sid,"source_version":source.get("version",1),"selection_reason":source.get("selection_reason", "scope and priority match"),"content":source.get("content", source.get("value")),"score":score,"target_key":source.get("target_key")}
            allowed.append(item); seen.setdefault(source.get("target_key", sid), []).append(item)
        conflicts=[]
        for key, items in seen.items():
            if len({json.dumps(i["content"],sort_keys=True,ensure_ascii=False) for i in items})>1: conflicts.append({"target_key":key,"source_ids":[i["source_id"] for i in items],"reason":"conflicting values retained separately"})
        allowed.sort(key=lambda x:(-x["score"], x["source_id"] or ""))
        payload={"book_id":book_id,"scene_id":scene_id,"fixture_id":f"{book_id}:{scene_id}","approved_facts":allowed,"previous_scene_state":previous_scene_state or {},"chapter_summary":chapter_summary,"excluded_sources":list(excluded),"missing_sources":list(missing_sources),"conflicts":conflicts,"story_state_version":story_state_version,"canon_version":canon_version}
        content_hash=digest(payload)
        existing=self.db.execute("SELECT payload_json,content_hash,context_pack_id FROM context_packs WHERE scene_id=? AND context_pack_version=? AND target_agent=? AND target_node=?",(scene_id,version,target_agent,target_node)).fetchone()
        if existing:
            saved=json.loads(existing[0])
            if saved != payload:
                raise ValueError(f'HISTORICAL_RECORD_CONFLICT context_pack:{existing[2]}')
            saved['context_pack_id']=existing[2]; saved['content_hash']=existing[1]; return saved
        self.db.execute("INSERT INTO context_packs(context_pack_id,book_id,chapter_id,scene_id,context_pack_version,target_agent,target_node,plan_version,content_hash,payload_json,assembled_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (pack_id,book_id,chapter_id,scene_id,version,target_agent,target_node,plan_version,content_hash,json.dumps(payload,ensure_ascii=False),stamp())); self.db.commit()
        return {**payload,"context_pack_id":pack_id,"content_hash":content_hash}
