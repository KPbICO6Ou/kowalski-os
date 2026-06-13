"""Automation recipes: YAML-defined trigger -> tool-call chains.

A recipe pairs a Trigger (manual/time/interval/inotify) with an ordered list
of Steps. Each Step is a tool call whose args may reference a previous step's
result data via ``{{ steps.<index>.<field> }}`` templates. Every step runs
through the ToolRegistry, so the security policy, confirmation and journal
apply to each call exactly as they would for a direct invocation.
"""

from __future__ import annotations

from .engine import RecipeEngine
from .model import Recipe, Step, Trigger, dump_recipe_yaml, load_recipe_yaml
from .store import RecipeStore

__all__ = [
    "Recipe",
    "RecipeEngine",
    "RecipeStore",
    "Step",
    "Trigger",
    "dump_recipe_yaml",
    "load_recipe_yaml",
]
