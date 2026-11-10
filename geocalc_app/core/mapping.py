"""
GeoCalc Pro - Map & Visualization Engine
Generates Folium interactive maps and matplotlib fence diagrams.
"""
import os
import json
import math
import tempfile
from typing import Optional
import textwrap
import json
import folium
from folium import plugins
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch
import numpy as np

# USCS color mapping for soil visualization
USCS_COLORS = {
    "GW": "#8B6914",  "GP": "#A0522D",  "GM": "#CD853F",  "GC": "#DEB887",
    "SW": "#DAA520",  "SP": "#F0E68C",  "SM": "#BDB76B",  "SC": "#9ACD32",
    "ML": "#90EE90",  "CL": "#3CB371",  "OL": "#228B22",  "MH": "#006400",
    "CH": "#2E8B57",  "OH": "#556B2F",  "Pt": "#8B4513",
    "":   "#CCCCCC",
}

USCS_HATCH = {
    "GW": "ooo", "GP": "ooo", "GM": "...", "GC": "xxx",
    "SW": "...", "SP": "...", "SM": "...", "SC": "xxx",
    "ML": "---", "CL": "///", "OL": "\\\\\\", "MH": "---",
    "CH": "///", "OH": "\\\\\\", "Pt": "+++", "": "",
}


# ── Interactive Map ───────────────────────────────────────────────────────────

