"""Lazy schema explorer."""

from __future__ import annotations

from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from teridex_core.models.schema import SchemaSnapshot


class SchemaTree(Tree[str]):
    DEFAULT_CSS = ""

    def __init__(self) -> None:
        super().__init__("Schema", id="schema-tree")
        self.show_root = True
        self.show_guides = True

    def populate(self, snapshot: SchemaSnapshot) -> None:
        self.clear()
        self.root.set_label(snapshot.database or "(database)")
        for schema_name, objects in sorted(snapshot.schemas.items()):
            schema_node = self.root.add(schema_name, expand=True)
            tables_node = schema_node.add("Tables", expand=False)
            views_node = schema_node.add("Views", expand=False)
            for obj in sorted(objects, key=lambda o: o.name):
                parent = views_node if obj.kind in {"view", "materialized_view"} else tables_node
                self._add_object(parent, obj)
        self.root.expand()

    def _add_object(self, parent: TreeNode[str], obj: object) -> None:
        # obj.kind in tables/views; we just expose columns lazily
        node = parent.add(getattr(obj, "name", "?"), expand=False)
        for col in getattr(obj, "columns", []):
            label = f"[dim]{col.name}[/]  [italic]{col.type_native}[/]"
            node.add_leaf(label)
