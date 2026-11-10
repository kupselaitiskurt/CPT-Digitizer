# GeoCalc Pro 🏗️

**Professional Geotechnical Engineering Analysis Platform**

A desktop Python application for geotechnical data management, visualization, and engineering calculations. Built with PyQt6 for a professional, expandable engineering workflow.

---

## Module 1: Boring Log Import & Site Mapping

### Features
- 📄 **PDF Report Import** — Upload geotechnical investigation reports
- 🤖 **AI Extraction** — Claude AI intelligently extracts boring logs, soil layers, N-values, lab data
- 📏 **Rule-Based Fallback** — Works without API key for standard boring log formats
- 🗺️ **Interactive Site Map** — Leaflet/Folium map with boring & CPT locations, satellite imagery
- 📊 **Fence Diagrams** — 2D cross-section views with USCS soil classification colors
- 💾 **Persistent Database** — SQLite stores all project data locally; works offline
- 🌐 **Multi-Project** — Manage multiple sites; borings from previous projects appear on map

---

## Installation

### Prerequisites
- Python 3.10+
- Windows 10/11, macOS 12+, or Linux

### Install Dependencies

```bash
# Clone or unzip the project
cd geocalc_app

# Create virtual environment (recommended)
python -m venv venv

# Activate:
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install all dependencies
pip install -r requirements.txt
```

### Run the App

```bash
python main.py
```

---

## Configuration

### Claude AI API Key (Optional but Recommended)

The app uses Claude AI for intelligent PDF extraction. Without it, rule-based parsing is used.

1. Get an API key at [console.anthropic.com](https://console.anthropic.com)
2. In the app: **Settings → AI & API → API Key**
3. Or enter it in the **Import Report** panel

The key is stored securely in your system's Qt settings (not in plain text files).

---

## Workflow

```
New Project → Import Report PDF → Review Extracted Data → Save to DB
     ↓
  Site Map (view all borings/CPTs on satellite imagery)
     ↓
  Fence Diagram (select borings → 2D cross-section)
     ↓
  [Future] Engineering Calculations
```

### Step-by-Step

1. **Create a Project** — Projects tab → New Project → enter name, client, location
2. **Import a Report** — Import Report tab → Browse PDF → Extract → review tree → Save
3. **View Map** — Site Map tab shows all borings with clickable popups (soil profile, N-values)
4. **Fence Diagram** — Select 2+ borings → Generate → cross-section with USCS colors
5. **Export** — Export map as HTML or fence diagram as PNG

---

## Architecture

```
geocalc_app/
├── main.py                     # Entry point
├── requirements.txt
├── setup.py
├── geocalc.spec               # PyInstaller build config
└── geocalc_app/
    ├── core/
    │   ├── database.py        # SQLite schema, CRUD operations
    │   ├── extractor.py       # PDF → structured data (Claude + rules)
    │   └── mapping.py         # Folium maps, matplotlib fence diagrams
    ├── ui/
    │   ├── main_window.py     # Main window, navigation
    │   ├── project_panel.py   # Project management
    │   ├── report_panel.py    # PDF import + data review
    │   ├── map_panel.py       # Interactive Leaflet map
    │   ├── fence_panel.py     # Fence diagram generator
    │   └── settings_dialog.py # Settings
    └── assets/
        └── style.qss          # Professional dark theme
```

### Database Schema (SQLite)

| Table | Purpose |
|---|---|
| `projects` | Project metadata |
| `reports` | Uploaded PDF files |
| `borings` | Boring locations + metadata |
| `soil_layers` | SPT data, USCS, lab values per boring |
| `cpt_soundings` | CPT locations |
| `cpt_data` | qc, fs, u2 readings per depth |
| `fence_diagrams` | Saved cross-section configurations |

---

## Building an Executable (.exe / .app)

```bash
pip install pyinstaller
pyinstaller geocalc.spec
```

The built app will be in `dist/GeoCalcPro/`. Distribute the whole folder or create an installer with NSIS (Windows) or create-dmg (macOS).

---

## Planned Modules

| Module | Status |
|---|---|
| Boring Log Import & Site Mapping | ✅ **Complete** |
| Foundation Drawing Overlay | 🔲 Next |
| Deep Foundation Calculations (driven/drilled) | 🔲 Planned |
| Ground Improvement (stone columns, wick drains) | 🔲 Planned |
| Earth Retention (sheet pile, soldier pile) | 🔲 Planned |
| Settlement Analysis | 🔲 Planned |
| Steel Design (AISC) | 🔲 Planned |
| Concrete Design (ACI) | 🔲 Planned |
| Arduino Instrumentation / Real-Time Monitoring | 🔲 Planned |

---

## Expanding the App

### Adding a New Calculation Module

1. Create `geocalc_app/ui/my_calc_panel.py` (extend `QWidget`)
2. Add to `main_window.py`:
   ```python
   from geocalc_app.ui.my_calc_panel import MyCalcPanel
   self.my_panel = MyCalcPanel()
   self.stack.addWidget(self.my_panel)
   ```
3. Add a nav button in `_build_sidebar()`

### Adding a New Table to the Database

Add `CREATE TABLE IF NOT EXISTS` in `database.py → initialize_database()`.
The table is auto-created on next launch.

### Arduino Integration (future)

The `InstrumentationPanel` placeholder is already in the nav. For Arduino:
- Use `pyserial` for COM port communication
- Add a `core/arduino_reader.py` with a QThread worker
- Stream live readings into a new `sensor_readings` table
- Plot with matplotlib or pyqtgraph for real-time charting

---

## Troubleshooting

**"No text extracted from PDF"** — The PDF may be a scanned image. Use Adobe Acrobat or similar to OCR the PDF first, then re-import.

**"API key invalid"** — Check the key starts with `sk-ant-`. Keys from console.anthropic.com.

**Map not loading** — The map requires internet for satellite tile loading. Street map tiles work offline via cached tiles. Check your firewall.

**Qt WebEngine not found** — Run: `pip install PyQt6-WebEngine`

---

## License

GeoCalc Pro — Proprietary. All rights reserved.
