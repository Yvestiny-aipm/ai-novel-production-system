"""MemoryProposal 分类、权限和人工确认恢复流程。"""
import json, time
AUTO_SCOPE='scene_memory'
CONFIRM_SCOPES={'book_memory','character_memory'}
def confirm_proposal(db, proposal_id, actor_id):
    row=db.execute('select * from memory_proposals where proposal_id=?',(proposal_id,)).fetchone()
    if not row: raise ValueError('PROPOSAL_NOT_FOUND')
    if row['status']!='pending': raise ValueError('PROPOSAL_NOT_PENDING')
    if row['write_policy']=='never_auto_write': raise ValueError('PROPOSAL_WRITE_FORBIDDEN')
    if row['target_scope'] not in CONFIRM_SCOPES or row['write_policy']!='human_confirmation': raise ValueError('PROPOSAL_PERMISSION_INVALID')
    try:
        db.execute("insert into memory_records(memory_record_id,book_id,scene_id,target_scope,memory_type,target_key,value_json,source_proposal_id,approval_status,version,created_at) values (?,?,?,?,?,?,?,?,?,?,?)",('mem_'+proposal_id,row['book_id'],row['scene_id'],row['target_scope'],row['memory_type'],row['target_key'],row['after_value_json'],proposal_id,'approved',1,str(time.time())))
        db.execute("update memory_proposals set status='approved' where proposal_id=?",(proposal_id,))
    except Exception:
        db.rollback()
        raise
    task=db.execute('select task_id from task_states where scene_id=?',(row['scene_id'],)).fetchone()
    # current_node records the last business node reached; status is the lifecycle terminal state.
    if task: db.execute("update task_states set status='completed',current_node='human_confirmation',next_action='none',updated_at=? where task_id=?",(str(time.time()),task[0]))
    scene=db.execute('select scene_number,book_id from scenes where scene_id=?',(row['scene_id'],)).fetchone()
    if scene: db.execute("update task_states set status='queued' where scene_id=(select scene_id from scenes where book_id=? and scene_number=?) and status='paused'",(scene[1],scene[0]+1))
    db.commit(); return {'proposal_id':proposal_id,'task_id':task[0] if task else None,'status':'completed'}
