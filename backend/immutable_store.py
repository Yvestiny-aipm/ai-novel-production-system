"""Append-only business snapshots. Status transitions are separate explicit actions."""
import json


class HistoricalRecordConflict(ValueError):
    pass


def insert_snapshot(db, table, columns, values, *, commit=True):
    allowed = {'scene_plans', 'prose_drafts', 'quality_reports', 'memory_proposals', 'memory_records'}
    if table not in allowed:
        raise ValueError('UNSUPPORTED_SNAPSHOT_TABLE')
    candidate = dict(zip(columns, values))
    cursor = db.execute(f'SELECT * FROM {table} WHERE {columns[0]}=?', (values[0],))
    row = cursor.fetchone()
    if row is not None:
        saved = dict(zip([d[0] for d in cursor.description], row))
        def comparable(key, value):
            return json.loads(value) if key.endswith('_json') and value is not None else value
        changed = [k for k, v in candidate.items() if k != 'created_at'
                   and comparable(k, v) != comparable(k, saved[k])]
        if changed:
            raise HistoricalRecordConflict(f'HISTORICAL_RECORD_CONFLICT {table}:{values[0]} fields={changed}')
        return False
    db.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", values)
    if commit:
        db.commit()
    return True
