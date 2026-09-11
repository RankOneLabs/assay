from __future__ import annotations

import argparse

from assay.store import ObjectIntegrityError, ObjectStore
from assay.verify import export_bundle, verify_bundle


def main() -> int:
    parser = argparse.ArgumentParser(prog="assay")
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("bundle")
    verify.add_argument("root_ref")
    export = subparsers.add_parser("export")
    export.add_argument("store")
    export.add_argument("root_ref")
    export.add_argument("destination")
    args = parser.parse_args()
    if args.command == "export":
        try:
            export_bundle(ObjectStore(args.store), args.root_ref, args.destination)
        except (OSError, ValueError, ObjectIntegrityError) as exc:
            print(f"export_failed: {exc}")
            return 1
        return 0
    failures = verify_bundle(ObjectStore(args.bundle), args.root_ref)
    for failure in failures:
        print(f"{failure.code}: {failure.message}")
    return 1 if failures else 0
