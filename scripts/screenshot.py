"""Render a screenshot of the eggseis GUI for documentation.

Boots MainWindow against examples/demo-project/, opens the demo survey,
then grabs the rendered window to PNG. Runs offscreen by default.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from eggseis.app import MainWindow

ROOT = Path(__file__).resolve().parents[1]
DEMO_PROJECT = ROOT / "examples" / "demo-project"
OUTPUT = ROOT / "docs" / "m2-screenshot.png"


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1280, 800)
    win.open_project(DEMO_PROJECT)

    project = win._project  # type: ignore[attr-defined]
    if not project or not project.surveys:
        print("demo project has no surveys", file=sys.stderr)
        return 1
    win.open_survey(project.surveys[0].path)
    win.show()

    # let Qt lay out and paint at least one frame before grabbing
    def grab() -> None:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        win.grab().save(str(OUTPUT))
        print(f"wrote {OUTPUT.relative_to(ROOT)}")
        app.quit()

    QTimer.singleShot(200, grab)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
