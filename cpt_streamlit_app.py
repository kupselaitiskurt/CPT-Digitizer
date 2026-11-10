"""
CPT Digitizer - Streamlit version

Run from the project folder:

    streamlit run cpt_streamlit_app.py

Runs on this computer only (localhost). No data is sent anywhere. Saved projects
use the same .dam_projects/projects.json format as the desktop cpt_digitizer.py.
"""

import io

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw
from streamlit_image_coordinates import streamlit_image_coordinates

from cpt_core import (
    CHANNELS, AxisCal, convert_depth, decode_png, encode_png, extract_channel,
    build_mask, min_interval, pixel_depth_size, safe_sheet_name, workbook_bytes,
    write_cpt_sheet,
)
from project_manager import CPTData, ProjectManager

UNIT_OPTIONS = {
    "qc": ["MPa", "ksf", "tsf", "psi", "kPa"],
    "fs": ["kPa", "ksf", "tsf", "psi", "psf"],
    "u2": ["kPa", "psi", "psf"],
}
DEFAULT_UNITS = {"qc": "tsf", "fs": "tsf", "u2": "psi"}
COLOURS = {"qc": "#e74c3c", "fs": "#27ae60", "u2": "#2980b9"}
MODES = ["Off", "Set X point 1", "Set X point 2", "Set Y point 1", "Set Y point 2", "Pick curve colour"]
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ─────────────────────────────────────────────────────────────────────────────
#  State helpers
# ─────────────────────────────────────────────────────────────────────────────

def new_channel_state() -> dict:
    return {
        "image": None,         # PIL image
        "img_src": None,       # uploader file_id the image came from
        "pts": {"x1": None, "x2": None, "y1": None, "y2": None},  # (px, py) tuples
        "color": None,         # (r, g, b)
        "extracted": [],       # list of (depth, value)
        "interval_used": None,
        "last_click": None,
    }


def init_state():
    ss = st.session_state
    if "pm" not in ss:
        ss["pm"] = ProjectManager()
    ss.setdefault("interval", 0.1)
    ss.setdefault("per_pixel", False)
    ss.setdefault("depth_units", "ft")
    ss.setdefault("depth_units_prev", "ft")
    ss.setdefault("cpt_name", "")
    ss.setdefault("new_project", "")
    ss.setdefault("confirm_del_project", False)
    ss.setdefault("confirm_del_cpt", False)
    ss.setdefault("flash", [])
    if "channels" not in ss:
        ss["channels"] = {ch: new_channel_state() for ch in CHANNELS}
    for ch in CHANNELS:
        ss.setdefault(f"{ch}_units", DEFAULT_UNITS[ch])
        ss.setdefault(f"{ch}_tol", 30)
        ss.setdefault(f"{ch}_mode", "Off")
        ss.setdefault(f"{ch}_gen", 0)
        for k in ("x1", "x2", "y1", "y2"):
            ss.setdefault(f"{ch}_{k}_val", None)


def flash(kind: str, msg: str):
    st.session_state["flash"].append((kind, msg))


def upload_key(ch: str) -> str:
    return f"{ch}_upload_{st.session_state[f'{ch}_gen']}"


def reset_channel(ch: str, keep_units: bool = True):
    """Clear a channel's image, calibration, colour and points."""
    ss = st.session_state
    ss["channels"][ch] = new_channel_state()
    for k in ("x1", "x2", "y1", "y2"):
        ss[f"{ch}_{k}_val"] = None
    ss[f"{ch}_gen"] += 1  # new, empty file uploader


def build_cal(ch: str, axis: str) -> AxisCal:
    """Calibration for one axis from the clicked pixels and the typed values."""
    pts = st.session_state["channels"][ch]["pts"]
    idx = 0 if axis == "x" else 1
    p1, p2 = pts[f"{axis}1"], pts[f"{axis}2"]
    return AxisCal(
        p1=p1[idx] if p1 else None,
        v1=st.session_state[f"{ch}_{axis}1_val"],
        p2=p2[idx] if p2 else None,
        v2=st.session_state[f"{ch}_{axis}2_val"],
    )


def channel_interval(ycal: AxisCal):
    ss = st.session_state
    if ss["per_pixel"]:
        ps = pixel_depth_size(ycal)
        if ps is None:
            return None
        return max(ps, min_interval(ss["depth_units"]))
    return ss["interval"]


