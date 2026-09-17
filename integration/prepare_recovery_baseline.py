"""Confirm one legal proposal in a copied test database and snapshot its resume baseline.

This utility deliberately has no model adapter and never starts the runner.
"""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from backend.memory_confirmation import confirm_proposal


def rows(db, sql, args=()):
    return [dict(row) for row in db.execute(sql, args)]


def build_baseline(db, database_path, confirmation):
    scenes = rows(db, "SELECT scene_id, scene_number FROM scenes ORDER BY scene_number")
    result = []
    for scene in scenes:
        scene_id = scene["scene_id"]
        state = dict(db.execute(
            "SELECT task_id,current_node,status,next_action,state_version FROM task_states WHERE scene_id=?",
            (scene_id,),
        ).fetchone())
        calls = rows(db, """
            SELECT harness_call_id,agent_type,status,started_at,completed_at
            FROM harness_calls WHERE task_id=? ORDER BY started_at,harness_call_id
        """, (state["task_id"],))
        result.append({
            "scene_number": scene["scene_number"],
            "scene_id": scene_id,
            "task_state": state,
            "harness_call_count": len(calls),
            "harness_calls": calls,
            "scene_plans": rows(db, "SELECT plan_id,plan_version,story_state_version,status FROM scene_plans WHERE scene_id=? ORDER BY plan_version", (scene_id,)),
            "prose_drafts": rows(db, "SELECT draft_id,draft_version,draft_hash,plan_version,context_pack_version FROM prose_drafts WHERE scene_id=? ORDER BY draft_version", (scene_id,)),
            "quality_reports": rows(db, "SELECT report_id,draft_id,review_attempt,status FROM quality_reports WHERE scene_id=? ORDER BY report_id", (scene_id,)),
            "memory_proposals": rows(db, "SELECT proposal_id,source_draft_id,source_report_id,memory_type,target_scope,target_key,write_policy,status FROM memory_proposals WHERE scene_id=? ORDER BY proposal_version", (scene_id,)),
            "memory_records": rows(db, "SELECT memory_record_id,source_proposal_id,target_scope,memory_type,target_key,approval_status,version FROM memory_records WHERE scene_id=? ORDER BY memory_record_id", (scene_id,)),
        })
    queued = next((item["scene_id"] for item in result if item["task_state"]["status"] == "queued"), None)
    return {
        "schema": "stage12-recovery-baseline-v1",
        "database": str(database_path),
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "confirmation": confirmation,
        "next_executable_scene_id": queued,
        "scenes": result,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--proposal-id", required=True)
    parser.add_argument("--actor-id", default="real_test_operator")
    parser.add_argument("--baseline", type=Path, required=True)
    args = parser.parse_args()
    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    try:
        proposal = db.execute("SELECT status FROM memory_proposals WHERE proposal_id=?", (args.proposal_id,)).fetchone()
        if proposal is None:
            raise ValueError("PROPOSAL_NOT_FOUND")
        if proposal["status"] == "pending":
            confirmation = confirm_proposal(db, args.proposal_id, args.actor_id)
        elif proposal["status"] == "approved":
            # The confirmation committed before a previous snapshot attempt failed.
            # Reuse it rather than re-confirming or mutating the durable result.
            confirmation = {"proposal_id": args.proposal_id, "status": "completed", "reused_confirmation": True}
        else:
            raise ValueError("PROPOSAL_NOT_CONFIRMABLE")
        baseline = build_baseline(db, args.db, confirmation)
    finally:
        db.close()
    args.baseline.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"database": str(args.db), "baseline": str(args.baseline), "confirmation": confirmation, "next_executable_scene_id": baseline["next_executable_scene_id"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
