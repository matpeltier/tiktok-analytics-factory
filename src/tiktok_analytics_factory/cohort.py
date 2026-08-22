"""Loader and validation for the pilot cohort contract.

Validates ``config/pilot_cohort.json`` against
``schemas/pilot_cohort.schema.json`` using a small standard-library validator
covering the JSON Schema keywords used by that document (the project avoids
heavy dependencies by design).

Fails loudly on any violation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "pilot_cohort.json"
SCHEMA_PATH = REPO_ROOT / "schemas" / "pilot_cohort.schema.json"


class CohortConfigError(ValueError):
    """Raised when the cohort config is missing or violates its schema."""


def load_config(path: Path | None = None) -> dict[str, Any]:
    cfg_path = path or CONFIG_PATH
    if not cfg_path.exists():
        raise CohortConfigError(f"cohort config not found: {cfg_path}")
    with open(cfg_path, encoding="utf-8") as fh:
        return json.load(fh)


def load_schema(path: Path | None = None) -> dict[str, Any]:
    schema_path = path or SCHEMA_PATH
    if not schema_path.exists():
        raise CohortConfigError(f"cohort schema not found: {schema_path}")
    with open(schema_path, encoding="utf-8") as fh:
        return json.load(fh)


def validate(instance: Any, schema: dict[str, Any], root: dict[str, Any] | None = None) -> list[str]:
    """Return a list of violation messages (empty when valid)."""
    root = root if root is not None else schema
    errors: list[str] = []
    where = "$"

    if "$ref" in schema:
        ref = schema["$ref"]
        assert ref.startswith("#/")
        target: Any = root
        for part in ref[2:].split("/"):
            target = target[part]
        return validate(instance, target, root)

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{where}: expected const {schema['const']!r}, got {instance!r}")

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{where}: {instance!r} not in enum {schema['enum']!r}")

    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        checks = {
            "object": lambda v: isinstance(v, dict),
            "array": lambda v: isinstance(v, list),
            "string": lambda v: isinstance(v, str),
            "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "boolean": lambda v: isinstance(v, bool),
            "null": lambda v: v is None,
        }
        if instance is None and "null" not in types:
            errors.append(f"{where}: null not allowed (expected {expected})")
        elif instance is not None and not any(checks[t](instance) for t in types):
            errors.append(f"{where}: expected type {expected}, got {type(instance).__name__}")
            return errors

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{where}: shorter than minLength={schema['minLength']}")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{where}: {instance} < minimum={schema['minimum']}")
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            errors.append(f"{where}: {instance} <= exclusiveMinimum={schema['exclusiveMinimum']}")

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{where}: missing required property {key!r}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in props:
                    errors.append(f"{where}: unexpected property {key!r}")
        for key, sub in props.items():
            if key in instance:
                for msg in validate(instance[key], sub, root):
                    errors.append(msg.replace("$", f"{where}.{key}", 1))

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{where}: fewer than minItems={schema['minItems']}")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{where}: more than maxItems={schema['maxItems']}")
        if schema.get("uniqueItems"):
            seen = [json.dumps(item, sort_keys=True) for item in instance]
            if len(seen) != len(set(seen)):
                errors.append(f"{where}: items are not unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(instance):
                for msg in validate(item, item_schema, root):
                    errors.append(msg.replace("$", f"{where}[{i}]", 1))

    return errors


def validate_config(config: dict[str, Any], schema: dict[str, Any]) -> None:
    errors = validate(config, schema)
    if errors:
        raise CohortConfigError(
            "pilot cohort config failed validation:\n" + "\n".join(sorted(errors))
        )


def load_validated_config(
    config_path: Path | None = None, schema_path: Path | None = None
) -> dict[str, Any]:
    """Load the cohort config and fail loudly if it violates the schema."""
    config = load_config(config_path)
    schema = load_schema(schema_path)
    validate_config(config, schema)
    return config


def require_approved(config: dict[str, Any]) -> dict[str, Any]:
    """Fail loudly unless the cohort has explicit owner approval."""
    if config.get("approval_status") != "approved":
        raise CohortConfigError(
            f"cohort {config.get('cohort_id')!r} is not owner-approved "
            f"(approval_status={config.get('approval_status')!r}); "
            "dataset work must not proceed until approval_status == 'approved'"
        )
    return config