def merged_df():
    """All extracted channels on one depth column (outer join)."""
    frames = [pd.DataFrame(st.session_state["channels"][ch]["extracted"],
                           columns=["depth", ch]).set_index("depth")
              for ch in CHANNELS if st.session_state["channels"][ch]["extracted"]]
    if not frames:
        return None
    return pd.concat(frames, axis=1).sort_index().reset_index()


# ─────────────────────────────────────────────────────────────────────────────
#  Callbacks (run before the page redraws, so they may change widget values)
# ─────────────────────────────────────────────────────────────────────────────

def on_depth_units_change():
    ss = st.session_state
    old, new = ss["depth_units_prev"], ss["depth_units"]
    if old != new:
        ss["interval"] = convert_depth(ss["interval"], old, new)
        ss["depth_units_prev"] = new


def create_project():
    ss = st.session_state
    name = (ss["new_project"] or "").strip()
    if not name:
        flash("warning", "Enter a project name"); return
    if name in ss["pm"].list_projects():
        flash("warning", f"A project named '{name}' already exists"); return
    ss["pm"].create_project(name)
    ss["project"] = name
    ss["new_project"] = ""
    flash("success", f"Project '{name}' created")


def delete_project():
    ss = st.session_state
    name = ss.get("project")
    if not name:
        return
    ss["pm"].delete_project(name)
    ss["project"] = None
    ss["confirm_del_project"] = False
    flash("success", f"Project '{name}' deleted")


def save_cpt():
    ss = st.session_state
    project = ss.get("project")
    name = (ss.get("cpt_name") or "").strip()
    if not project:
        flash("warning", "Create or select a project first"); return
    if not name:
        flash("warning", "Enter a CPT name (e.g. BH-01)"); return
    df = merged_df()
    if df is None:
        flash("warning", "Extract data from at least one channel first"); return

    channel_state, cal_units = {}, {}
    for ch in CHANNELS:
        s = ss["channels"][ch]
        xc, yc = build_cal(ch, "x"), build_cal(ch, "y")
        channel_state[ch] = {
            "image": encode_png(s["image"]) if s["image"] is not None else None,
            "x_cal": [xc.p1, xc.v1, xc.p2, xc.v2],
            "y_cal": [yc.p1, yc.v1, yc.p2, yc.v2],
            "curve_color": list(s["color"]) if s["color"] else None,
            "markers": [],
            "tolerance": ss[f"{ch}_tol"],
            "depth_interval": ss["interval"],
            "per_pixel": ss["per_pixel"],
        }
        cal_units[ch] = ss[f"{ch}_units"]

    def col(ch):
        return df[ch].tolist() if ch in df.columns else []

    cpt = CPTData(
        depth=df["depth"].tolist(),
        qc=col("qc"), fs=col("fs"), u2=col("u2"),
        units_qc=cal_units["qc"], units_fs=cal_units["fs"], units_u2=cal_units["u2"],
        units_depth=ss["depth_units"],
        boring_name=name,
        channel_state=channel_state,
    )
    ss["pm"].save_cpt_data(project, cpt)
    flash("success", f"Saved '{name}' to project '{project}'")
    # Clear for the next CPT (same as the desktop app)
    for ch in CHANNELS:
        reset_channel(ch)
    ss["cpt_name"] = ""