def build_project_map(borings: list[dict], cpt_soundings: list[dict],
                      output_html: str, project_name: str = "Project") -> str:
    """
    Build a Folium interactive map with boring and CPT locations.
    Returns path to saved HTML file.
    """
    # Determine map center
    lats = [b["latitude"] for b in borings if b.get("latitude")]
    lons = [b["longitude"] for b in borings if b.get("longitude")]
    for c in cpt_soundings:
        if c.get("latitude"):
            lats.append(c["latitude"])
            lons.append(c["longitude"])

    if lats and lons:
        center_lat = sum(lats) / len(lats)
        center_lon = sum(lons) / len(lons)
    else:
        center_lat, center_lon = 25.7617, -80.1918  # Default: Miami

    # Create map with satellite + street tile options
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=17,
        tiles=None
    )

    # Tile layers
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery",
        name="Satellite",
        overlay=False,
        control=True
    ).add_to(m)

    folium.TileLayer(
        tiles="OpenStreetMap",
        name="Street Map",
        overlay=False,
        control=True
    ).add_to(m)

    # Feature groups
    boring_group = folium.FeatureGroup(name="Boring Locations", show=True)
    cpt_group = folium.FeatureGroup(name="CPT Soundings", show=True)

    # Add borings
    for b in borings:
        lat, lon = b.get("latitude"), b.get("longitude")
        if not lat or not lon:
            continue

        # Build popup HTML
        layers_html = ""
        for layer in b.get("layers", [])[:8]:
            color = USCS_COLORS.get(layer.get("uscs_symbol", ""), "#CCC")
            layers_html += f"""
            <tr>
              <td style='padding:2px 6px; border:1px solid #ddd'>{layer['depth_top']:.1f}–{layer['depth_bottom']:.1f}</td>
              <td style='padding:2px 6px; border:1px solid #ddd; background:{color}; font-weight:bold'>{layer.get('uscs_symbol','')}</td>
              <td style='padding:2px 6px; border:1px solid #ddd; max-width:200px'>{layer.get('soil_description','')[:60]}</td>
              <td style='padding:2px 6px; border:1px solid #ddd; text-align:center'>{layer.get('n_value') or ''}</td>
            </tr>"""

        popup_html = f"""
        <div style='font-family: Arial, sans-serif; min-width: 300px'>
          <h3 style='background:#1B3A5C; color:white; padding:8px; margin:0'>{b['boring_id']}</h3>
          <table style='width:100%; border-collapse:collapse; margin-top:4px'>
            <tr><td style='padding:3px 8px; color:#555; width:140px'><b>Total Depth</b></td>
                <td style='padding:3px 8px'>{b.get('total_depth') or 'N/A'} ft</td></tr>
            <tr style='background:#f5f5f5'><td style='padding:3px 8px; color:#555'><b>Ground Elev.</b></td>
                <td style='padding:3px 8px'>{b.get('elevation') or 'N/A'} ft</td></tr>
            <tr><td style='padding:3px 8px; color:#555'><b>Water Table</b></td>
                <td style='padding:3px 8px'>{b.get('water_table') or 'N/A'} ft</td></tr>
            <tr style='background:#f5f5f5'><td style='padding:3px 8px; color:#555'><b>Date Drilled</b></td>
                <td style='padding:3px 8px'>{b.get('date_drilled') or 'N/A'}</td></tr>
          </table>
          {'<h4 style="margin:8px 0 4px 0; color:#1B3A5C">Soil Profile</h4><table style="width:100%; border-collapse:collapse"><thead><tr style="background:#1B3A5C; color:white"><th style="padding:3px 6px; text-align:left">Depth (ft)</th><th>USCS</th><th style="text-align:left">Description</th><th>N</th></tr></thead><tbody>' + layers_html + '</tbody></table>' if layers_html else ''}
        </div>"""

        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup_html, max_width=400),
            tooltip=f"<b>{b['boring_id']}</b><br>Depth: {b.get('total_depth') or '?'} ft",
            icon=folium.Icon(
                color="darkblue",
                icon="circle",
                prefix="fa",
                icon_color="white"
            )
        ).add_to(boring_group)

        # Add boring ID label
        folium.Marker(
            location=[lat + 0.00003, lon],
            icon=folium.DivIcon(
                html=f'<div style="font-weight:bold; font-size:10px; color:#1B3A5C; '
                     f'white-space:nowrap; text-shadow: 1px 1px 2px white">{b["boring_id"]}</div>',
                icon_size=(60, 20),
                icon_anchor=(0, 20)
            )
        ).add_to(boring_group)

    # Add CPTs
    for c in cpt_soundings:
        lat, lon = c.get("latitude"), c.get("longitude")
        if not lat or not lon:
            continue

        popup_html = f"""
        <div style='font-family: Arial, sans-serif'>
          <h3 style='background:#8B0000; color:white; padding:8px; margin:0'>{c['cpt_id']}</h3>
          <table style='width:100%; border-collapse:collapse; margin-top:4px'>
            <tr><td style='padding:3px 8px; color:#555'><b>Elevation</b></td>
                <td style='padding:3px 8px'>{c.get('elevation') or 'N/A'}</td></tr>
            <tr style='background:#f5f5f5'><td style='padding:3px 8px; color:#555'><b>Date</b></td>
                <td style='padding:3px 8px'>{c.get('date_tested') or 'N/A'}</td></tr>
            <tr><td style='padding:3px 8px; color:#555'><b>Data Points</b></td>
                <td style='padding:3px 8px'>{len(c.get('data_points', []))}</td></tr>
          </table>
        </div>"""

        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"<b>{c['cpt_id']}</b>",
            icon=folium.Icon(color="red", icon="tint", prefix="fa", icon_color="white")
        ).add_to(cpt_group)

    boring_group.add_to(m)
    cpt_group.add_to(m)

    # Measure tool, minimap, layer control
    plugins.MeasureControl(position="topleft", primary_length_unit="meters").add_to(m)
    plugins.MiniMap(toggle_display=True).add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)

    # Fit bounds
    if lats and lons:
        m.fit_bounds([[min(lats) - 0.001, min(lons) - 0.001],
                      [max(lats) + 0.001, max(lons) + 0.001]])

    m.save(output_html)
    return output_html


# ── Fence Diagram ─────────────────────────────────────────────────────────────

