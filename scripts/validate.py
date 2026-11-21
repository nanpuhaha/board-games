#!/usr/bin/env python3
"""Validate all game manifests, data JSON files, and conformance test suites."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT / "schemas"
GAMES_DIR = ROOT / "games"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_all() -> list[str]:
    errors: list[str] = []
    manifest_schema = load_json(SCHEMAS_DIR / "manifest.schema.json")
    conformance_schema = load_json(SCHEMAS_DIR / "conformance.schema.json")

    if not GAMES_DIR.exists():
        return ["games/ directory does not exist"]

    game_dirs = sorted(p for p in GAMES_DIR.iterdir() if p.is_dir() and not p.name.startswith("_"))
    if not game_dirs:
        return ["No games found under games/"]

    for game_dir in game_dirs:
        manifest_path = game_dir / "manifest.yaml"
        if not manifest_path.exists():
            errors.append(f"{game_dir.name}: missing manifest.yaml")
            continue

        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        try:
            jsonschema.validate(instance=manifest, schema=manifest_schema)
        except jsonschema.ValidationError as exc:
            errors.append(f"{manifest_path}: schema error: {exc.message}")
            continue

        if manifest["id"] != game_dir.name:
            errors.append(f"{manifest_path}: id {manifest['id']!r} != directory name {game_dir.name!r}")

        if manifest["players"]["min"] > manifest["players"]["max"]:
            errors.append(f"{manifest_path}: players.min > players.max")

        for field in ("spec_files", "data_files", "conformance_tests"):
            for rel_path in manifest.get(field, []):
                target = game_dir / rel_path
                if not target.exists():
                    errors.append(f"{game_dir.name}: missing {field} entry {rel_path}")

        for rel_path in manifest.get("data_files", []):
            target = game_dir / rel_path
            if target.exists() and target.suffix == ".json":
                try:
                    load_json(target)
                except json.JSONDecodeError as exc:
                    errors.append(f"{target}: invalid JSON: {exc}")

        seen_case_ids: set[str] = set()
        for rel_path in manifest.get("conformance_tests", []):
            target = game_dir / rel_path
            if not target.exists():
                continue
            try:
                suite = load_json(target)
                jsonschema.validate(instance=suite, schema=conformance_schema)
            except (json.JSONDecodeError, jsonschema.ValidationError) as exc:
                errors.append(f"{target}: conformance validation error: {exc}")
                continue

            if suite["game"] != manifest["id"]:
                errors.append(f"{target}: suite.game {suite['game']!r} != {manifest['id']!r}")

            for case in suite["cases"]:
                cid = case["id"]
                if cid in seen_case_ids:
                    errors.append(f"{target}: duplicate case id {cid!r} in game {game_dir.name}")
                seen_case_ids.add(cid)

    return errors


def main() -> int:
    errors = validate_all()
    if errors:
        print("Validation FAILED:")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("Validation PASSED: all manifests, data files, and conformance suites are valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
