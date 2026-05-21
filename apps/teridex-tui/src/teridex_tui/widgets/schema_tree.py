"""Lazy schema explorer.

The tree shows ``schema → {Tables, Views} → object`` eagerly. Columns,
indexes, and foreign keys are populated only when an object node is
expanded for the first time. This keeps ``populate()`` O(objects) for
wide schemas instead of O(objects * columns).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import Tree

if TYPE_CHECKING:
    from textual.widgets.tree import TreeNode

    from teridex_core.models.schema import SchemaObject, SchemaSnapshot


class SchemaTree(Tree[object]):
    DEFAULT_CSS = ""

    def __init__(self) -> None:
        super().__init__("Schema", id="schema-tree", data=None)
        self.show_root = True
        self.show_guides = True
        # Track object-node ids we've already filled so re-expansion is cheap.
        self._populated: set[int] = set()

    def populate(self, snapshot: SchemaSnapshot) -> None:
        self.clear()
        self._populated.clear()
        self.root.set_label(snapshot.database or "(database)")
        for schema_name, objects in sorted(snapshot.schemas.items()):
            schema_node = self.root.add(schema_name, data=None, expand=True)
            tables_node = schema_node.add("Tables", data=None, expand=False)
            views_node = schema_node.add("Views", data=None, expand=False)
            for obj in sorted(objects, key=lambda o: o.name):
                parent = views_node if obj.kind in {"view", "materialized_view"} else tables_node
                # Object node carries the SchemaObject; columns are added lazily
                # in ``on_tree_node_expanded``.
                parent.add(obj.name, data=obj, expand=False)
        self.root.expand()

    def on_tree_node_expanded(self, event: Tree.NodeExpanded[object]) -> None:
        node = event.node
        obj = node.data
        if obj is None:
            return
        if id(node) in self._populated:
            return
        self._fill_object_node(node, obj)  # type: ignore[arg-type]
        self._populated.add(id(node))

    def _fill_object_node(self, node: TreeNode[object], obj: SchemaObject) -> None:
        # Columns block
        if obj.columns:
            cols_node = node.add("columns", data=None, expand=True)
            for col in obj.columns:
                pk = " [yellow](PK)[/]" if col.is_primary_key else ""
                null = "" if col.nullable else " [red]NOT NULL[/]"
                cols_node.add_leaf(
                    f"[bold]{col.name}[/]  [italic dim]{col.type_native}[/]{pk}{null}",
                    data=None,
                )
        # Indexes
        if obj.indexes:
            idx_node = node.add("indexes", data=None, expand=False)
            for idx in obj.indexes:
                marker = "★" if idx.primary else ("◆" if idx.unique else "·")
                idx_node.add_leaf(
                    f"{marker} [bold]{idx.name}[/]  ({', '.join(idx.columns)})",
                    data=None,
                )
        # Foreign keys
        if obj.foreign_keys:
            fk_node = node.add("foreign keys", data=None, expand=False)
            for fk in obj.foreign_keys:
                fk_node.add_leaf(
                    f"{', '.join(fk.columns)} → "
                    f"{fk.referenced_table}({', '.join(fk.referenced_columns)})",
                    data=None,
                )
