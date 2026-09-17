from content_isolation import validate_memory_content
try: validate_memory_content(book_id='b',scene_id='s',target_key='ancient_village',evidence='ancient_village',after_value='ancient_village',draft_text='',context_pack={})
except ValueError as e: assert str(e)=='CROSS_BOOK_CONTAMINATION'
else: raise AssertionError('cross-book content accepted')
assert validate_memory_content(book_id='b',scene_id='s',target_key='harbor',evidence='harbor',after_value='harbor record',draft_text='harbor',context_pack={})
print('content isolation ok')