def load_cpt():
    ss = st.session_state
    project, name = ss.get("project"), ss.get("cpt_pick")
    if not project or not name:
        flash("warning", "Select a saved CPT first"); return
    cpt = ss["pm"].load_cpt_data(project, name)
    if cpt is None:
        flash("error", f"Could not load '{name}'"); return

    ss["depth_units"] = cpt.units_depth
    ss["depth_units_prev"] = cpt.units_depth
    ss["cpt_name"] = cpt.boring_name
    depth = cpt.depth
    values = {"qc": (cpt.qc, cpt.units_qc), "fs": (cpt.fs, cpt.units_fs), "u2": (cpt.u2, cpt.units_u2)}
    first_state = None

    for ch in CHANNELS:
        st_dict = (cpt.channel_state or {}).get(ch, {})
        if first_state is None and st_dict:
            first_state = st_dict
        vals, units = values[ch]
        s = new_channel_state()
        if st_dict.get("image"):
            s["image"] = decode_png(st_dict["image"])
        xc = st_dict.get("x_cal") or [None] * 4
        yc = st_dict.get("y_cal") or [None] * 4
        if xc[0] is not None:
            s["pts"]["x1"] = (xc[0], None)
        if xc[2] is not None:
            s["pts"]["x2"] = (xc[2], None)
        if yc[0] is not None:
            s["pts"]["y1"] = (None, yc[0])
        if yc[2] is not None:
            s["pts"]["y2"] = (None, yc[2])
        ss[f"{ch}_x1_val"], ss[f"{ch}_x2_val"] = xc[1], xc[3]
        ss[f"{ch}_y1_val"], ss[f"{ch}_y2_val"] = yc[1], yc[3]
        if st_dict.get("curve_color"):
            s["color"] = tuple(st_dict["curve_color"])
        if st_dict.get("tolerance") is not None:
            ss[f"{ch}_tol"] = st_dict["tolerance"]
        if units in UNIT_OPTIONS[ch]:
            ss[f"{ch}_units"] = units
        s["extracted"] = [(float(d), float(v)) for d, v in zip(depth, vals)
                          if pd.notna(d) and pd.notna(v)]
        ss["channels"][ch] = s
        ss[f"{ch}_gen"] += 1  # the uploader is empty; the saved image is kept

    if first_state:
        ss["interval"] = first_state.get("depth_interval", 0.1)
        ss["per_pixel"] = bool(first_state.get("per_pixel", False))
    flash("success", f"Loaded '{name}'")


def delete_cpt():
    ss = st.session_state
    project, name = ss.get("project"), ss.get("cpt_pick")
    if not project or not name:
        return
    ss["pm"].delete_cpt_data(project, name)
    ss["confirm_del_cpt"] = False
    flash("success", f"Deleted '{name}'")


# ─────────────────────────────────────────────────────────────────────────────
#  UI
# ─────────────────────────────────────────────────────────────────────────────

def render_flash():
    ss = st.session_state
    for kind, msg in ss["flash"]:
        getattr(st, kind)(msg)
    ss["flash"] = []


def render_sidebar():
    ss = st.session_state
    pm = ss["pm"]
    with st.sidebar:
        st.header("Settings")
        st.selectbox("Depth units", ["ft", "m"], key="depth_units",
                     on_change=on_depth_units_change)
        st.number_input(f"Depth interval ({ss['depth_units']})",
                        min_value=min_interval(ss["depth_units"]), max_value=10.0,
                        step=0.01, format="%.4f", key="interval",
                        help="Shared by qc, fs and u2. Standard is 0.1 ft.")
        st.checkbox("Every pixel row (finest the image allows, not finer than the minimum)",
                    key="per_pixel")

        st.divider()
        st.header("Project")
        projects = pm.list_projects()
        if ss.get("project") not in projects:
            ss["project"] = projects[0] if projects else None
        if projects:
            st.selectbox("Current project", projects, key="project")
        else:
            st.caption("No projects yet.")
        st.text_input("New project name", key="new_project")
        st.button("Create project", on_click=create_project)
        st.checkbox("Confirm delete project", key="confirm_del_project")
        st.button("Delete project", on_click=delete_project,
                  disabled=not (ss.get("confirm_del_project") and ss.get("project")))

        st.divider()
        st.header("CPT")
        st.text_input("CPT name", key="cpt_name", placeholder="e.g. BH-01")
        st.button("Save CPT to project", on_click=save_cpt)

        cpts = pm.list_cpt_data(ss["project"]) if ss.get("project") else []
        if ss.get("cpt_pick") not in cpts:
            ss["cpt_pick"] = cpts[0] if cpts else None
        if cpts:
            st.selectbox("Saved CPTs", cpts, key="cpt_pick")
        st.button("Load CPT", on_click=load_cpt, disabled=not cpts)
        st.checkbox("Confirm delete CPT", key="confirm_del_cpt")
        st.button("Delete CPT", on_click=delete_cpt,
                  disabled=not (cpts and ss.get("confirm_del_cpt")))

        st.divider()
        st.header("Export")
        if st.button("Build project Excel", disabled=not ss.get("project")):
            ss["project_xlsx"] = build_project_xlsx()
        if ss.get("project_xlsx"):
            data, n, name = ss["project_xlsx"]
            st.download_button(f"Download {n} CPT(s) as Excel", data=data,
                               file_name=f"{name}.xlsx", mime=XLSX_MIME)


