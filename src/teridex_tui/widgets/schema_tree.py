"""Lazy schema explorer.

The tree shows ``schema → {Tables, Views} → object`` eagerly. Columns,
indexes, and foreign keys are populated only when an object node is
expanded for the first time. This keeps ``populate()`` O(objects) for
wide schemas instead of O(objects * columns).
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from rich.markup import escape
from textual.widgets import Tree

from teridex_core.models.schema import SchemaObject

if TYPE_CHECKING:
    from textual.widgets.tree import TreeNode

    from teridex_core.models.schema import SchemaSnapshot


class SchemaTree(Tree[object]):
    DEFAULT_CSS = ""

    def __init__(self) -> None:
        super().__init__("Schema", id="schema-tree", data=None)
        self.show_root = True
        self.show_guides = True

    def populate(self, snapshot: SchemaSnapshot) -> None:
        self.clear()
        self.root.set_label(escape(snapshot.database or "(database)"))
        for schema_name, objects in sorted(snapshot.schemas.items()):
            schema_node = self.root.add(escape(schema_name), data=None, expand=True)
            tables_node = schema_node.add("Tables", data=None, expand=False)
            views_node = schema_node.add("Views", data=None, expand=False)
            for obj in sorted(objects, key=lambda o: o.name):
                parent = views_node if obj.kind in {"view", "materialized_view"} else tables_node
                # Object node carries the SchemaObject; columns are added lazily
                # in ``on_tree_node_expanded``.
                parent.add(escape(obj.name), data=obj, expand=False)
        self.root.expand()

    async def on_tree_node_expanded(self, event: Tree.NodeExpanded[object]) -> None:
        node = event.node
        obj = node.data
        if not isinstance(obj, SchemaObject):
            return
        if node.children:
            return

        # Fetch columns/indexes/foreign keys lazily if not already present.
        if not obj.columns:
            app_state = getattr(self.app, "state", None)
            introspector = (
                getattr(app_state, "introspector", None) if app_state is not None else None
            )
            if introspector is not None:
                schema_name = obj.schema_name or ""
                try:
                    if obj.kind == "table":
                        cols, fks, indexes = await asyncio.gather(
                            introspector.fetch_columns(schema_name, obj.name),
                            introspector.fetch_foreign_keys(schema_name, obj.name),
                            introspector.fetch_indexes(schema_name, obj.name),
                        )
                    else:
                        cols = await introspector.fetch_columns(schema_name, obj.name)
                        fks = []
                        indexes = []

                    obj = obj.model_copy(
                        update={
                            "columns": cols,
                            "indexes": indexes,
                            "foreign_keys": fks,
                        }
                    )
                    introspector.update_object(schema_name, obj.name, cols, fks, indexes)
                    node.data = obj
                except Exception as exc:
                    status = getattr(self.app, "_status", None)
                    if status is not None:
                        with contextlib.suppress(Exception):
                            status().message = (
                                f"[red]Failed to introspect "
                                f"{escape(obj.name)}: {escape(str(exc))}[/]"
                            )
                    return

        self._fill_object_node(node, obj)

    def _fill_object_node(self, node: TreeNode[object], obj: SchemaObject) -> None:
        # Columns block
        if obj.columns:
            cols_node = node.add("columns", data=None, expand=True)
            for col in obj.columns:
                pk = " [yellow](PK)[/]" if col.is_primary_key else ""
                null = "" if col.nullable else " [red]NOT NULL[/]"
                cols_node.add_leaf(
                    f"[bold]{escape(col.name)}[/]  "
                    f"[italic dim]{escape(col.type_native)}[/]{pk}{null}",
                    data=None,
                )
        # Indexes
        if obj.indexes:
            idx_node = node.add("indexes", data=None, expand=False)
            for idx in obj.indexes:
                marker = "★" if idx.primary else ("◆" if idx.unique else "·")
                idx_node.add_leaf(
                    f"{marker} [bold]{escape(idx.name)}[/]  ({escape(', '.join(idx.columns))})",
                    data=None,
                )
        # Foreign keys
        if obj.foreign_keys:
            fk_node = node.add("foreign keys", data=None, expand=False)
            for fk in obj.foreign_keys:
                fk_node.add_leaf(
                    f"{escape(', '.join(fk.columns))} → "
                    f"{escape(fk.referenced_table)}"
                    f"({escape(', '.join(fk.referenced_columns))})",
                    data=None,
                )
