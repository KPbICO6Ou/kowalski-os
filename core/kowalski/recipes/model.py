"""Pydantic models for automation recipes plus YAML (de)serialization."""

from __future__ import annotations

from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

TriggerKind = Literal["manual", "time", "interval", "inotify"]


class Step(BaseModel):
    """A single tool call within a recipe.

    ``args`` values may contain ``{{ steps.N.field }}`` templates that the
    engine substitutes with field ``field`` of the N-th (zero-based) previous
    step's ToolResult.data before the call is executed.
    """

    tool: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)


class Trigger(BaseModel):
    """When a recipe fires.

    - ``manual``: never auto-fires; run explicitly via the engine.
    - ``time``: one-shot at ISO-8601 timestamp ``at``.
    - ``interval``: every ``every_seconds`` seconds.
    - ``inotify``: when the filesystem ``path`` changes (needs ``watchdog``).
    """

    kind: TriggerKind
    at: str | None = None
    every_seconds: int | None = None
    path: str | None = None

    @model_validator(mode="after")
    def _check_consistency(self) -> Trigger:
        if self.kind == "time":
            if not self.at:
                raise ValueError("time trigger requires 'at'")
        elif self.kind == "interval":
            if self.every_seconds is None:
                raise ValueError("interval trigger requires 'every_seconds'")
            if self.every_seconds <= 0:
                raise ValueError("'every_seconds' must be positive")
        elif self.kind == "inotify":
            if not self.path:
                raise ValueError("inotify trigger requires 'path'")
        return self


class Recipe(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    trigger: Trigger
    steps: list[Step] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_name(self) -> Recipe:
        if not self.name.strip():
            raise ValueError("recipe name must not be blank")
        return self


def load_recipe_yaml(text: str) -> Recipe:
    """Parse YAML text into a validated Recipe (raises on invalid input)."""
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("recipe YAML must be a mapping")
    return Recipe.model_validate(data)


def dump_recipe_yaml(recipe: Recipe) -> str:
    """Serialize a Recipe to YAML text, omitting unset trigger fields."""
    data = recipe.model_dump(exclude_none=True)
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
