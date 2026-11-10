"""
GeoCalc Pro - PDF Extraction Engine
Extracts boring logs and CPT data from geotechnical reports using
pdfplumber for text/table extraction + Claude API for intelligent parsing.
"""
import os
import re
import json
import logging
from typing import Optional
import pdfplumber

logger = logging.getLogger(__name__)


# ── Text Extraction ───────────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_path: str) -> tuple[str, list[dict]]:
    """
    Extract full text and tables from a PDF.
    Returns (full_text, tables_as_list_of_dicts)
    """
    full_text = []
    tables = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            text = page.extract_text(x_tolerance=2, y_tolerance=2)
            if text:
                full_text.append(f"\n--- PAGE {page_num} ---\n{text}")

            # Extract tables
            for table in page.extract_tables():
                if table and len(table) > 1:
                    headers = [str(h).strip() if h else "" for h in table[0]]
                    for row in table[1:]:
                        if any(cell for cell in row):
                            row_dict = {
                                headers[i] if i < len(headers) else f"col_{i}": str(cell).strip() if cell else ""
                                for i, cell in enumerate(row)
                            }
                            row_dict["_page"] = page_num
                            tables.append(row_dict)

    return "\n".join(full_text), tables


# ── Claude-Powered Extraction ─────────────────────────────────────────────────

def extract_with_claude(pdf_text: str, api_key: str) -> dict:
    """
    Use Claude API to intelligently extract structured data from geotechnical report text.
    Returns structured JSON with borings, CPT soundings, and metadata.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    # Split text into chunks if very long (Claude context limit)
    max_chars = 80000
    text_chunk = pdf_text[:max_chars]
    if len(pdf_text) > max_chars:
        # Also grab end of document (often has summary tables)
        text_chunk += "\n\n... [middle truncated] ...\n\n" + pdf_text[-20000:]

    system_prompt = """You are a geotechnical engineering data extraction expert. 
Extract all boring log and CPT data from the provided geotechnical report text.
Return ONLY valid JSON, no markdown, no explanation.

The JSON structure must be:
{
  "report_metadata": {
    "project_name": "",
    "project_number": "",
    "client": "",
    "lab_firm": "",
    "report_date": "",
    "location": ""
  },

  "borings": [
    {
      "boring_id": "B-1",
      "latitude": null,
      "longitude": null,
      "elevation": null,
      "total_depth": null,
      "water_table": null,
      "date_drilled": "",
      "drill_method": "",
      "notes": "",
      "layers": [
        {
          "depth_top": 0.0,
          "depth_bottom": 5.0,
          "uscs_symbol": "SP",
          "soil_description": "Brown fine to medium SAND",
          "color": "Brown",
          "moisture": "Moist",
          "consistency": "Medium Dense",
          "blow_counts": [4, 5, 6],
          "n_value": 11,
          "liquid_limit": null,
          "plastic_limit": null,
          "plasticity_index": null,
          "fines_content": null,
          "unit_weight": null
        }
      ]
    }
  ],
  "cpt_soundings": [
    {
      "cpt_id": "CPT-1",
      "latitude": null,
      "longitude": null,
      "elevation": null,
      "date_tested": "",
      "equipment": "",
      "data_points": [
        {"depth": 0.5, "qc": 1.2, "fs": 10.0, "u2": 0.0, "rf": 0.83}
      ]
    }
  ]
}

Rules:
- For "location": extract the full street address of the project site (e.g. "3201 North Orange Avenue, Sarasota, FL"). This is critical for auto-locating borings on a map.
- Extract ALL borings found, even if only partial data is available
- For blow counts, list the individual blows per 6-inch interval (up to 4 values)
- N-value is typically the sum of 2nd + 3rd interval blows (standard SPT)
- Use null for missing numeric values, empty string for missing text
- Depths are in feet unless clearly labeled otherwise
- If coordinates are not in the report, leave latitude/longitude as null
- USCS symbols: SP, SW, SM, SC, GP, GW, GM, GC, ML, CL, OL, MH, CH, OH, Pt
"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8000,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": f"Extract all geotechnical data from this report:\n\n{text_chunk}"
                }
            ]
        )

        raw = response.content[0].text.strip()
        # Strip any accidental markdown fences
        raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'^```\s*', '', raw, flags=re.MULTILINE)
        raw = raw.strip()

        return json.loads(raw)

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error from Claude response: {e}")
        return {"error": str(e), "borings": [], "cpt_soundings": [], "report_metadata": {}}
    except Exception as e:
        logger.error(f"Claude API error: {e}")
        return {"error": str(e), "borings": [], "cpt_soundings": [], "report_metadata": {}}