def build_fence_diagram(borings: list[dict], output_path: str,
                        title: str = "Fence Diagram",
                        vertical_exaggeration: float = 1.0,
                        show_water_table: bool = True) -> str:
    """
    Generate a 2D cross-section fence diagram from selected borings.
    Borings are spaced by actual horizontal distance if coordinates available,
    else evenly spaced.
    Returns path to saved PNG.
    """
    if not borings:
        return ""

    fig, ax = plt.subplots(figsize=(max(14, len(borings) * 3), 10))
    fig.patch.set_facecolor("#F0F4F8")
    ax.set_facecolor("#E8EFF5")

    # Compute horizontal positions (use real distances if coords available)
    positions = _compute_horizontal_positions(borings)
    max_depth = max((b.get("total_depth") or 0) for b in borings)
    if max_depth == 0:
        max_depth = 30  # default

    # Draw each boring column
    if len(positions) > 1:
        spacings = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
        min_spacing = min(spacings) if spacings else 50
        boring_width = max(2.5, min(min_spacing * 0.2, 8.0))
    else:
        boring_width = 4.0

    for idx, (boring, x_pos) in enumerate(zip(borings, positions)):
        elevation = boring.get("elevation") or 0
        layers = boring.get("layers", [])

        if not layers:
            # Draw empty boring
            ax.add_patch(mpatches.Rectangle(
                (x_pos - boring_width / 2, elevation - (boring.get("total_depth") or 20)),
                boring_width, boring.get("total_depth") or 20,
                facecolor="#DDDDDD", edgecolor="#999", linewidth=0.5, zorder=2
            ))
        else:
            for layer in layers:
                top_elev = elevation - layer["depth_top"]
                bot_elev = elevation - layer["depth_bottom"]
                height = top_elev - bot_elev
                if height <= 0:
                    continue

                uscs = layer.get("uscs_symbol", "")
                color = USCS_COLORS.get(uscs, "#CCC")
                hatch = USCS_HATCH.get(uscs, "")

                rect = mpatches.Rectangle(
                    (x_pos - boring_width / 2, bot_elev),
                    boring_width, height,
                    facecolor=color, edgecolor="#333",
                    linewidth=0.5, hatch=hatch, zorder=2
                )
                ax.add_patch(rect)

                # Layer label
                mid_elev = (top_elev + bot_elev) / 2
                if height > 1.5:
                    ax.text(x_pos, mid_elev, uscs,
                            ha="center", va="center", fontsize=7,
                            fontweight="bold", color="#333", zorder=4)

                # Depth label at layer top
                if layer.get("depth_top", 0) > 0 and height > 1.0:
                    ax.text(x_pos - boring_width * 0.58, top_elev,
                            f"{layer['depth_top']:.0f}'", va="center", ha="right",
                            fontsize=6, color="#777", zorder=4)

                # N-value annotation
                n_val = layer.get("n_value")
                if n_val is not None and height > 1.0:
                    ax.text(x_pos + boring_width * 0.58, mid_elev,
                            f"N={int(n_val)}", va="center", ha="left",
                            fontsize=6, color="#444", zorder=4)

        # Water table
        if show_water_table and boring.get("water_table"):
            wt_elev = elevation - boring["water_table"]
            ax.plot([x_pos - boring_width * 0.6, x_pos + boring_width * 0.6],
                    [wt_elev, wt_elev], color="#2196F3", linewidth=2,
                    linestyle="--", zorder=5)
            ax.text(x_pos + boring_width * 0.65, wt_elev, "GWT",
                    va="center", fontsize=6, color="#2196F3", zorder=5)

        # Ground surface marker
        ax.plot(x_pos, elevation, "v", color="#333", markersize=8, zorder=6)

        # Boring label on top
        ax.text(x_pos, elevation + max_depth * 0.04, boring["boring_id"],
                ha="center", va="bottom", fontsize=9, fontweight="bold",
                color="#1B3A5C", zorder=7,
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                          edgecolor="#1B3A5C", linewidth=1.5))

        # Depth labels
        if boring.get("total_depth"):
            ax.text(x_pos, elevation - boring["total_depth"] - max_depth * 0.02,
                    f"{boring['total_depth']:.0f} ft",
                    ha="center", va="top", fontsize=7, color="#666", zorder=7)

    # Draw interpolation lines between adjacent borings (simplified)
    if len(borings) > 1:
        _draw_interpolation_lines(ax, borings, positions, boring_width)

    # Axes formatting
    ax.set_xlim(min(positions) - boring_width * 2, max(positions) + boring_width * 2)
    elev_vals = [b.get("elevation") or 0 for b in borings]
    y_max = max(elev_vals) + max_depth * 0.15
    y_min = min(elev_vals) - max_depth * 1.1
    ax.set_ylim(y_min, y_max)

    ax.set_xlabel("Horizontal Distance (ft)", fontsize=11, color="#333")
    ax.set_ylabel("Elevation (ft)", fontsize=11, color="#333")
    ax.set_title(f"{title}\n(Vertical Exaggeration: {vertical_exaggeration:.1f}x)",
                 fontsize=13, fontweight="bold", color="#1B3A5C", pad=15)

    ax.grid(True, axis="y", linestyle="--", alpha=0.4, color="#999")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # USCS Legend
    legend_items = []
    uscs_seen = set()
    for b in borings:
        for l in b.get("layers", []):
            sym = l.get("uscs_symbol", "")
            if sym and sym not in uscs_seen:
                uscs_seen.add(sym)
                legend_items.append(
                    mpatches.Patch(facecolor=USCS_COLORS.get(sym, "#CCC"),
                                   edgecolor="#555", label=sym,
                                   hatch=USCS_HATCH.get(sym, ""))
                )

    if legend_items:
        ax.legend(handles=legend_items, title="USCS Classification",
                  loc="lower right", fontsize=8, title_fontsize=9,
                  framealpha=0.9, ncol=2)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    return output_path


