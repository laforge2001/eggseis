"""Command-line interface for eggseis."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import typer
from rich.console import Console
from rich.table import Table

from eggseis.backends.mdio import MDIOBackend
from eggseis.data import SeismicVolume

app = typer.Typer(help="eggseis — open-source seismic interpretation", no_args_is_help=True)
console = Console()


def _open(survey: Path) -> SeismicVolume:
    backend = MDIOBackend(survey)
    return SeismicVolume(backend, name=survey.stem)


@app.command()
def info(survey: Path = typer.Argument(..., help="Path to MDIO survey")) -> None:
    """Show summary information about a seismic survey."""
    volume = _open(survey)
    g = volume.geometry

    table = Table(title=f"Survey: {volume.name}", show_header=False)
    table.add_column("Property", style="cyan")
    table.add_column("Value")
    table.add_row("Inline range", f"{g.inline_min}–{g.inline_max} (step {g.inline_step})")
    table.add_row("Xline range", f"{g.xline_min}–{g.xline_max} (step {g.xline_step})")
    table.add_row("Samples", str(g.n_samples))
    table.add_row("Sample rate", f"{g.sample_rate_ms} ms")
    table.add_row("Time max", f"{g.time_max_ms:.1f} ms")
    table.add_row("Shape", f"{g.shape}")
    table.add_row("Dtype", str(volume.dtype))
    console.print(table)


@app.command("dump-inline")
def dump_inline(
    survey: Path = typer.Argument(..., help="Path to MDIO survey"),
    inline: int = typer.Argument(..., help="Inline number"),
    output: Path = typer.Option("inline.png", "--output", "-o", help="Output PNG path"),
) -> None:
    """Read an inline and save it as a PNG (1–99 percentile linear stretch)."""
    from PIL import Image

    volume = _open(survey)
    data = volume.read_inline(inline)

    arr = data.T  # transpose so time is vertical
    p_low, p_high = np.percentile(arr, [1, 99])
    if p_high == p_low:
        normalized = np.zeros_like(arr, dtype=np.float32)
    else:
        normalized = np.clip((arr - p_low) / (p_high - p_low), 0, 1)
    arr_u8 = (normalized * 255).astype(np.uint8)

    Image.fromarray(arr_u8).save(output)
    size_mb = output.stat().st_size / (1024 * 1024)
    console.print(
        f"[green]Wrote[/green] {output} ({arr.shape[1]}×{arr.shape[0]}, {size_mb:.1f} MB)"
    )


@app.command()
def plugins(
    show_params: bool = typer.Option(
        False, "--params", "-p", help="Show parameter declarations for each plugin"
    ),
) -> None:
    """List discovered plugins from all configured sources."""
    from eggseis.plugin_loader import discover_all, resolved_user_dirs

    specs = discover_all()

    dirs = resolved_user_dirs()
    if dirs:
        console.print("[dim]Plugin directories scanned:[/dim]")
        for d in dirs:
            mark = "" if d.is_dir() else " [yellow](missing)[/yellow]"
            console.print(f"  {d}{mark}")
        console.print()

    table = Table(title=f"Plugins ({len(specs)})", show_lines=show_params)
    table.add_column("Name", style="cyan")
    table.add_column("Version")
    table.add_column("Source")
    if show_params:
        table.add_column("Parameters")

    for spec in sorted(specs, key=lambda s: s.name):
        source = spec.source_path or "(built-in / entry point)"
        row = [spec.name, spec.version, source]
        if show_params:
            if spec.params_decl:
                lines = []
                for pname, p in spec.params_decl.items():
                    bits = [f"default={p.default}"]
                    if p.min is not None or p.max is not None:
                        bits.append(f"range=[{p.min}, {p.max}]")
                    if p.units:
                        bits.append(f"units={p.units}")
                    lines.append(f"{pname}: {', '.join(bits)}")
                row.append("\n".join(lines))
            else:
                row.append("(none)")
        table.add_row(*row)
    console.print(table)


@app.command()
def gui(
    project_dir: Path | None = typer.Argument(
        None, help="Optional project directory to open on launch"
    ),
) -> None:
    """Launch the eggseis GUI."""
    import sys

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise typer.BadParameter(
            "GUI dependencies not installed. Install with: pip install 'eggseis[gui]'"
        ) from exc

    from eggseis.app import MainWindow

    qt_app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    if project_dir is not None:
        win.open_project(project_dir)
    win.show()
    sys.exit(qt_app.exec())


if __name__ == "__main__":
    app()
