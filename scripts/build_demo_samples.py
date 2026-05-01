"""Generate sample horizon CSV + LAS files for testing the import flow.

Targets `examples/demo-project/wedge.mdio` geometry:
  inline 100..131 (32 inlines, step 1)
  xline  300..323 (24 xlines, step 1)
  96 samples × 4 ms = 0..380 ms time range

Outputs land in `examples/demo-project/samples/`:
  - wedge_top.csv     XYZ CSV horizon following the wedge's first dipping
                      reflector (matches build_demo_data.py's depth math)
  - well_a.las        synthetic vertical LAS, MD = time-ms, GR + RHOB curves
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "examples" / "demo-project" / "samples"


def build_horizon_csv() -> None:
    """Wedge's first reflector lives at sample = 20 + 0.6*i + 0.3*j (4 ms/sample)."""
    out = SAMPLES / "wedge_top.csv"
    lines = ["inline,xline,time"]
    for i in range(32):
        for j in range(24):
            inline = 100 + i
            xline = 300 + j
            time_ms = (20 + 0.6 * i + 0.3 * j) * 4.0
            lines.append(f"{inline},{xline},{time_ms:.2f}")
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out} ({(32*24)} samples)")


def build_well_las() -> None:
    """Vertical synthetic well at the wedge survey center.
    MD axis treated as time-ms (matches Well.domain='time_ms')."""
    out = SAMPLES / "well_a.las"
    md = list(range(0, 384, 4))   # 0..380 ms in 4-ms steps (matches wedge sample rate)
    gr = [55 + (i % 7) * 4 + (i // 8) * 1.5 for i in range(len(md))]
    rhob = [2.4 + 0.005 * i + ((-1) ** i) * 0.02 for i in range(len(md))]

    header = (
        "~Version Information\n"
        "VERS.   2.0 :CWLS LOG ASCII STANDARD\n"
        "WRAP.   NO  :ONE LINE PER DEPTH STEP\n"
        "~Well Information\n"
        "STRT.M       0.0  :START\n"
        "STOP.M     380.0  :STOP\n"
        "STEP.M       4.0  :STEP\n"
        "NULL.    -999.25 :NULL\n"
        "WELL.    Well-A :WELL NAME\n"
        "~Curve Information\n"
        "DEPT.M  :TIME (treated as ms by eggseis time-domain wells)\n"
        "GR.GAPI :GAMMA RAY\n"
        "RHOB.G/CC :BULK DENSITY\n"
        "~ASCII\n"
    )
    rows = "\n".join(
        f"{m:7.2f}  {g:6.2f}  {rh:6.3f}"
        for m, g, rh in zip(md, gr, rhob, strict=True)
    )
    out.write_text(header + rows + "\n")
    print(f"wrote {out} ({len(md)} samples)")


def main() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    build_horizon_csv()
    build_well_las()


if __name__ == "__main__":
    main()
