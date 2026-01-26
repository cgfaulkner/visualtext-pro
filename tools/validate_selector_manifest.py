#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
import jsonschema

def load_json(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)

def main():
    p = argparse.ArgumentParser(description="Validate selector manifest JSON against schema")
    p.add_argument("manifest", type=Path, help="Path to selector manifest JSON (array)")
    p.add_argument("--schema", type=Path, default=Path("schemas/selector_manifest.schema.json"), help="Path to JSON schema")
    args = p.parse_args()

    manifest_path = args.manifest
    schema_path = args.schema

    if not manifest_path.exists():
        print(f"ERROR: manifest file not found: {manifest_path}", file=sys.stderr)
        sys.exit(2)
    if not schema_path.exists():
        print(f"ERROR: schema file not found: {schema_path}", file=sys.stderr)
        sys.exit(2)

    try:
        manifest = load_json(manifest_path)
        schema = load_json(schema_path)
    except Exception as e:
        print(f"ERROR loading JSON: {e}", file=sys.stderr)
        sys.exit(2)

    try:
        resolver = jsonschema.RefResolver(base_uri=f"file://{schema_path.resolve()}", referrer=schema)
        jsonschema.validate(instance=manifest, schema=schema, resolver=resolver)
        print("VALID: manifest conforms to selector schema")
        sys.exit(0)
    except jsonschema.ValidationError as ve:
        print("INVALID: manifest failed schema validation", file=sys.stderr)
        print(f"Validation error: {ve.message}", file=sys.stderr)
        # Show the path within the JSON where the error occurred for quick debugging
        if ve.path:
            print("Error at JSON path:", " -> ".join([str(p) for p in ve.path]), file=sys.stderr)
        # Print the full error for CI logs
        print(str(ve), file=sys.stderr)
        sys.exit(3)
    except Exception as e:
        print(f"ERROR during validation: {e}", file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    main()
