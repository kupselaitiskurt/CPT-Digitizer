"""
Core CPT digitizing and Excel logic (no GUI dependencies).

Used by the Streamlit app (cpt_streamlit_app.py). Keeps the same behaviour as
the desktop cpt_digitizer.py so both produce the same numbers and workbooks.
"""

import base64
import io
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from openpyxl.chart import Reference, ScatterChart, Series
from openpyxl.utils import get_column_letter
from PIL import Image

MIN_INTERVAL_FT = 0.1   # finest depth interval allowed (the standard)
FT_PER_M = 3.28084
CHANNELS = ["qc", "fs", "u2"]


@dataclass
class AxisCal:
    """Two-point linear calibration for one image axis."""
    p1: Optional[float] = None   # pixel coordinate of known point 1
    v1: Optional[float] = None   # real-world value at p1
    p2: Optional[float] = None   # pixel coordinate of known point 2
    v2: Optional[float] = None   # real-world value at p2

    @property
    def ready(self) -> bool:
        return all(x is not None for x in (self.p1, self.v1, self.p2, self.v2))

    def to_value(self, pixel: float) -> Optional[float]:
        if not self.ready or self.p2 == self.p1:
            return None
        return self.v1 + (pixel - self.p1) * (self.v2 - self.v1) / (self.p2 - self.p1)

    def to_pixel(self, value: float) -> Optional[float]:
        if not self.ready or self.v2 == self.v1:
            return None
        return self.p1 + (value - self.v1) * (self.p2 - self.p1) / (self.v2 - self.v1)


def convert_depth(value: float, from_units: str, to_units: str) -> float:
    """Convert a depth value between m and ft."""
    if from_units == to_units:
        return value
    if from_units == "m" and to_units == "ft":
        return value * FT_PER_M
    if from_units == "ft" and to_units == "m":
        return value / FT_PER_M
    return value


def min_interval(depth_units: str) -> float:
    """The 0.1 ft floor expressed in the given depth units."""
    return convert_depth(MIN_INTERVAL_FT, "ft", depth_units)


def pixel_depth_size(ycal: AxisCal) -> Optional[float]:
    """Depth represented by one image pixel row, from the Y-axis calibration."""
    if not ycal.ready or ycal.p2 == ycal.p1:
        return None
    return abs(ycal.v2 - ycal.v1) / abs(ycal.p2 - ycal.p1)


def build_mask(img: Image.Image, color, tol: float) -> np.ndarray:
    """Boolean mask of pixels within `tol` (colour distance) of the curve colour."""
    arr = np.asarray(img.convert("RGB")).astype(np.float32)
    cr, cg, cb = color
    dist = np.sqrt((arr[:, :, 0] - cr) ** 2 + (arr[:, :, 1] - cg) ** 2 + (arr[:, :, 2] - cb) ** 2)
    return dist <= tol


def extract_channel(img: Image.Image, color, tol: float,
                    xcal: AxisCal, ycal: AxisCal, di: float) -> List[Tuple[float, float]]:
    """Sample the curve at every depth step `di` between the Y calibration values."""
    mask = build_mask(img, color, tol)
    d_min = min(ycal.v1, ycal.v2)
    d_max = max(ycal.v1, ycal.v2)
    depths = np.arange(d_min, d_max + di * 0.5, di)

    results: List[Tuple[float, float]] = []
    for depth in depths:
        py = ycal.to_pixel(depth)
        if py is None:
            continue
        r0 = max(0, int(round(py)) - 2)
        r1 = min(mask.shape[0], int(round(py)) + 3)
        if r0 >= r1:
            continue
        col_hits = mask[r0:r1, :].any(axis=0)
        x_indices = np.where(col_hits)[0]
        if len(x_indices) == 0:
            continue
        weights = mask[r0:r1, x_indices].sum(axis=0).astype(float)
        x_pos = float(np.average(x_indices, weights=weights))
        value = xcal.to_value(x_pos)
        if value is not None:
            results.append((round(float(depth), 6), round(float(value), 6)))
    return results


def safe_sheet_name(name: str, used: set) -> str:
    """Excel-legal, unique sheet name (max 31 chars, no []:*?/\\)."""
    base = re.sub(r"[\[\]:*?/\\]", "_", name or "").strip() or "CPT"
    base = base[:31]
    cand, i = base, 2
    while cand.lower() in used:
        suffix = f" ({i})"
        cand = base[:31 - len(suffix)] + suffix
        i += 1
    used.add(cand.lower())
    return cand


def add_depth_chart(ws, n_points: int, name: str, units: str, depth_units: str,
                    value_col: int = 2, anchor: str = "D2"):
    """Value-vs-depth scatter chart (depth increasing downward) on a sheet.

    Depth is read from column A and values from `value_col`, starting at row 3
    (rows 1-2 hold the header and units).
    """
    chart = ScatterChart()
    chart.scatterStyle = "lineMarker"
    chart.varyColors = False
    chart.title = f"{name} vs Depth"
    chart.x_axis.title = f"{name} ({units})"
    chart.y_axis.title = f"Depth ({depth_units})"
    chart.y_axis.scaling.orientation = "maxMin"
    chart.x_axis.crosses = "max"
    chart.x_axis.delete = False
    chart.y_axis.delete = False
    chart.legend = None
    chart.width = 16
    chart.height = 18

    depth_ref = Reference(ws, min_col=1, min_row=3, max_row=n_points + 2)
    value_ref = Reference(ws, min_col=value_col, min_row=3, max_row=n_points + 2)
    series = Series(depth_ref, value_ref, title=name)
    series.marker.symbol = "circle"
    series.marker.size = 5
    series.marker.graphicalProperties.solidFill = "1F4E79"
    series.marker.graphicalProperties.line.solidFill = "1F4E79"
    series.graphicalProperties.line.solidFill = "1F4E79"
    series.graphicalProperties.line.width = 19050
    series.smooth = False
    chart.series.append(series)
    ws.add_chart(chart, anchor)


def write_cpt_sheet(wr, sheet: str, depth: list, channels: Dict[str, Tuple[list, str]],
                    depth_units: str):
    """Write one CPT to a sheet: header, units row, data, and one chart per channel.

    `channels` maps channel name -> (values, units). Channels with no data are skipped.
    """
    n = len(depth)
    data = {"depth": depth}
    units = {"depth": depth_units}
    for ch in CHANNELS:
        if ch in channels:
            vals, u = channels[ch]
            if vals and len(vals) == n and pd.Series(vals).notna().any():
                data[ch] = vals
                units[ch] = u

    df = pd.DataFrame(data)
    pd.concat([pd.DataFrame([units]), df], ignore_index=True).to_excel(
        wr, sheet_name=sheet, index=False)

    ws = wr.sheets[sheet]
    cols = list(df.columns)
    anchor_col = len(cols) + 2
    for ch in cols[1:]:
        add_depth_chart(ws, n, ch, units[ch], depth_units,
                        value_col=cols.index(ch) + 1,
                        anchor=f"{get_column_letter(anchor_col)}2")
        anchor_col += 11


def workbook_bytes(write_fn) -> bytes:
    """Build an .xlsx in memory. `write_fn(writer)` writes the sheets."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as wr:
        write_fn(wr)
    return buf.getvalue()


def encode_png(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def decode_png(b64: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