# ── Rule-Based Fallback Extraction ────────────────────────────────────────────

def extract_with_rules(pdf_text: str) -> dict:
    """
    Fallback rule-based extraction when Claude API is not configured.
    Handles common boring log formats.
    """
    result = {
        "report_metadata": _extract_metadata_rules(pdf_text),
        "borings": _extract_borings_rules(pdf_text),
        "cpt_soundings": _extract_cpt_rules(pdf_text),
    }
    return result


def _extract_metadata_rules(text: str) -> dict:
    meta = {
        "project_name": "", "project_number": "", "client": "",
        "lab_firm": "", "report_date": "", "location": ""
    }

    patterns = {
        "project_name": [r"project\s*(?:name|title)[:\s]+([^\n]+)", r"(?:re:|subject:)\s*([^\n]+)"],
        "project_number": [r"project\s*(?:no|number|#)[:\s.]+([A-Z0-9\-]+)"],
        "client": [r"(?:prepared\s+for|client)[:\s]+([^\n]+)"],
        "lab_firm": [r"(?:prepared\s+by|firm)[:\s]+([^\n]+)"],
        "report_date": [r"(?:date|dated)[:\s]+(\w+\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4})"],
        "location": [
            r"(\d+\s+\w[\w\s]+(?:avenue|ave|street|st|road|rd|blvd|boulevard|drive|dr|lane|ln|way|court|ct)[,\s]+\w[\w\s]+,\s*[A-Z]{2})",
            r"(?:site\s+address|project\s+(?:site|location|address))[:\s]+([^\n]+)",
            r"(?:located\s+at|address)[:\s]+([^\n]{10,80})",
        ],
    }

    for field, pats in patterns.items():
        for pat in pats:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                meta[field] = m.group(1).strip()[:200]
                break

    return meta


def _extract_borings_rules(text: str) -> list[dict]:
    """Find boring headers and extract basic info."""
    borings = []

    # Match boring headers like "BORING B-1", "TEST BORING TB-2", "BH-3"
    boring_pattern = re.compile(
        r'(?:TEST\s+)?(?:BORING|BOREHOLE|BH)\s*[-#]?\s*([A-Z]?\d+[A-Z]?)',
        re.IGNORECASE
    )

    # Find all boring IDs and their positions
    matches = list(boring_pattern.finditer(text))
    boring_ids_seen = set()

    for i, match in enumerate(matches):
        bid = f"B-{match.group(1)}" if not match.group(0).upper().startswith("BH") else f"BH-{match.group(1)}"
        bid = bid.upper()

        if bid in boring_ids_seen:
            continue
        boring_ids_seen.add(bid)

        # Get text window for this boring
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else min(start + 3000, len(text))
        boring_text = text[start:end]

        boring = {
            "boring_id": bid,
            "latitude": None, "longitude": None,
            "elevation": _find_float(boring_text, [r"elev(?:ation)?[:\s.]+([+-]?\d+\.?\d*)"]),
            "total_depth": _find_float(boring_text, [r"(?:total\s+)?depth[:\s.]+(\d+\.?\d*)"]),
            "water_table": _find_float(boring_text, [r"(?:water|gwt|wt)[:\s.]+(\d+\.?\d*)"]),
            "date_drilled": _find_str(boring_text, [r"drilled[:\s]+([^\n]{5,30})"]),
            "drill_method": _find_str(boring_text, [r"method[:\s]+([^\n]{3,30})"]),
            "notes": "",
            "layers": _extract_layers_from_text(boring_text)
        }
        borings.append(boring)

    return borings


def _extract_layers_from_text(text: str) -> list[dict]:
    """Extract soil layer table from boring log text."""
    layers = []

    # Pattern: depth range + soil description + N-value
    # e.g.  0-5  Brown fine SAND (SP)  4/5/6  11
    layer_pat = re.compile(
        r'(\d+\.?\d*)\s*[-–to]+\s*(\d+\.?\d*)\s+'
        r'([A-Z][^\n]{5,80}?)\s+'
        r'(?:(\d+)[/\s](\d+)[/\s](\d+))?',
        re.IGNORECASE
    )

    uscs_pat = re.compile(r'\b(SP|SW|SM|SC|GP|GW|GM|GC|ML|CL|OL|MH|CH|OH|Pt)\b')

    for m in layer_pat.finditer(text):
        try:
            d_top = float(m.group(1))
            d_bot = float(m.group(2))
            desc = m.group(3).strip()

            blows = []
            n_val = None
            if m.group(4) and m.group(5) and m.group(6):
                blows = [int(m.group(4)), int(m.group(5)), int(m.group(6))]
                n_val = blows[1] + blows[2]  # Standard SPT N

            uscs_match = uscs_pat.search(desc)
            uscs = uscs_match.group(1) if uscs_match else ""

            layers.append({
                "depth_top": d_top,
                "depth_bottom": d_bot,
                "uscs_symbol": uscs,
                "soil_description": desc[:200],
                "color": "",
                "moisture": "",
                "consistency": "",
                "blow_counts": blows,
                "n_value": n_val,
                "liquid_limit": None,
                "plastic_limit": None,
                "plasticity_index": None,
                "fines_content": None,
                "unit_weight": None,
            })
        except (ValueError, IndexError):
            continue

    return layers