def _compute_horizontal_positions(borings: list[dict]) -> list[float]:
    """Compute x positions using lat/lon distances if available, else evenly spaced."""
    positions = []

    lats = [b.get("latitude") for b in borings]
    lons = [b.get("longitude") for b in borings]

    if all(lats) and all(lons):
        # Use geodetic distances from first boring
        ref_lat, ref_lon = lats[0], lons[0]
        x = 0.0
        positions.append(x)
        for i in range(1, len(borings)):
            dist = _haversine_ft(ref_lat, ref_lon, lats[i], lons[i])
            positions.append(dist)
    else:
        # Even spacing at 50 ft
        positions = [i * 50.0 for i in range(len(borings))]

    return positions


def _haversine_ft(lat1, lon1, lat2, lon2) -> float:
    """Distance in feet between two lat/lon points."""
    R = 20902231  # Earth radius in feet
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _draw_interpolation_lines(ax, borings, positions, boring_width):
    """Draw ground surface and layer boundary correlation lines between adjacent borings."""
    for i in range(len(borings) - 1):
        b1, b2 = borings[i], borings[i + 1]
        e1 = b1.get("elevation") or 0
        e2 = b2.get("elevation") or 0
        x1 = positions[i] + boring_width / 2
        x2 = positions[i + 1] - boring_width / 2

        # Ground surface line
        ax.plot([x1, x2], [e1, e2], color="#555", linewidth=1.0,
                linestyle="-", alpha=0.8, zorder=1)

        # Layer boundary correlations
        depths1 = sorted({float(l["depth_bottom"]) for l in b1.get("layers", [])})
        depths2 = sorted({float(l["depth_bottom"]) for l in b2.get("layers", [])})
        for d1 in depths1:
            if not depths2:
                break
            d2 = min(depths2, key=lambda d: abs(d - d1))
            if abs(d2 - d1) <= 8:
                ax.plot([x1, x2], [e1 - d1, e2 - d2],
                        color="#aaa", linewidth=0.5,
                        linestyle="--", alpha=0.5, zorder=1)


# ── Graphical Boring Log ──────────────────────────────────────────────────────

