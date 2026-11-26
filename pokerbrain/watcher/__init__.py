"""Citirea mesei de pe ecran: captura, profiluri de layout, recunoasterea cartilor si a textului."""
from .layout import LayoutProfile, Region, layouts_dir, list_layouts
from .watcher import TableWatcher, TableSnapshot

__all__ = ["LayoutProfile", "Region", "layouts_dir", "list_layouts", "TableWatcher", "TableSnapshot"]