def _extract_cpt_rules(text: str) -> list[dict]:
    """Extract CPT sounding headers."""
    soundings = []
    cpt_pat = re.compile(r'CPT\s*[-#]?\s*(\d+)', re.IGNORECASE)
    seen = set()

    for m in cpt_pat.finditer(text):
        cid = f"CPT-{m.group(1)}"
        if cid in seen:
            continue
        seen.add(cid)
        soundings.append({
            "cpt_id": cid,
            "latitude": None, "longitude": None,
            "elevation": None, "date_tested": "",
            "equipment": "", "data_points": []
        })

    return soundings


def _find_float(text: str, patterns: list[str]) -> Optional[float]:
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
    return None


def _find_str(text: str, patterns: list[str]) -> str:
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()[:100]
    return ""


# ── Claude Vision Extraction (scanned / graphical boring logs) ────────────────

def extract_with_claude_vision(pdf_path: str, api_key: str,
                                progress_callback=None) -> dict:
    """
    Render each PDF page as an image and use Claude vision to extract boring log data.
    Handles scanned PDFs and CAD-drawn boring log sheets that contain no parseable text.
    """
    import anthropic
    import fitz  # PyMuPDF
    import base64

    def cb(msg, pct):
        if progress_callback:
            progress_callback(msg, pct)

    client = anthropic.Anthropic(api_key=api_key)

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        logger.error(f"PyMuPDF could not open PDF: {e}")
        return {"report_metadata": {}, "borings": [], "cpt_soundings": []}

    all_borings: list = []
    merged_meta: dict = {}
    seen_ids: set = set()
    total = len(doc)

    vision_prompt = (
        "You are a geotechnical engineering expert reading a boring log sheet.\n"
        "Extract ALL boring logs visible on this page.\n"
        "Return ONLY valid JSON — no markdown, no explanation.\n\n"
        "{\n"
        '  "page_type": "boring_log OR location_plan OR site_map OR other",\n'
        '  "metadata": {\n'
        '    "project_name": "", "project_number": "", "client": "",\n'
        '    "lab_firm": "", "report_date": "", "location": ""\n'
        "  },\n"
        '  "borings": [\n'
        "    {\n"
        '      "boring_id": "B-1",\n'
        '      "total_depth": 25.0,\n'
        '      "water_table": 5.0,\n'
        '      "date_drilled": "12/12/2020",\n'
        '      "drill_method": "",\n'
        '      "layers": [\n'
        "        {\n"
        '          "depth_top": 0.0, "depth_bottom": 5.0,\n'
        '          "uscs_symbol": "SP",\n'
        '          "soil_description": "Light brown fine sand with silt and shell",\n'
        '          "blow_counts": [2, 4, 5],\n'
        '          "n_value": 9,\n'
        '          "color": "", "consistency": ""\n'
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- Extract EVERY boring column on the page (B-1, B-2 ... HA-1 etc.)\n"
        "- N-value = sum of 2nd + 3rd blow count intervals (standard SPT)\n"
        "- Depths in feet; null for missing numbers; empty string for missing text\n"
        "- location = full street address if visible\n"
        "- If no boring logs on this page: page_type='other', borings=[]"
    )

    for page_num in range(total):
        cb(f"AI reading page {page_num + 1}/{total}...",
           35 + int(50 * page_num / total))

        page = doc[page_num]
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        if pix.width > 1600:
            s = 1600 / pix.width
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0 * s, 2.0 * s))

        try:
            img_bytes = pix.tobytes("jpg")
            media_type = "image/jpeg"
        except Exception:
            img_bytes = pix.tobytes("png")
            media_type = "image/png"

        img_b64 = base64.standard_b64encode(img_bytes).decode()

        try:
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=6000,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image",
                         "source": {"type": "base64",
                                    "media_type": media_type,
                                    "data": img_b64}},
                        {"type": "text", "text": vision_prompt}
                    ]
                }]
            )
            raw = resp.content[0].text.strip()
            raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
            raw = re.sub(r'^```\s*', '', raw, flags=re.MULTILINE)
            page_data = json.loads(raw.strip())
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error page {page_num + 1}: {e}")
            continue
        except Exception as e:
            logger.error(f"Vision API error page {page_num + 1}: {e}")
            continue

        for k, v in page_data.get("metadata", {}).items():
            if v and not merged_meta.get(k):
                merged_meta[k] = v

        for b in page_data.get("borings", []):
            bid = b.get("boring_id", "")
            if bid and bid not in seen_ids:
                all_borings.append(b)
                seen_ids.add(bid)

    doc.close()
    cb(f"Vision complete: {len(all_borings)} borings extracted", 88)
    return {"report_metadata": merged_meta, "borings": all_borings, "cpt_soundings": []}


