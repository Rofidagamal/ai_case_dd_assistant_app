"""Turns whatever a doctor uploads into (a) plain text for the AI to read and
(b) a list of images for a vision model. Supported:
  tables : .xlsx .xlsm .xls .csv .tsv        -> text (every sheet, every row)
  docs   : .pdf .docx .txt .md .json         -> text
  slides : .pptx .pptm                       -> text per slide + embedded pictures
  images : .png .jpg .jpeg .webp .bmp .tif   -> sent to a vision model
A case presentation is read slide by slide: the text, the tables, the chart
numbers and the speaker notes become text, and the X-ray / endoscopy / ECG
pictures sitting on the slides are pulled out and sent to the vision model
like any uploaded image (logos and tiny decorations are left out).
Images are shrunk to at most 1600 px on the long side before sending: this
makes the AI answer much faster and loses no clinically useful detail.
"""
import hashlib
import io
import json
from pathlib import Path

import pandas as pd

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
TABLE_EXT = {".xlsx", ".xlsm", ".xls", ".csv", ".tsv"}
DOC_EXT = {".pdf", ".docx", ".txt", ".md", ".json"}
SLIDE_EXT = {".pptx", ".pptm", ".ppt"}
ALL_EXT = sorted(e.lstrip(".") for e in IMAGE_EXT | TABLE_EXT | DOC_EXT | SLIDE_EXT)

# A slide deck can hold dozens of pictures; only keep the ones big enough to
# carry clinical detail, and never flood the vision model with a whole deck.
SLIDE_IMG_MIN_BYTES = 8_000
SLIDE_IMG_MIN_SIDE = 160
SLIDE_IMG_MAX_PER_FILE = 16


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in TABLE_EXT:
        return "table"
    if ext in SLIDE_EXT:
        return "slides"
    if ext in DOC_EXT:
        return "doc"
    return "unknown"


def prepare_image(data: bytes, max_side: int = 1600):
    """-> (mime, jpeg/png bytes). Always returns something the AI APIs accept."""
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im.load()
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side))
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=90)
    return "image/jpeg", out.getvalue()


def read_table(name: str, data: bytes) -> dict:
    """-> {sheet_name: DataFrame}"""
    ext = Path(name).suffix.lower()
    if ext in (".csv", ".tsv"):
        sep = "\t" if ext == ".tsv" else None
        df = pd.read_csv(io.BytesIO(data), sep=sep, engine="python")
        return {"table": df}
    return pd.read_excel(io.BytesIO(data), sheet_name=None)


def table_to_text(name: str, sheets: dict) -> str:
    parts = []
    for sheet, df in sheets.items():
        df = df.dropna(how="all").dropna(axis=1, how="all")
        parts.append(f"[Sheet: {sheet}] ({len(df)} rows)\n" + df.to_csv(index=False))
    return "\n".join(parts)


def read_doc(name: str, data: bytes) -> str:
    ext = Path(name).suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        r = PdfReader(io.BytesIO(data))
        txt = "\n".join((p.extract_text() or "") for p in r.pages).strip()
        if not txt:
            return ("(This PDF has no readable text - it is probably a scan. "
                    "Save its pages as pictures and upload those instead.)")
        return txt
    if ext == ".docx":
        import docx
        d = docx.Document(io.BytesIO(data))
        lines = [p.text for p in d.paragraphs if p.text.strip()]
        for t in d.tables:
            for row in t.rows:
                lines.append(" | ".join(c.text.strip() for c in row.cells))
        return "\n".join(lines)
    if ext == ".json":
        try:
            return json.dumps(json.loads(data.decode("utf-8", "ignore")),
                              ensure_ascii=False, indent=1)
        except Exception:
            pass
    return data.decode("utf-8", "ignore")


def _shape_text(shape) -> list[str]:
    """Text out of one shape: its text frame, its table, or its chart numbers.
    Groups are walked recursively - case decks often nest text inside groups."""
    lines = []
    if hasattr(shape, "shapes"):                 # a group: look inside it
        for sub in shape.shapes:
            lines += _shape_text(sub)
        return lines
    if getattr(shape, "has_table", False):
        for row in shape.table.rows:
            cells = [c.text.strip().replace("\n", " ") for c in row.cells]
            if any(cells):
                lines.append(" | ".join(cells))
        return lines
    if getattr(shape, "has_chart", False):
        try:
            plot = shape.chart.plots[0]
            cats = [str(c) for c in plot.categories]
            if cats:
                lines.append("[chart] " + " | ".join(cats))
            for ser in plot.series:
                vals = ["" if v is None else str(v) for v in ser.values]
                lines.append(f"[chart] {ser.name or 'series'}: " + " | ".join(vals))
        except Exception:
            lines.append("[chart - its numbers could not be read]")
        return lines
    if getattr(shape, "has_text_frame", False):
        for para in shape.text_frame.paragraphs:
            t = para.text.strip()
            if t:
                lines.append(("  " * (getattr(para, "level", 0) or 0)) + t)
    return lines


