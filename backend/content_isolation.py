FORBIDDEN_TERMS=('ancient_village','eastern_country','古代王国')
def validate_memory_content(*, book_id, scene_id, target_key, evidence, after_value, draft_text, context_pack):
    if any(term in str(evidence)+' '+str(after_value) for term in FORBIDDEN_TERMS): raise ValueError('CROSS_BOOK_CONTAMINATION')
    if target_key and ('pack_v' in target_key or 'context' in target_key): raise ValueError('CROSS_BOOK_CONTAMINATION')
    haystack=str(draft_text)+' '+str(context_pack)
    if evidence and evidence not in haystack: raise ValueError('CROSS_BOOK_CONTAMINATION')
    return True
