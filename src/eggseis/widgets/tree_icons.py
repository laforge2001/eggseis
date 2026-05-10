"""Apply QtAwesome icons to project tree category roots."""

from __future__ import annotations

import qtawesome as qta

from eggseis.viewers.theme import colors


def apply_to_tree(tree) -> None:
    """Walk top-level item's children (category roots) and set icons.

    Per-item children intentionally get no icons — PaleoScan-aligned low
    chrome. Categories are matched by their visible label so we don't
    couple to a specific child index.
    """
    if tree.topLevelItemCount() == 0:
        return
    project_root = tree.topLevelItem(0)
    accent = colors()["accent"]
    icons = {
        "Surveys": "fa5s.cube",
        "Horizons": "fa5s.chart-area",
        "Wells": "fa5s.tint",
    }
    for i in range(project_root.childCount()):
        child = project_root.child(i)
        label = child.text(0).split()[0]  # strip any future suffix
        icon_name = icons.get(label)
        if icon_name:
            child.setIcon(0, qta.icon(icon_name, color=accent))
