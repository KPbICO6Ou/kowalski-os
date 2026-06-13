"""Filesystem-backed recipe store: one ``<name>.yaml`` file per recipe."""

from __future__ import annotations

import logging
from pathlib import Path

from .model import Recipe, dump_recipe_yaml, load_recipe_yaml

log = logging.getLogger(__name__)

DEFAULT_RECIPES_DIR = Path("~/.config/kowalski/recipes").expanduser()


class RecipeStore:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.directory / f"{name}.yaml"

    def save(self, recipe: Recipe) -> Path:
        path = self._path(recipe.name)
        path.write_text(dump_recipe_yaml(recipe), encoding="utf-8")
        return path

    def get(self, name: str) -> Recipe | None:
        path = self._path(name)
        if not path.exists():
            return None
        return load_recipe_yaml(path.read_text(encoding="utf-8"))

    def list(self) -> list[Recipe]:
        recipes: list[Recipe] = []
        for path in sorted(self.directory.glob("*.yaml")):
            try:
                recipes.append(load_recipe_yaml(path.read_text(encoding="utf-8")))
            except Exception:
                log.warning("skipping invalid recipe file: %s", path, exc_info=True)
        return recipes

    def remove(self, name: str) -> bool:
        path = self._path(name)
        if not path.exists():
            return False
        path.unlink()
        return True
