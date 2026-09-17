"""Command-line entry point for Phase 13 backup and isolated restore operations."""
import argparse
import json
from pathlib import Path

from backend.backup_restore import create_full_backup, restore_full_backup, restore_scene_scope, restore_single_record, verify_backup


def main():
    parser = argparse.ArgumentParser()
    command = parser.add_subparsers(dest="command", required=True)
    create = command.add_parser("create")
    create.add_argument("--source-db", type=Path, required=True)
    create.add_argument("--backup-root", type=Path, required=True)
    create.add_argument("--backup-id", required=True)
    verify = command.add_parser("verify")
    verify.add_argument("--backup", type=Path, required=True)
    restore = command.add_parser("restore")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--target-db", type=Path, required=True)
    record = command.add_parser("restore-record")
    record.add_argument("--backup", type=Path, required=True)
    record.add_argument("--target-db", type=Path, required=True)
    record.add_argument("--table", required=True)
    record.add_argument("--record-id", required=True)
    scene = command.add_parser("restore-scene")
    scene.add_argument("--backup", type=Path, required=True)
    scene.add_argument("--target-db", type=Path, required=True)
    scene.add_argument("--scene-id", required=True)
    args = parser.parse_args()
    if args.command == "create": result = {"backup": str(create_full_backup(args.source_db, args.backup_root, args.backup_id))}
    elif args.command == "verify": result = verify_backup(args.backup)
    elif args.command == "restore": result = {"database": str(restore_full_backup(args.backup, args.target_db))}
    elif args.command == "restore-record": result = {"restored": restore_single_record(args.backup, args.target_db, args.table, args.record_id)}
    else: result = restore_scene_scope(args.backup, args.target_db, args.scene_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