def _shape_pictures(shape) -> list:
    """Every embedded picture in a shape (walking groups), as python-pptx Images."""
    pics = []
    if hasattr(shape, "shapes"):
        for sub in shape.shapes:
            pics += _shape_pictures(sub)
        return pics
    try:
        pics.append(shape.image)                 # raises on shapes that hold no picture
    except Exception:
        pass
    return pics


def read_slides(name: str, data: bytes) -> dict:
    """A PowerPoint case presentation, read slide by slide.
    -> {"text": str, "images": [(mime, bytes)], "image_names": [str], "notes": [str]}"""
    if Path(name).suffix.lower() == ".ppt":
        raise ValueError("this is the old PowerPoint format, which cannot be read. "
                         "Open it in PowerPoint, then File -> Save As -> .pptx "
                         "and upload that.")
    from pptx import Presentation
    try:
        prs = Presentation(io.BytesIO(data))
    except Exception:
        raise ValueError("this does not open as a PowerPoint file. If it was renamed, "
                         "open it in PowerPoint and use File -> Save As -> .pptx.")

    parts, images, image_names, notes = [], [], [], []
    seen = set()              # a logo sits on every slide: read it once
    big_pictures = 0          # how many were worth sending (before the cap)
    any_text = False
    for i, slide in enumerate(prs.slides, start=1):
        lines = []
        for shape in slide.shapes:
            lines += _shape_text(shape)
        if slide.has_notes_slide:
            nt = (slide.notes_slide.notes_text_frame.text or "").strip()
            if nt:
                lines.append("[speaker notes] " + nt)
        body = "\n".join(lines).strip()
        any_text = any_text or bool(body)
        parts.append(f"--- Slide {i} ---\n" + (body or "(no text on this slide)"))

        for pic in [p for shape in slide.shapes for p in _shape_pictures(shape)]:
            try:
                blob = pic.blob
                digest = hashlib.md5(blob).hexdigest()
                if digest in seen:
                    continue
                seen.add(digest)
                if len(blob) < SLIDE_IMG_MIN_BYTES or min(pic.size) < SLIDE_IMG_MIN_SIDE:
                    continue                     # a logo, bullet icon or divider line
                big_pictures += 1
                if len(images) < SLIDE_IMG_MAX_PER_FILE:
                    images.append(prepare_image(blob))
                    image_names.append(f"{name} - slide {i}")
            except Exception:
                pass

    head = f"[PowerPoint presentation: {len(parts)} slide(s)]"
    if images:
        head += (f" {len(images)} picture(s) taken from these slides are attached "
                 f"as images for the vision model.")
    if big_pictures > len(images):
        notes.append(f"{name}: it has {big_pictures} pictures; only the first "
                     f"{len(images)} were sent to the vision model. Upload any key "
                     f"image separately if it is missing.")
    if not any_text and not images:
        notes.append(f"{name}: no readable text or pictures found. If the slides are "
                     f"screenshots, save them as images and upload those instead.")
    return {"text": head + "\n" + "\n\n".join(parts),
            "images": images, "image_names": image_names, "notes": notes}


def process_uploads(uploaded) -> dict:
    """uploaded: list of Streamlit UploadedFile.
    -> {"text": str, "images": [(mime, bytes)], "image_names": [..],
        "tables": {name: {sheet: df}}, "notes": [str]}"""
    out = {"text": "", "images": [], "image_names": [], "tables": {}, "notes": []}
    chunks = []
    for f in uploaded or []:
        name, data = f.name, f.getvalue()
        k = kind_of(name)
        try:
            if k == "image":
                out["images"].append(prepare_image(data))
                out["image_names"].append(name)
            elif k == "table":
                sheets = read_table(name, data)
                out["tables"][name] = sheets
                chunks.append(f"=== FILE: {name} ===\n{table_to_text(name, sheets)}")
            elif k == "slides":
                deck = read_slides(name, data)
                chunks.append(f"=== FILE: {name} ===\n{deck['text']}")
                out["images"] += deck["images"]
                out["image_names"] += deck["image_names"]
                out["notes"] += deck["notes"]
            elif k == "doc":
                chunks.append(f"=== FILE: {name} ===\n{read_doc(name, data)}")
            else:
                out["notes"].append(f"Skipped {name}: unsupported type.")
        except Exception as e:
            out["notes"].append(f"Could not read {name}: {e}")
    out["text"] = "\n\n".join(chunks)
    return out
