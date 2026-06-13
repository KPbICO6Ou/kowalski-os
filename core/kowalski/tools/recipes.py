"""recipes.* tools: list, add, run and remove automation recipes.

``recipes.add`` lets the agent/LLM author a recipe by emitting its YAML, so the
assistant can generate automations for itself. Each recipe's individual steps
still run through the ToolRegistry when executed, so per-step risk (confirmation
for destructive/out-of-allowlist steps) is enforced by the engine at run time.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..recipes.engine import RecipeEngine
from ..recipes.model import load_recipe_yaml
from .base import RiskLevel, ToolDef, ToolResult


class RecipesListArgs(BaseModel):
    pass


class RecipesAddArgs(BaseModel):
    yaml: str = Field(min_length=1, description="Full recipe definition as YAML text.")


class RecipesRunArgs(BaseModel):
    name: str = Field(min_length=1)


class RecipesRemoveArgs(BaseModel):
    name: str = Field(min_length=1)


def build_recipe_tools(engine: RecipeEngine) -> list[ToolDef]:
    store = engine._store

    async def recipes_list(args: RecipesListArgs) -> ToolResult:
        recipes = store.list()
        if not recipes:
            return ToolResult(ok=True, content="No recipes saved.", data={"recipes": []})
        summary = [
            {
                "name": r.name,
                "description": r.description,
                "trigger": r.trigger.kind,
                "steps": len(r.steps),
            }
            for r in recipes
        ]
        lines = [
            f"- {s['name']} ({s['trigger']}, {s['steps']} steps): {s['description']}".rstrip(": ")
            for s in summary
        ]
        return ToolResult(ok=True, content="\n".join(lines), data={"recipes": summary})

    async def recipes_add(args: RecipesAddArgs) -> ToolResult:
        try:
            recipe = load_recipe_yaml(args.yaml)
        except Exception as exc:
            return ToolResult(ok=False, content=f"Invalid recipe: {exc}")
        store.save(recipe)
        engine.arm(recipe)
        return ToolResult(
            ok=True, content=f"Recipe '{recipe.name}' saved.", data={"name": recipe.name}
        )

    async def recipes_run(args: RecipesRunArgs) -> ToolResult:
        try:
            results = await engine.run(args.name)
        except ValueError as exc:
            return ToolResult(ok=False, content=str(exc))
        ran = len(results)
        ok = bool(results) and all(step["ok"] for step in results)
        lines = [
            f"step {s['step']} {s['tool']}: {'ok' if s['ok'] else 'FAILED'} — {s['content']}"
            for s in results
        ]
        header = (
            f"Recipe '{args.name}' completed ({ran} steps)."
            if ok
            else f"Recipe '{args.name}' stopped after {ran} step(s)."
        )
        return ToolResult(
            ok=ok, content="\n".join([header, *lines]), data={"steps": results}
        )

    async def recipes_remove(args: RecipesRemoveArgs) -> ToolResult:
        removed = store.remove(args.name)
        if not removed:
            return ToolResult(ok=False, content=f"No recipe named '{args.name}'.")
        engine.disarm(args.name)
        return ToolResult(ok=True, content=f"Recipe '{args.name}' removed.")

    return [
        ToolDef(
            name="recipes.list",
            description="List saved automation recipes (name, trigger, step count).",
            args_model=RecipesListArgs,
            risk=RiskLevel.READ,
            handler=recipes_list,
        ),
        ToolDef(
            name="recipes.add",
            description=(
                "Create/replace an automation recipe from YAML text and arm its trigger. "
                "YAML has: name, optional description, trigger {kind, at/every_seconds/path}, "
                "and steps [{tool, args}]; args may use {{ steps.N.field }} templates."
            ),
            args_model=RecipesAddArgs,
            risk=RiskLevel.WRITE,
            handler=recipes_add,
        ),
        ToolDef(
            name="recipes.run",
            description="Run a saved recipe now; returns a per-step summary.",
            args_model=RecipesRunArgs,
            risk=RiskLevel.WRITE,
            handler=recipes_run,
        ),
        ToolDef(
            name="recipes.remove",
            description="Delete a saved recipe and unschedule its trigger.",
            args_model=RecipesRemoveArgs,
            risk=RiskLevel.WRITE,
            handler=recipes_remove,
        ),
    ]
