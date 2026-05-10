"""Visual regression gallery — renders themed widgets to PNG.

Run via ``python -m eggseis.gallery --out docs/gallery/``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QApplication


def render_all(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])  # noqa: F841

    from eggseis.style import Theme, apply_theme

    apply_theme(Theme.DARK)

    written: list[Path] = []
    written.extend(_render_welcome(out_dir))
    written.extend(_render_sections(out_dir))
    written.extend(_render_map_view(out_dir))
    written.extend(_render_log_panel(out_dir))
    return written


def _render_welcome(out_dir: Path) -> list[Path]:
    from eggseis.widgets.welcome import WelcomeWidget

    w = WelcomeWidget()
    w.resize(640, 480)
    return [_grab(w, out_dir / "welcome.png")]


def _render_sections(out_dir: Path) -> list[Path]:
    from eggseis.data import SeismicVolume
    from eggseis.viewers.section import SectionViewer

    backend = _fake_backend()

    out: list[Path] = []
    for cmap in ("vik", "batlow", "gray"):
        sv = SectionViewer()
        sv.resize(640, 480)
        sv.set_volume(SeismicVolume(backend))
        sv.set_colormap(cmap)
        out.append(_grab(sv, out_dir / f"section_{cmap}.png"))
    return out


def _render_map_view(out_dir: Path) -> list[Path]:
    from eggseis.data import SeismicVolume
    from eggseis.viewers.map_view import MapViewWidget

    mv = MapViewWidget()
    mv.resize(640, 240)
    mv.set_volume(SeismicVolume(_fake_backend()))
    mv.add_well_marker("WA", (310.0, 110.0))
    return [_grab(mv, out_dir / "map_view.png")]


def _render_log_panel(out_dir: Path) -> list[Path]:
    from eggseis.data.well import Well
    from eggseis.viewers.well_log_panel import WellLogPanel

    n = 50
    md = np.linspace(0.0, 196.0, n, dtype=np.float32)  # time in ms (sample_rate 4 ms × 49)
    deviation = np.column_stack(
        [md, np.zeros(n, dtype=np.float32), np.zeros(n, dtype=np.float32)]
    ).astype(np.float32)
    well = Well(
        name="WA",
        deviation=deviation,
        logs={"GR": np.linspace(40, 90, n, dtype=np.float32)},
        markers=[],
        surface_xy=(310.0, 110.0),
    )
    panel = WellLogPanel()
    panel.resize(220, 480)
    panel.set_well(well, sample_rate_ms=4.0)
    return [_grab(panel, out_dir / "log_panel.png")]


def _grab(widget, path: Path) -> Path:
    widget.show()
    QApplication.processEvents()
    pix = widget.grab()
    pix.save(str(path), "PNG")
    return path


def _fake_backend():
    """Tiny deterministic in-memory backend for gallery rendering.

    Implements the SeismicBackend protocol just enough for SectionViewer
    and MapViewWidget. Does not import test fixtures (tests.conftest); the
    gallery is a runtime artifact and must not depend on pytest packaging.
    """
    from eggseis.data import SurveyGeometry

    class _Backend:
        def __init__(self):
            self.geometry = SurveyGeometry(
                inline_min=100,
                inline_max=219,
                inline_step=1,
                xline_min=300,
                xline_max=379,
                xline_step=1,
                n_samples=200,
                sample_rate_ms=4.0,
            )
            rng = np.random.default_rng(seed=42)
            self._cube = rng.standard_normal(self.geometry.shape).astype(np.float32)

        @property
        def dtype(self) -> np.dtype:
            return self._cube.dtype

        @property
        def version(self) -> tuple:
            return ("gallery-fake", id(self))

        def read_inline(self, inline: int) -> np.ndarray:
            i = (inline - self.geometry.inline_min) // self.geometry.inline_step
            return self._cube[i, :, :]

        def read_xline(self, xline: int) -> np.ndarray:
            x = (xline - self.geometry.xline_min) // self.geometry.xline_step
            return self._cube[:, x, :]

        def read_timeslice(self, sample_index: int) -> np.ndarray:
            return self._cube[:, :, sample_index]

        def read_trace(self, inline: int, xline: int) -> np.ndarray:
            i = (inline - self.geometry.inline_min) // self.geometry.inline_step
            x = (xline - self.geometry.xline_min) // self.geometry.xline_step
            return self._cube[i, x, :]

    return _Backend()


def main() -> None:
    parser = argparse.ArgumentParser(description="Render gallery PNGs")
    parser.add_argument("--out", default="docs/gallery", type=Path)
    args = parser.parse_args()
    paths = render_all(args.out)
    for p in paths:
        print(p)


if __name__ == "__main__":
    main()