def build_project_xlsx():
    """One workbook for every saved CPT in the current project."""
    ss = st.session_state
    pm, project = ss["pm"], ss["project"]
    cpts = []
    for name in pm.list_cpt_data(project):
        cpt = pm.load_cpt_data(project, name)
        if cpt is not None and cpt.depth:
            cpts.append(cpt)
    if not cpts:
        flash("info", "This project has no saved CPTs yet")
        return None

    def write(wr):
        used = set()
        for cpt in cpts:
            write_cpt_sheet(
                wr, safe_sheet_name(cpt.boring_name, used), cpt.depth,
                {"qc": (cpt.qc, cpt.units_qc), "fs": (cpt.fs, cpt.units_fs),
                 "u2": (cpt.u2, cpt.units_u2)},
                cpt.units_depth)

    return workbook_bytes(write), len(cpts), project


def annotate(img: Image.Image, xlines, ylines, dots) -> Image.Image:
    out = img.copy()
    d = ImageDraw.Draw(out)
    for x in xlines:
        d.line([(x, 0), (x, out.height)], fill=(255, 0, 255), width=2)
    for y in ylines:
        d.line([(0, y), (out.width, y)], fill=(0, 200, 255), width=2)
    for x, y in dots:
        d.ellipse([x - 3, y - 3, x + 3, y + 3], outline=(255, 140, 0), width=2)
    return out


def handle_click(ch: str, click: dict):
    """Apply a new click on the image according to the selected mode."""
    ss = st.session_state
    s = ss["channels"][ch]
    if not click or click.get("unix_time") == s["last_click"]:
        return False
    s["last_click"] = click.get("unix_time")
    mode = ss[f"{ch}_mode"]
    if mode == "Off" or s["image"] is None:
        return False
    nx = click["x"] * s["image"].width / click["width"]
    ny = click["y"] * s["image"].height / click["height"]
    if mode == "Set X point 1":
        s["pts"]["x1"] = (nx, ny)
    elif mode == "Set X point 2":
        s["pts"]["x2"] = (nx, ny)
    elif mode == "Set Y point 1":
        s["pts"]["y1"] = (nx, ny)
    elif mode == "Set Y point 2":
        s["pts"]["y2"] = (nx, ny)
    elif mode == "Pick curve colour":
        px = min(max(int(nx), 0), s["image"].width - 1)
        py = min(max(int(ny), 0), s["image"].height - 1)
        s["color"] = s["image"].getpixel((px, py))
    return True


def run_extraction(ch: str):
    ss = st.session_state
    s = ss["channels"][ch]
    xcal, ycal = build_cal(ch, "x"), build_cal(ch, "y")
    if not xcal.ready:
        return "Complete the X-axis calibration (both points and values)."
    if not ycal.ready:
        return "Complete the Y-axis calibration (both points and values)."
    if s["color"] is None:
        return "Pick the curve colour first."
    di = channel_interval(ycal)
    if di is None or di <= 0:
        return "Y-axis calibration is invalid, so the per-pixel interval cannot be found."
    s["extracted"] = extract_channel(s["image"], s["color"], ss[f"{ch}_tol"], xcal, ycal, di)
    s["interval_used"] = di
    return None


