# CPT Digitizer

A desktop tool (Python + PyQt6) that digitizes **CPT graphs** from geotechnical reports and exports the data to **Excel** or **CSV**.

It reads a screenshot or image of a CPT plot, lets you calibrate the axes, traces the curve by colour, and samples it at a depth interval. It does not do any engineering calculations.

---

## What it does

- Loads a CPT graph from an image file or a screen capture
- Digitizes three channels on separate tabs: **qc**, **fs** and **u2**
- Calibrates each axis from two known points (X = value, Y = depth)
- Traces the curve by picking its colour, with an adjustable tolerance and a colour-mask preview
- Samples the curve at a depth interval (default **0.1 ft**, shared across all three channels), or at every image pixel row
- Shows all channels together on a Summary tab
- Saves each digitized CPT, with its source image and digitizing setup, into a named project
- Reloads a saved CPT and restores its image, calibration and points
- Exports to CSV, to Excel (with native charts), or exports a whole project to one Excel file

It does not read PDFs, make maps, or perform calculations.

---

## Requirements

- Python 3.10 or newer (developed with Python 3.14)
- Windows, macOS or Linux

Install the packages used by the digitizer:

```bash
pip install PyQt6 pillow numpy pandas openpyxl
```

Note: `requirements.txt` lists packages for the older GeoCalc Pro modules too. You only need the five packages above to run the digitizer.

---

## Running it

From the project folder:

```bash
python cpt_digitizer.py
```

The window opens with a toolbar at the top and the three channel tabs (qc, fs, u2) plus the Summary tab.

---

## Typical workflow

1. **Create a project.** Click **New Project** and enter a name. Projects keep your saved CPTs together.
2. **Load the graph.** On a channel tab, click **Load Image File…** or **Capture Screen Region**. Use the zoom buttons and **Pan** to find the plot.
3. **Calibrate X.** Click **Set X-Point 1 →**, then click a known x-value on the image and enter its value. Repeat for **Set X-Point 2 →**.
4. **Calibrate Y (depth).** Do the same with **Set Y-Point 1 →** and **Set Y-Point 2 →**, using two known depths.
5. **Pick the curve colour.** Click **Pick Curve Colour**, then click on the curve. Adjust the tolerance slider if needed, and use **Show Colour Mask Preview** to check the trace.
6. **Set the depth interval.** The default is 0.1 ft. Changing it on one channel changes it on all three. Tick **Every pixel row** to sample at the finest resolution the image allows (never finer than 0.1 ft).
7. **Extract.** Click **Extract Data**. Use **Preview This Channel** to check the result.
8. **Repeat for qc, fs and u2.** The Summary tab shows all channels together.
9. **Save.** Type a CPT name and click **Save CPT** (Ctrl+S). The tabs clear so you can start the next CPT.
10. **Export.** Use **Export CSV…**, **Export Excel…** (one sheet with all channels, one sheet per channel, and charts) or **Export Project…** (every saved CPT in the project, one sheet per CPT).

To reload a saved CPT, choose it in the **Load CPT** dropdown. Its image, calibration and points come back. **Delete CPT** and **Delete Project** remove saved data.

### Keyboard shortcuts

| Shortcut | Action |
|---|---|
| Ctrl+S | Save CPT |
| Ctrl+Shift+S | Export CSV |
| Ctrl+E | Export Excel |
| Ctrl+Shift+E | Export Project (all saved CPTs) |
| Ctrl+P | Preview All |
| F1 | Help |

---

## Units

Units are chosen per channel. Defaults are **ft** for depth, **tsf** for qc and fs, and **psi** for u2. Options include MPa, ksf, tsf, psi and kPa for qc; kPa, ksf, tsf, psi and psf for fs; and kPa, psi and psf for u2. Depth can be set to m or ft.

---

## Where your data is saved

Projects are stored in a `.dam_projects` folder inside the project folder, in `projects.json`. This folder holds your saved CPT data, so it is not included in the repository. A new copy of the program starts with no projects.

---

## Troubleshooting

**"Points missing at some depths"** — Increase the tolerance, or pick the curve colour from a cleaner part of the trace (avoid anti-aliased edges).

**Wrong values or an offset** — Zoom in and click exactly on the axis tick marks when you set the calibration points.

**Grid lines are traced along with the curve** — Lower the tolerance until the grid disappears from the mask preview, or pick the colour from a section without grid lines.

**Coordinates are wrong on a high-DPI screen** — Take the screenshot yourself (for example with the Snipping Tool) and use **Load Image File…**.

**Excel charts don't appear** — Restart the program and export again. Older copies of the program did not write charts.

---

## Other files in this repository

The repository also contains the older GeoCalc Pro modules (`main.py`, `geocalc_app/`, `map_view*.py`, `ags_handler.py`, `borehole_map.py`, `priebe_settlement_calc.py`, and related files). They are not part of the CPT digitizer and are not described here.
