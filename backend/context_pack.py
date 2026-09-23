"""ContextPack 组装：固定筛选顺序、来源快照和冲突标记。"""
import hashlib, json
from datetime import datetime, timezone

from backend.character_canon import character_canon_snapshot
from backend.chapter_state import build_chapter_state, load_chapter_context
from backend.established_facts import ESTABLISHED_FACTS_RULE, build_world_state, established_facts_snapshot
from backend.pacing import build_pacing_state, load_pacing_recent
from backend.setting_canon import setting_canon_snapshot

PRIORITY = {"brief": 100, "world_rule": 90, "book_memory": 80, "scene_memory": 70, "chapter": 60, "reference": 10}
def stamp(): return datetime.now(timezone.utc).isoformat()
def digest(value): return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

class ContextPackService:
    def __init__(self, db): self.db=db
    def assemble(self, *, pack_id, book_id, chapter_id, scene_id, version, target_agent, target_node, brief_version, plan_version, story_state_version, canon_version, sources, keywords=(), excluded_sources=(), missing_sources=(), previous_scene_state=None, chapter_summary='', established_facts=None, pacing_recent=None, chapter_context=None):
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
        ledger = established_facts if isinstance(established_facts, dict) else established_facts_snapshot(version=canon_version)
        ledger = {"canon_version": ledger.get("canon_version", canon_version), "rule": ledger.get("rule") or ESTABLISHED_FACTS_RULE, "facts": list(ledger.get("facts") or [])}
        previous = previous_scene_state or {}
        if pacing_recent is not None:
            recent = pacing_recent if isinstance(pacing_recent, list) else []
        else:
            try:
                number = self.db.execute("select scene_number from scenes where scene_id=?", (scene_id,)).fetchone()
                recent = load_pacing_recent(self.db, book_id=book_id, before_scene_number=(number[0] if number else 0))
            except Exception:
                recent = []
        if chapter_context is not None:
            raw_chapter = chapter_context if isinstance(chapter_context, dict) else {}
        else:
            try:
                raw_chapter = load_chapter_context(self.db, book_id, scene_id)
            except Exception:
                raw_chapter = {}
        payload={"book_id":book_id,"scene_id":scene_id,"fixture_id":f"{book_id}:{scene_id}","approved_facts":allowed,"previous_scene_state":previous,"chapter_summary":chapter_summary,"excluded_sources":list(excluded),"missing_sources":list(missing_sources),"conflicts":conflicts,"story_state_version":story_state_version,"canon_version":canon_version,"character_canon":character_canon_snapshot(version=canon_version),"setting_canon":setting_canon_snapshot(version=canon_version),"established_facts":ledger,"world_state":build_world_state(previous),"pacing_state":build_pacing_state(recent),"chapter_state":build_chapter_state(raw_chapter)}
        content_hash=digest(payload)
        existing=self.db.execute("SELECT payload_json,content_hash,context_pack_id FROM context_packs WHERE scene_id=? AND context_pack_version=? AND target_agent=? AND target_node=?",(scene_id,version,target_agent,target_node)).fetchone()
        if existing:
            saved=json.loads(existing[0])
            if saved != payload:
                raise ValueError(f'HISTORICAL_RECORD_CONFLICT context_pack:{existing[2]}')
            saved['context_pack_id']=existing[2]; saved['content_hash']=existing[1]; return saved
        self.db.execute("INSERT INTO context_packs(context_pack_id,book_id,chapter_id,scene_id,context_pack_version,target_agent,target_node,plan_version,content_hash,payload_json,assembled_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (pack_id,book_id,chapter_id,scene_id,version,target_agent,target_node,plan_version,content_hash,json.dumps(payload,ensure_ascii=False),stamp())); self.db.commit()
        return {**payload,"context_pack_id":pack_id,"content_hash":content_hash}
