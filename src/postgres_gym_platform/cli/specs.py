"""One payload contract shared with REST; CLI does not duplicate schema defaults."""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from ..schemas import Benchmark, Deployment, Evaluation, ModelImport, Training

SCHEMAS = {
    "benchmark": Benchmark,
    "deployment": Deployment,
    "evaluation": Evaluation,
    "model": ModelImport,
    "training": Training,
}


def read_mapping(path: Path) -> dict[str, Any]:
    text = path.expanduser().read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        import yaml

        try:
            value = yaml.safe_load(text)
        except yaml.YAMLError:
            raise ValueError("Invalid YAML specification") from None
    else:
        value = json.loads(text)
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Configuration must be an object with string keys")
    return value


def validate(model: type[BaseModel], body: dict[str, Any]) -> dict[str, Any]:
    try:
        return model.model_validate(body).model_dump(mode="json")
    except ValidationError as exc:
        message = "; ".join(
            ".".join(map(str, item["loc"])) + ": " + item["msg"]
            for item in exc.errors(include_input=False)
        )
        raise ValueError(message) from None


def build(kind: str, config: Path | None, **fields: Any) -> dict[str, Any]:
    explicit = {key: value for key, value in fields.items() if value is not None}
    if config is not None and explicit:
        raise ValueError(
            "--config cannot be combined with payload arguments/options: "
            + ", ".join(explicit)
        )
    return validate(SCHEMAS[kind], read_mapping(config) if config else explicit)