def render_channel(ch: str):
    ss = st.session_state
    s = ss["channels"][ch]
    units = ss[f"{ch}_units"]

    upl = st.file_uploader(f"Graph image ({ch})", type=["png", "jpg", "jpeg", "bmp", "tif", "tiff"],
                           key=upload_key(ch))
    if upl is not None and upl.file_id != s["img_src"]:
        s["image"] = Image.open(io.BytesIO(upl.getvalue())).convert("RGB")
        s["img_src"] = upl.file_id
        s["pts"] = {"x1": None, "x2": None, "y1": None, "y2": None}
        s["color"] = None
        s["extracted"] = []
        s["last_click"] = None

    c1, c2 = st.columns(2)
    with c1:
        st.selectbox("Curve units", UNIT_OPTIONS[ch], key=f"{ch}_units")
    with c2:
        st.slider("Colour tolerance", 1, 150, key=f"{ch}_tol",
                  help="Higher picks up more colours; lower avoids grid lines.")

    if s["image"] is None:
        st.info("Upload a CPT graph image to begin.")
        return

    st.radio("Clicking the image will:", MODES, key=f"{ch}_mode", horizontal=True)

    a, b = st.columns(2)
    with a:
        st.caption("X axis (values)")
        st.number_input(f"X point 1 value ({units})", value=None, key=f"{ch}_x1_val", format="%.4f")
        st.number_input(f"X point 2 value ({units})", value=None, key=f"{ch}_x2_val", format="%.4f")
    with b:
        st.caption("Y axis (depth)")
        st.number_input(f"Y point 1 depth ({ss['depth_units']})", value=None, key=f"{ch}_y1_val", format="%.4f")
        st.number_input(f"Y point 2 depth ({ss['depth_units']})", value=None, key=f"{ch}_y2_val", format="%.4f")

    xcal, ycal = build_cal(ch, "x"), build_cal(ch, "y")
    xlines = [s["pts"][k][0] for k in ("x1", "x2")
              if s["pts"][k] and s["pts"][k][0] is not None]
    ylines = [s["pts"][k][1] for k in ("y1", "y2")
              if s["pts"][k] and s["pts"][k][1] is not None]
    dots = []
    for depth, value in s["extracted"]:
        ex, ey = xcal.to_pixel(value), ycal.to_pixel(depth)
        if ex is not None and ey is not None:
            dots.append((ex, ey))

    if s["color"]:
        hex_col = "#{:02x}{:02x}{:02x}".format(*s["color"])
        st.markdown(f"Curve colour: <span style='display:inline-block;width:28px;height:14px;"
                    f"background:{hex_col};border:1px solid #888;vertical-align:middle'></span> {hex_col}",
                    unsafe_allow_html=True)
    else:
        st.caption("Curve colour: not picked yet")

    shown = annotate(s["image"], xlines, ylines, dots)
    click = streamlit_image_coordinates(shown, key=f"{ch}_click",
                                        width=min(shown.width, 900))
    if handle_click(ch, click):
        st.rerun()

    st.divider()
    if st.button("Extract data", key=f"{ch}_extract", type="primary"):
        err = run_extraction(ch)
        if err:
            st.error(err)
        else:
            st.success(f"{len(s['extracted'])} points extracted "
                       f"(interval {s['interval_used']:.4f} {ss['depth_units']})")

    if st.checkbox("Show colour mask", key=f"{ch}_mask") and s["color"]:
        mask = build_mask(s["image"], s["color"], ss[f"{ch}_tol"])
        st.image(Image.fromarray((mask * 255).astype(np.uint8)), caption="White = pixels kept as curve")

    if s["extracted"]:
        df = pd.DataFrame(s["extracted"], columns=["depth", "value"])
        chart = (alt.Chart(df)
                 .mark_line(point=True, color=COLOURS[ch])
                 .encode(x=alt.X("value:Q", title=f"{ch} ({units})"),
                         y=alt.Y("depth:Q", title=f"Depth ({ss['depth_units']})",
                                 scale=alt.Scale(reverse=True)),
                         tooltip=["depth", "value"])
                 .properties(height=500))
        st.altair_chart(chart, width="stretch")

    st.button("Clear this channel", key=f"{ch}_clear", on_click=reset_channel, args=(ch,))


def render_summary():
    ss = st.session_state
    df = merged_df()
    if df is None:
        st.info("Extract data from at least one channel to see the summary.")
        return
    units = {"depth": ss["depth_units"]}
    for ch in CHANNELS:
        if ch in df.columns:
            units[ch] = ss[f"{ch}_units"]
    st.dataframe(df, width="stretch", hide_index=True)

    name = (ss.get("cpt_name") or "").strip() or "cpt_data"
    csv_df = pd.concat([pd.DataFrame([units]), df], ignore_index=True)
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("Download CSV", data=csv_df.to_csv(index=False, float_format="%.6f"),
                           file_name=f"{name}.csv", mime="text/csv")
    with c2:
        def write(wr):
            write_cpt_sheet(
                wr, "CPT Data", df["depth"].tolist(),
                {ch: (df[ch].tolist(), ss[f"{ch}_units"]) for ch in CHANNELS if ch in df.columns},
                ss["depth_units"])
        st.download_button("Download Excel (with charts)", data=workbook_bytes(write),
                           file_name=f"{name}.xlsx", mime=XLSX_MIME)


def main():
    st.set_page_config(page_title="CPT Digitizer", layout="wide")
    init_state()
    st.title("CPT Digitizer")
    st.caption("Runs on this computer only. Upload a CPT graph, calibrate both axes, pick the curve "
               "colour, extract, then save to a project or export to Excel.")
    render_flash()
    render_sidebar()
    tabs = st.tabs(["qc", "fs", "u2", "Summary"])
    for tab, ch in zip(tabs[:3], CHANNELS):
        with tab:
            render_channel(ch)
    with tabs[3]:
        render_summary()


main()