# ── Geocoding ─────────────────────────────────────────────────────────────────

def geocode_address(address: str) -> Optional[tuple]:
    """
    Geocode a free-text address using OpenStreetMap Nominatim.
    Returns (lat, lon) or None on failure.
    """
    try:
        import requests
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1},
            headers={"User-Agent": "GeoCalcPro/1.0"},
            timeout=10
        )
        data = resp.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        logger.warning(f"Geocoding failed for '{address}': {e}")
    return None


def _auto_assign_coords(borings: list, center_lat: float, center_lon: float):
    """
    Distribute borings without coordinates in a grid around a center point.
    Each step is ~50 ft (0.000138 degrees).
    """
    step = 0.000138
    cols = max(1, round(len(borings) ** 0.5))
    for idx, b in enumerate(borings):
        if not b.get("latitude"):
            row = idx // cols
            col = idx % cols
            b["latitude"] = center_lat + row * step
            b["longitude"] = center_lon + col * step


# ── Main Entry Point ──────────────────────────────────────────────────────────

def process_report(pdf_path: str, api_key: Optional[str] = None,
                   progress_callback=None) -> dict:
    """
    Full pipeline: PDF → extracted structured data.
    Uses Claude API if api_key provided, else falls back to rule-based.
    progress_callback(message: str, percent: int) → optional UI updates
    """

    def progress(msg, pct):
        if progress_callback:
            progress_callback(msg, pct)
        logger.info(f"[{pct}%] {msg}")

    progress("Reading PDF...", 10)
    full_text, tables = extract_text_from_pdf(pdf_path)

    if not full_text.strip():
        return {"error": "No text could be extracted from PDF (may be scanned image)",
                "borings": [], "cpt_soundings": [], "report_metadata": {}}

    if api_key:
        progress("Extracting data with AI (Claude)...", 30)
        result = extract_with_claude(full_text, api_key)
        if "error" in result and result.get("borings") == []:
            progress("AI text extraction failed, falling back to rule-based parser...", 50)
            result = extract_with_rules(full_text)
    else:
        progress("Extracting data with rule-based parser...", 30)
        result = extract_with_rules(full_text)

    # If still no borings found (likely scanned/graphical PDF), use Claude vision
    if api_key and len(result.get("borings", [])) == 0:
        progress("No borings in text layer — switching to AI vision extraction...", 50)
        vision = extract_with_claude_vision(pdf_path, api_key, progress_callback)
        if vision.get("borings"):
            result["borings"] = vision["borings"]
            result["cpt_soundings"] = vision.get("cpt_soundings", [])
            for k, v in vision.get("report_metadata", {}).items():
                if v and not result.get("report_metadata", {}).get(k):
                    result["report_metadata"][k] = v

    result["raw_text"] = full_text
    result["source_file"] = os.path.basename(pdf_path)

    # Geocode project address and auto-assign coords to borings that have none
    meta = result.get("report_metadata", {})
    address = (meta.get("location") or meta.get("project_name") or "").strip()
    if address:
        progress(f"Geocoding: {address[:60]}...", 90)
        coords = geocode_address(address)
        if coords:
            result["_geocoded_address"] = address
            result["_geocoded_lat"] = coords[0]
            result["_geocoded_lon"] = coords[1]
            missing = [b for b in result.get("borings", []) if not b.get("latitude")]
            if missing:
                _auto_assign_coords(missing, coords[0], coords[1])
            progress(f"Located at {coords[0]:.4f}, {coords[1]:.4f}", 95)

    boring_count = len(result.get("borings", []))
    cpt_count = len(result.get("cpt_soundings", []))
    progress(f"Complete: {boring_count} borings, {cpt_count} CPT soundings", 100)

    return result