def build_boring_log(boring: dict, output_path: str) -> str:
    """
    Generate a graphical boring log similar to standard geotech log sheets.
    Three panels: graphic log | SPT N-value | soil description.
    Returns path to saved PNG.
    """
    layers = boring.get("layers", [])
    total_depth = boring.get("total_depth")
    if not total_depth and layers:
        total_depth = float(layers[-1].get("depth_bottom", 25))
    if not total_depth:
        total_depth = 25.0
    total_depth = float(total_depth)

    fig_height = max(10, total_depth * 0.45)
    fig, (ax_log, ax_spt, ax_desc) = plt.subplots(
        1, 3,
        figsize=(14, fig_height),
        gridspec_kw={"width_ratios": [1.2, 1.0, 3.5]},
        sharey=True
    )
    fig.patch.set_facecolor("white")

    boring_id = boring.get("boring_id", "")
    fig.suptitle(f"BORING LOG — {boring_id}",
                 fontsize=13, fontweight="bold", color="#1B3A5C", y=0.99)

    for ax in (ax_log, ax_spt, ax_desc):
        ax.set_facecolor("#fefefe")
        ax.set_ylim(total_depth + 0.5, -0.5)
        for spine in ax.spines.values():
            spine.set_linewidth(0.5)

    # Graphic log panel
    ax_log.set_ylabel("Depth (ft)", fontsize=10)
    ax_log.set_yticks(range(0, int(total_depth) + 1, 5))
    ax_log.yaxis.set_tick_params(labelsize=8)
    ax_log.set_xlim(0, 1)
    ax_log.set_xticks([])
    ax_log.set_title("Graphic Log\n& USCS", fontsize=8, pad=4)

    # SPT panel
    ax_spt.set_xlim(0, 65)
    ax_spt.set_title("SPT N\n(blows/ft)", fontsize=8, pad=4)
    ax_spt.set_xlabel("N-value", fontsize=7)
    ax_spt.tick_params(axis="x", labelsize=6)
    ax_spt.set_xticks([0, 10, 20, 30, 40, 50])
    ax_spt.grid(axis="x", linestyle="--", alpha=0.25)
    ax_spt.axvline(50, color="red", linestyle=":", alpha=0.3, linewidth=0.8)
    ax_spt.set_yticks([])

    # Description panel
    ax_desc.set_xlim(0, 1)
    ax_desc.set_xticks([])
    ax_desc.set_yticks([])
    ax_desc.set_title("Soil Description", fontsize=8, pad=4, loc="left")

    for layer in layers:
        try:
            top = float(layer.get("depth_top", 0))
            bot = float(layer.get("depth_bottom", 0))
        except (TypeError, ValueError):
            continue
        if bot <= top:
            continue
        mid = (top + bot) / 2
        height = bot - top
        uscs = (layer.get("uscs_symbol") or "").strip()
        color = USCS_COLORS.get(uscs, "#CCCCCC")
        hatch = USCS_HATCH.get(uscs, "")

        # Soil rectangle
        ax_log.add_patch(mpatches.Rectangle(
            (0.05, top), 0.9, height,
            facecolor=color, edgecolor="#555",
            linewidth=0.5, hatch=hatch, zorder=2
        ))
        if uscs:
            ax_log.text(0.5, mid, uscs, ha="center", va="center",
                        fontsize=7, fontweight="bold", color="#111", zorder=3)

        # Boundary lines across all panels
        for ax in (ax_log, ax_spt, ax_desc):
            ax.axhline(bot, color="#999", linewidth=0.4, zorder=1)

        # SPT N-value bar
        n_val = layer.get("n_value")
        if n_val is not None:
            try:
                n = float(n_val)
                bar_w = min(n, 50)
                ax_spt.barh(mid, bar_w, height=max(height * 0.5, 0.3),
                            color=color, edgecolor="#555", linewidth=0.5, zorder=2)
                ax_spt.text(bar_w + 0.8, mid, str(int(n)),
                            va="center", fontsize=7, color="#222")
            except (TypeError, ValueError):
                pass

        # Individual blow counts (if available)
        blow_counts = layer.get("blow_counts", [])
        if isinstance(blow_counts, str):
            try:
                blow_counts = json.loads(blow_counts)
            except Exception:
                blow_counts = []
        if blow_counts and isinstance(blow_counts, list):
            bc_str = "/".join(str(int(x)) for x in blow_counts if x is not None)
            ax_spt.text(0.5, top + 0.15, bc_str, va="top", ha="left",
                        fontsize=6, color="#666")

        # Soil description (word-wrapped)
        desc = (layer.get("soil_description") or "").strip()
        if desc:
            lines = textwrap.wrap(desc, width=62)[:4]
            ax_desc.text(0.02, top + 0.12, "\n".join(lines),
                         va="top", fontsize=7.5, color="#222", clip_on=True)

    # Water table marker
    wt = boring.get("water_table")
    if wt:
        try:
            wt = float(wt)
            for ax in (ax_log, ax_spt, ax_desc):
                ax.axhline(wt, color="#2196F3", linewidth=1.5,
                           linestyle="--", zorder=5, alpha=0.85)
            ax_desc.text(0.02, wt - 0.1, "GWT", va="bottom",
                         fontsize=7, color="#2196F3", fontweight="bold")
        except (TypeError, ValueError):
            pass

    # Boring end line
    for ax in (ax_log, ax_spt, ax_desc):
        ax.axhline(total_depth, color="#222", linewidth=2, zorder=5)
    ax_log.text(0.5, total_depth + 0.2, "END OF BORING",
                ha="center", va="top", fontsize=6, color="#555")

    # Footer info line
    parts = []
    if boring.get("date_drilled"):
        parts.append(f"Drilled: {boring['date_drilled']}")
    if boring.get("elevation") is not None:
        try:
            parts.append(f"Elev: {float(boring['elevation']):.1f} ft")
        except (TypeError, ValueError):
            pass
    if boring.get("drill_method"):
        parts.append(f"Method: {boring['drill_method']}")
    if boring.get("latitude"):
        try:
            parts.append(f"Lat: {float(boring['latitude']):.5f}  Lon: {float(boring['longitude']):.5f}")
        except (TypeError, ValueError):
            pass
    if parts:
        fig.text(0.5, 0.002, "  |  ".join(parts),
                 ha="center", fontsize=7, color="#666")

    plt.tight_layout(rect=[0, 0.015, 1, 0.985])
    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path
