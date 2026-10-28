"""
Conversor de archivos sencillo (estilo Clémentine) en Python + PySide6.

Abres la app, arrastras un archivo (o lo eliges con un clic) y te muestra
las opciones disponibles según su tipo: convertir, comprimir, redimensionar,
recortar, quitar metadatos, extraer audio...

Dependencias:
    pip install PySide6 Pillow pillow-heif pymupdf python-docx
Además, para vídeo y audio hace falta FFmpeg instalado y en el PATH.
(Opcional: LibreOffice para pasar DOCX a PDF.)

Uso:
    python conversor.py
"""
import io
import os
import re
import shutil
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from statistics import median

from PIL import Image, ImageOps
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QGridLayout, QInputDialog, QLabel,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass
try:
    import pymupdf as fitz  # PyMuPDF (nombre moderno)
except ImportError:
    try:
        import fitz  # PyMuPDF (nombre antiguo)
    except ImportError:
        fitz = None
try:
    import docx
except ImportError:
    docx = None

IMG = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".tiff", ".tif", ".avif", ".ico", ".bmp"}
VID = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".gif"}
AUD = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aiff", ".wma"}


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def out_path(src: Path, suffix: str, ext: str) -> Path:
    """Ruta de salida junto al original, sin pisar archivos existentes."""
    p = src.with_name(f"{src.stem}{suffix}{ext}")
    n = 1
    while p.exists():
        p = src.with_name(f"{src.stem}{suffix}_{n}{ext}")
        n += 1
    return p


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def open_image(src: Path) -> Image.Image:
    im = Image.open(src)
    im.load()
    return ImageOps.exif_transpose(im)  # respeta la rotación del móvil


def flatten(im: Image.Image) -> Image.Image:
    """Quita la transparencia sobre fondo blanco (para JPG/PDF)."""
    if im.mode in ("RGBA", "LA", "P"):
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, "white")
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    return im.convert("RGB") if im.mode != "RGB" else im


def run_ffmpeg(src: Path, out: Path, *opts: str) -> Path:
    exe = shutil.which("ffmpeg")
    if not exe:      # ffmpeg.exe junto a la app (versión empaquetada)
        for cand in (Path(sys.executable).parent / "ffmpeg.exe", Path(sys.executable).parent / "ffmpeg"):
            if cand.exists():
                exe = str(cand)
                break
    if not exe:
        raise RuntimeError("No encuentro FFmpeg. Instálalo y añádelo al PATH.")
    cmd = [exe, "-y", "-i", str(src), *opts, str(out)]
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=flags)
    if r.returncode != 0:
        raise RuntimeError("FFmpeg falló:\n" + r.stderr[-400:])
    return out


# --------------------------------------------------------------------------
# Acciones sobre imágenes
# --------------------------------------------------------------------------
IMG_FORMATS = {
    "JPG": ("JPEG", ".jpg"), "PNG": ("PNG", ".png"), "WEBP": ("WEBP", ".webp"),
    "PDF": ("PDF", ".pdf"), "ICO": ("ICO", ".ico"), "TIFF": ("TIFF", ".tiff"),
}


def img_to(fmt: str):
    pil_fmt, ext = IMG_FORMATS[fmt]

    def run(src, _):
        im = open_image(src)
        out = out_path(src, "", ext)
        if pil_fmt in ("JPEG", "PDF"):
            im = flatten(im)
        if pil_fmt == "ICO":
            im.thumbnail((256, 256))
        im.save(out, pil_fmt)
        return out
    return run


def img_compress(strong: bool):
    def run(src, _):
        im = open_image(src)
        ext = src.suffix.lower()
        if ext == ".png":
            out = out_path(src, "_comprimido", ".png")
            if strong:
                im = im.convert("RGBA").quantize(256, method=Image.Quantize.FASTOCTREE)
            im.save(out, "PNG", optimize=True)
        elif ext == ".webp":
            out = out_path(src, "_comprimido", ".webp")
            im.save(out, "WEBP", quality=50 if strong else 75)
        else:
            out = out_path(src, "_comprimido", ".jpg")
            flatten(im).save(out, "JPEG", quality=50 if strong else 75, optimize=True)
        return out
    return run


def img_resize(src, width):
    im = open_image(src)
    height = max(1, round(im.height * width / im.width))
    out = out_path(src, f"_{width}x{height}", src.suffix.lower() or ".png")
    im.resize((width, height), Image.LANCZOS).save(out)
    return out


def img_crop(src, value):
    wr, hr = map(int, value.split()[0].split(":"))
    im = open_image(src)
    w, h = im.size
    target = wr / hr
    if w / h > target:
        nw = int(h * target)
        box = ((w - nw) // 2, 0, (w - nw) // 2 + nw, h)
    else:
        nh = int(w / target)
        box = (0, (h - nh) // 2, w, (h - nh) // 2 + nh)
    out = out_path(src, "_recortado", src.suffix.lower() or ".png")
    im.crop(box).save(out)
    return out


def img_strip_metadata(src, _):
    # Pillow no copia el EXIF salvo que se lo pidamos, así que basta con guardar.
    im = open_image(src)
    out = out_path(src, "_sin_metadatos", src.suffix.lower() or ".png")
    im.save(out)
    return out


# --------------------------------------------------------------------------
# PDF, DOCX y TXT
# --------------------------------------------------------------------------
def pdf_to_images(fmt: str):
    def run(src, _):
        if fitz is None:
            raise RuntimeError("Falta PyMuPDF: pip install pymupdf")
        doc = fitz.open(src)
        folder = out_path(src, "_imagenes", "")
        folder.mkdir()
        zoom = 150 / 72  # 150 ppp
        for i, page in enumerate(doc, 1):
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            im.save(folder / f"{src.stem}_{i:03d}.{fmt.lower()}")
        return folder
    return run


def pdf_to_txt(src, _):
    if fitz is None:
        raise RuntimeError("Falta PyMuPDF: pip install pymupdf")
    doc = fitz.open(src)
    out = out_path(src, "", ".txt")
    out.write_text("\n\n".join(p.get_text() for p in doc), encoding="utf-8")
    return out


def pdf_compress(src, _):
    if fitz is None:
        raise RuntimeError("Falta PyMuPDF: pip install pymupdf")
    doc = fitz.open(src)
    out = out_path(src, "_comprimido", ".pdf")
    doc.save(out, garbage=4, deflate=True, clean=True)
    return out


_XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def clean_xml(text: str) -> str:
    """Quita los caracteres que Word (XML) no admite: NULL, controles, sustitutos."""
    return _XML_ILLEGAL.sub("", text)


# ---- PDF -> DOCX (texto editable + fórmulas/gráficos como imagen) ----
_MATH_CHARS = set("∆∑∏√∫±≈≤≥≠∝∞×−→⇒∂∇µμπθλφωΩΦσρτηεαβγδΔΣΠΛΨψχξζκνυ")
_OPERATORS = set("=≈≤≥≠∝")
_BAND_GAP = 4.0     # pt: separación vertical mínima entre dos bloques distintos
_RES = 200          # ppp con los que se dibujan las zonas de imagen


def _is_rule(o, pw, ph):
    """Filetes largos (bordes de tabla, línea de cabecera) y fondos enormes: se ignoran."""
    w, h = o["x1"] - o["x0"], o["bottom"] - o["top"]
    if h < 3 and w > 0.5 * pw:
        return True
    if w < 3 and h > 100:
        return True
    return w * h > 0.8 * pw * ph


def _page_items(page):
    pw, ph = float(page.width), float(page.height)
    items = []
    for c in page.chars:
        if c["text"].strip():
            items.append(("c", c["x0"], c["top"], c["x1"], c["bottom"], c))
    for kind in ("lines", "rects", "curves", "images"):
        for o in getattr(page, kind):
            if not _is_rule(o, pw, ph):
                items.append(("o", o["x0"], o["top"], o["x1"], o["bottom"], o))
    return items


def _bands(items):
    items = sorted(items, key=lambda t: t[2])
    bands = []
    for it in items:
        if bands and it[2] - bands[-1]["bottom"] <= _BAND_GAP:
            b = bands[-1]
            b["items"].append(it)
            b["bottom"] = max(b["bottom"], it[4])
            b["x0"] = min(b["x0"], it[1])
            b["x1"] = max(b["x1"], it[3])
        else:
            bands.append({"items": [it], "top": it[2], "bottom": it[4], "x0": it[1], "x1": it[3]})
    return bands


def _is_image_band(b):
    chars = [it[5] for it in b["items"] if it[0] == "c"]
    if any(it[0] == "o" for it in b["items"]):
        return True                      # líneas, fracciones, dibujos, logos...
    if not chars:
        return False
    sizes = [c["size"] for c in chars]
    med = median(sizes)
    text = "".join(c["text"] for c in chars)
    if any(ch in _MATH_CHARS or ch in _OPERATORS for ch in text):
        return True
    if ". . . ." in text.replace("  ", " ") or "...." in text:
        return True                      # puntos guía de un índice
    if any(("symbol" in c["fontname"].lower() or "math" in c["fontname"].lower()) for c in chars):
        return True
    if med >= 6.5 and any(s < 0.8 * med for s in sizes):
        return True                      # subíndices / exponentes
    # texto en columnas separadas (filas de tabla): se conserva la alineación
    for line in _lines(chars):
        xs = sorted((c["x0"], c["x1"]) for c in line)
        for (a0, a1), (b0, b1) in zip(xs, xs[1:]):
            if b0 - a1 > 3.5 * med:
                return True
    return False


def _lines(chars):
    out = []
    for c in sorted(chars, key=lambda c: (c["top"] + c["bottom"]) / 2):
        cy = (c["top"] + c["bottom"]) / 2
        if out and abs(cy - out[-1]["cy"]) <= 0.5 * max(c["size"], out[-1]["size"]):
            out[-1]["chars"].append(c)
        else:
            out.append({"cy": cy, "size": c["size"], "chars": [c]})
    return [sorted(l["chars"], key=lambda c: c["x0"]) for l in out]


def _style(c):
    n = c["fontname"].lower()
    bold = "bold" in n or "semibold" in n or "black" in n
    italic = "italic" in n or n.endswith("-it") or "oblique" in n
    fam = "Arial" if "arial" in n else ("Calibri" if "myriad" in n else None)
    return (bold, italic, round(c["size"] * 2) / 2, fam)


def _paragraph_runs(chars):
    """Convierte los caracteres de una banda de texto en runs (texto, estilo)."""
    runs = []
    for line in _lines(chars):
        if runs:
            runs.append([" ", runs[-1][1]])
        prev = None
        for c in line:
            if prev is not None and c["text"] != " " and prev["text"] != " " \
                    and c["x0"] - prev["x1"] > 0.22 * c["size"]:
                runs.append([" ", _style(c)])
            runs.append([c["text"], _style(c)])
            prev = c
    merged = []
    for t, s in runs:
        if merged and merged[-1][1] == s:
            merged[-1][0] += t
        else:
            merged.append([t, s])
    return merged


def _tiny_mark(p):
    """Marca de párrafo de 1 pt (si no, Word suma la altura de una línea de 11 pt)."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    pPr = p._p.get_or_add_pPr()
    rPr = OxmlElement("w:rPr")
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), "2")
    rPr.append(sz)
    pPr.append(rPr)


def _pdf_to_docx_formulas(src: Path, out: Path):
    import pdfplumber
    from docx.shared import Pt
    pdf = pdfplumber.open(str(src))
    pages = []
    for page in pdf.pages:
        try:
            clean = page.dedupe_chars(tolerance=1)
        except AttributeError:      # versiones antiguas de pdfplumber
            clean = page
        bands = _bands(_page_items(clean))
        for b in bands:
            b["image"] = _is_image_band(b)
        pages.append((page, clean, bands))

    pw, ph = float(pdf.pages[0].width), float(pdf.pages[0].height)
    lefts = [b["x0"] for _, _c, bs in pages for b in bs if b["x0"] > 20]
    rights = [b["x1"] for _, _c, bs in pages for b in bs if b["x1"] < pw - 20]
    tops = [bs[0]["top"] for _, _c, bs in pages if bs and bs[0]["top"] > 20]
    left = median(lefts) if lefts else 72
    right = pw - (max(rights) if rights else pw - 72)
    top = min(tops) if tops else 72
    text_w = pw - left - right

    d = docx.Document()
    sec = d.sections[0]
    sec.page_width, sec.page_height = Pt(pw), Pt(ph)
    sec.left_margin, sec.right_margin = Pt(left), Pt(right)
    sec.top_margin, sec.bottom_margin = Pt(top), Pt(12)
    normal = d.styles["Normal"]
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.line_spacing = 1.0

    for n, (page, clean, bands) in enumerate(pages):
        scale = _RES / 72
        im = page.to_image(resolution=_RES).original.convert("RGB")
        px0 = float(page.bbox[0])
        cols = [b for b in bands if b["image"]]
        full = [b for b in cols if (b["x1"] - b["x0"]) > 0.9 * pw]
        norm = [b for b in cols if b not in full]
        pl = min([b["x0"] for b in norm] or [left]) - 2
        pr = max([b["x1"] for b in norm] or [pw - right]) + 2

        first = True
        prev_end = None
        for i, b in enumerate(bands):
            gap_prev = (b["top"] - bands[i - 1]["bottom"]) if i else 0
            gap_next = (bands[i + 1]["top"] - b["bottom"]) if i + 1 < len(bands) else 0
            if b["image"]:
                y0 = b["top"] - (gap_prev / 2 if i else 2)
                y1 = b["bottom"] + (gap_next / 2 if i + 1 < len(bands) else 2)
                x0, x1 = (0, pw) if b in full else (pl, max(pr, b["x1"] + 2))
                y0, y1 = max(0, y0), min(ph, y1)
                crop = im.crop((int((x0 - px0) * scale), int(y0 * scale),
                                int((x1 - px0) * scale), int(y1 * scale)))
                buf = io.BytesIO()
                crop.save(buf, "PNG", optimize=True)
                buf.seek(0)
                p = d.add_paragraph()
                w = x1 - x0
                indent = x0 - left
                if w > text_w + 1:
                    w, indent = text_w, 0
                p.paragraph_format.left_indent = Pt(indent)
                run = p.add_run()
                run.font.size = Pt(1)
                _tiny_mark(p)
                run.add_picture(buf, width=Pt(w))
                start, end = y0, y1
            else:
                chars = [c for c in clean.chars
                         if b["top"] - 1 <= (c["top"] + c["bottom"]) / 2 <= b["bottom"] + 1]
                runs = _paragraph_runs(chars)
                p = d.add_paragraph()
                p.paragraph_format.left_indent = Pt(max(0, b["x0"] - left))
                for t, (bold, italic, size, fam) in runs:
                    r = p.add_run(clean_xml(t))
                    r.bold, r.italic = bold, italic
                    r.font.size = Pt(size)
                    if fam:
                        r.font.name = fam
                start, end = b["top"], b["bottom"]
            if first:
                p.paragraph_format.page_break_before = n > 0
                p.paragraph_format.space_before = Pt(max(0, start - top)) if n == 0 or True else Pt(0)
                first = False
            elif prev_end is not None:
                p.paragraph_format.space_before = Pt(max(0, start - prev_end))
            prev_end = end
        if first:                                # página sin contenido
            p = d.add_paragraph()
            p.paragraph_format.page_break_before = n > 0
    d.save(str(out))
    return out


# --- Motor PDF -> Word con ecuaciones nativas (módulos incrustados) -------------
_SRC_MATHPDF = '"""Reconstruye fórmulas de un PDF (letras con posición/tamaño/fuente + barras + curvas)\ncomo ecuaciones nativas de Word (OMML). Sin OCR."""\nfrom collections import Counter\nfrom statistics import median\n\nM_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"\nW_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"\n\nLP = set("\uf8eb\uf8ec\uf8ed⎛⎜⎝")\nRP = set("\uf8f6\uf8f7\uf8f8⎞⎟⎠")\nOPS = set("=+−±×≈≤≥≡≠→<>·∝")\n_SYMBOL_PUA = dict(zip("abcdefghijklmnopqrstuvwxyz",\n                       "αβχδεφγηιϕκλμνοπθρστυϖωξψζ"))\n_SYMBOL_HI = {0xB0: "°", 0xB1: "±", 0xB2: "″", 0xB3: "≥", 0xB4: "×", 0xB5: "∝", 0xB6: "∂", 0xB7: "·",\n              0xB8: "÷", 0xB9: "≠", 0xBA: "≡", 0xBB: "≈", 0xA3: "≤", 0xA5: "∞", 0xAB: "↔", 0xAC: "←",\n              0xAD: "↑", 0xAE: "→", 0xAF: "↓", 0xD1: "∇", 0xD5: "∏", 0xD6: "√", 0xD7: "⋅", 0xE5: "∑",\n              0xF2: "∫", 0xA2: "′", 0xBC: "…", 0xC5: "⊕", 0xC6: "∅", 0xC7: "∩", 0xC8: "∪", 0xCE: "∈"}\n_SYMBOL_LO = {0x2D: "−", 0x3D: "=", 0x2B: "+", 0x28: "(", 0x29: ")", 0x2C: ",", 0x2E: ".", 0x2F: "/",\n              0x3C: "<", 0x3E: ">", 0x5B: "[", 0x5D: "]", 0x2A: "∗", 0x3A: ":", 0x3B: ";"}\n_GREEK_UP = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ",\n                     "ΑΒΧΔΕΦΓΗΙϑΚΛΜΝΟΠΘΡΣΤΥςΩΞΨΖ"))\n\n\ndef norm_char(c):\n    """Texto Unicode utilizable de un carácter de pdfplumber (\'\' = descartar)."""\n    t = c["text"]\n    f = c.get("fontname", "")\n    if t.startswith("(cid:"):\n        return "=" if t == "(cid:31)" and "ymbol" in f else ""\n    if len(t) != 1:\n        return t\n    o = ord(t)\n    if 0xF020 <= o <= 0xF0FF and "ymbol" in f:\n        k = chr(o - 0xF000)\n        return (_SYMBOL_PUA.get(k) or _GREEK_UP.get(k) or _SYMBOL_LO.get(o - 0xF000)\n                or _SYMBOL_HI.get(o - 0xF000) or (k if k.isdigit() else ""))\n    return {"∆": "Δ", "µ": "μ", "Ω": "Ω", "\xa0": " "}.get(t, t)\n\n\ndef is_italic_font(c):\n    n = c.get("fontname", "").lower()\n    return "italic" in n or n.endswith("-it") or "oblique" in n or n.endswith("-ital")\n\n\ndef _cx(c):\n    return (c["x0"] + c["x1"]) / 2\n\n\ndef _cy(c):\n    return (c["top"] + c["bottom"]) / 2\n\n\nclass A:\n    """Átomo de la secuencia horizontal."""\n    def __init__(self, kind, x0, x1, top, bottom, size, node=None, ch="", ital=False, cy=None, raw=None):\n        self.raw = raw\n        self.kind, self.x0, self.x1 = kind, x0, x1\n        self.top, self.bottom, self.size = top, bottom, size\n        self.node, self.ch, self.ital = node, ch, ital\n        self.cy = (top + bottom) / 2 if cy is None else cy\n\n\n# --------------------------------------------------------------------------\ndef _atoms(chars, bars=(), curves=(), want_left=False):\n    """Extrae raíces, fracciones, rayas y paréntesis grandes; devuelve (átomos, tamaño de referencia)."""\n    atoms = []\n    left = []\n    used_bars = set()\n    used_curves = set()\n    pool = []\n    for c in chars:\n        t = norm_char(c)\n        if t.strip():\n            d = dict(c)\n            d["t"] = t\n            pool.append(d)\n    bars = list(bars)\n\n    # ---- raíces -------------------------------------------------------\n    for cv in sorted(curves, key=lambda r: r[0] - r[1]):\n        ins = [c for c in pool if cv[0] <= _cx(c) <= cv[1] + 0.5 and cv[2] - 1 <= _cy(c) <= cv[3] + 1]\n        ibars = [b for b in bars if cv[0] - 0.5 <= b[0] and b[1] <= cv[1] + 0.5 and cv[2] - 1 <= b[2] <= cv[3] + 1]\n        if not ins:\n            continue\n        used_curves.add(cv)\n        for c in ins:\n            pool.remove(c)\n        for b in ibars:\n            used_bars.add(b)\n            bars.remove(b)\n        size = median(c["size"] for c in ins)\n        atoms.append(A("n", cv[0], cv[1], cv[2], cv[3], size,\n                       node=("rad", parse(ins, ibars)), cy=(cv[2] + cv[3]) / 2))\n\n    # ---- fracciones y rayas superiores (de dentro hacia fuera) -----------\n    for b in sorted(bars, key=lambda b: b[1] - b[0]):\n        x0, x1, y = b\n        near = [c for c in pool if x0 - 1.5 <= _cx(c) <= x1 + 1.5 and abs(_cy(c) - y) <= 16]\n        sz = max((c["size"] for c in near), default=11)\n        win = 1.05 * sz\n        span_all = [c for c in pool if x0 - 1.5 <= _cx(c) <= x1 + 1.5\n                    or (c["size"] < 0.82 * sz and x1 < _cx(c) <= x1 + 8 and c["x0"] <= x1 + 1.5)]\n        span = [c for c in span_all\n                if abs(_cy(c) - y) <= (win if c["size"] >= 0.82 * sz else 1.4 * sz)]\n        up = [c for c in span if _cy(c) < y - 0.5]\n        dn = [c for c in span if _cy(c) > y + 0.5]\n        # fracciones internas ya construidas, pegadas a la barra\n        up_a = [a for a in atoms if a.kind == "n" and x0 - 1.5 <= (a.x0 + a.x1) / 2 <= x1 + 1.5 and 0 <= y - a.bottom <= 5]\n        dn_a = [a for a in atoms if a.kind == "n" and x0 - 1.5 <= (a.x0 + a.x1) / 2 <= x1 + 1.5 and 0 <= a.top - y <= 5]\n        for lst, atl in ((up, up_a), (dn, dn_a)):\n            for a_ in atl:\n                for c in span_all:\n                    if c not in up and c not in dn and abs(_cy(c) - a_.cy) <= 0.4 * c["size"]:\n                        lst.append(c)\n        if (up or up_a) and (dn or dn_a):\n            used_bars.add(b)\n            for q in list(bars):\n                if q is not b and x0 - 1.5 <= q[0] and q[1] <= x1 + 1.5 and q in used_bars:\n                    pass\n            for c in up + dn:\n                pool.remove(c)\n            for a_ in up_a + dn_a:\n                atoms.remove(a_)\n            allc = up + dn\n            size = median(c["size"] for c in allc) if allc else sz\n            tops = [c["top"] for c in up] + [a_.top for a_ in up_a]\n            bots = [c["bottom"] for c in dn] + [a_.bottom for a_ in dn_a]\n            nu = _sub_parse(up, up_a)\n            de = _sub_parse(dn, dn_a)\n            atoms.append(A("n", x0, x1, min(tops), max(bots), size, node=("f", nu, de), cy=y))\n        elif dn and not up:\n            nr = [c for c in dn if c["top"] - y < 5]\n            if nr:\n                used_bars.add(b)\n                for c in nr:\n                    pool.remove(c)\n                size = median(c["size"] for c in nr)\n                atoms.append(A("n", x0, x1, y, max(c["bottom"] for c in nr), size,\n                               node=("ob", parse(nr)), cy=(y + max(c["bottom"] for c in nr)) / 2))\n\n    # ---- paréntesis grandes (piezas de la fuente Symbol) ----------------\n    for kind, S in (("lp", LP), ("rp", RP)):\n        pieces = [c for c in pool if c["t"] in S]\n        for c in pieces:\n            pool.remove(c)\n        groups = []\n        for c in sorted(pieces, key=lambda c: c["x0"]):\n            for g in groups:\n                if abs(g[0]["x0"] - c["x0"]) < 3:\n                    g.append(c)\n                    break\n            else:\n                groups.append([c])\n        for g in groups:\n            atoms.append(A(kind, min(c["x0"] for c in g), max(c["x1"] for c in g),\n                           min(c["top"] for c in g), max(c["bottom"] for c in g), g[0]["size"]))\n\n    # ---- caracteres restantes ------------------------------------------\n    for c in pool:\n        atoms.append(A("c", c["x0"], c["x1"], c["top"], c["bottom"], c["size"], ch=c["t"],\n                       ital=is_italic_font(c), raw=c))\n\n    for b in bars:\n        if b not in used_bars:\n            left.append((b[0] - 0.5, b[1] + 0.5, b[2] - 0.8, b[2] + 0.8))\n    for cv in curves:\n        if cv not in used_curves:\n            left.append((cv[0], cv[1], cv[2], cv[3]))\n    if not atoms:\n        return ([], 11, left) if want_left else ([], 11)\n    sizes = Counter(round(a.size * 2) / 2 for a in atoms if a.kind == "c")\n    if sizes:\n        top_n = max(sizes.values())\n        ref = max(s for s, n in sizes.items() if n >= top_n * 0.5)\n    else:\n        ref = max(a.size for a in atoms)\n    if ref < 7:\n        ref = max(a.size for a in atoms)\n    return (atoms, ref, left) if want_left else (atoms, ref)\n\n\ndef _sub_parse(chars, atoms_in):\n    """Numerador/denominador: caracteres sueltos + fracciones ya construidas."""\n    atoms, ref = _atoms(chars, (), ())\n    atoms += atoms_in\n    if not atoms:\n        return []\n    atoms.sort(key=lambda a: (a.x0, a.top))\n    return _sequence(atoms, ref)\n\n\ndef parse(chars, bars=(), curves=()):\n    """chars: dicts de pdfplumber | bars: (x0, x1, y) | curves: (x0, x1, top, bottom)\n    -> lista de nodos (una sola línea)."""\n    atoms, ref = _atoms(chars, bars, curves)\n    if not atoms:\n        return []\n    atoms.sort(key=lambda a: (a.x0, a.top))\n    return _sequence(atoms, ref)\n\n\ndef _is_math_line(atoms, ref):\n    for a in atoms:\n        if a.kind in ("n", "lp", "rp"):\n            return True\n        if a.size < 0.82 * ref:\n            return True\n        if a.ch in OPS or a.ch in "°′≡∝√∫ΔΩΦΣΠΓΛΨΞΘ" or ("\\u0370" <= a.ch <= "\\u03ff"):\n            return True\n    return False\n\n\ndef parse_lines(chars, bars=(), curves=(), images=()):\n    """Separa el contenido en líneas. Devuelve dicts con: top, bottom, x0, x1, math, nodes, chars, image.\n    image=True: la línea contiene gráficos que no se saben interpretar (se insertará como imagen)."""\n    atoms, ref, left = _atoms(chars, bars, curves, want_left=True)\n    left = list(left) + [tuple(i) for i in images]\n    if not atoms:\n        return [{"top": l[2], "bottom": l[3], "x0": l[0], "x1": l[1], "math": False, "image": True,\n                 "chars": [], "ref": 11} for l in left]\n    seeds = sorted((a for a in atoms if a.size >= 0.82 * ref), key=lambda a: a.cy)\n    if not seeds:\n        seeds = sorted(atoms, key=lambda a: a.cy)\n    lines = []\n    tol = 0.55 * ref\n    for a in seeds:\n        if lines and abs(a.cy - lines[-1]["cy"]) <= tol:\n            lines[-1]["atoms"].append(a)\n            lines[-1]["cy"] = median(x.cy for x in lines[-1]["atoms"])\n        else:\n            lines.append({"cy": a.cy, "atoms": [a]})\n    seed_ids = {id(a) for ln in lines for a in ln["atoms"]}\n    for a in atoms:\n        if id(a) in seed_ids:\n            continue\n        best = min(lines, key=lambda ln: abs(ln["cy"] - a.cy))\n        best["atoms"].append(a)\n    res = []\n    for ln in sorted(lines, key=lambda ln: ln["cy"]):\n        at = sorted(ln["atoms"], key=lambda a: (a.x0, a.top))\n        math = _is_math_line(at, ref)\n        d = {"top": min(a.top for a in at), "bottom": max(a.bottom for a in at),\n             "x0": min(a.x0 for a in at), "x1": max(a.x1 for a in at), "math": math, "ref": ref}\n        d["image"] = False\n        if math:\n            d["nodes"] = _sequence(at, ref)\n        else:\n            d["chars"] = [a.raw for a in at if a.raw is not None]\n        res.append(d)\n    for l in left:\n        cy = (l[2] + l[3]) / 2\n        for d in res:\n            if d["top"] - 3 <= cy <= d["bottom"] + 3:\n                d["image"] = True\n                d["x0"], d["x1"] = min(d["x0"], l[0]), max(d["x1"], l[1])\n                d["top"], d["bottom"] = min(d["top"], l[2]), max(d["bottom"], l[3])\n                break\n        else:\n            res.append({"top": l[2], "bottom": l[3], "x0": l[0], "x1": l[1], "math": False,\n                        "image": True, "chars": [], "ref": ref})\n    res.sort(key=lambda d: d["top"])\n    return res\n\n\n# --------------------------------------------------------------------------\ndef _sequence(atoms, ref):\n    out = []          # lista de entradas: dict(kind, base(node|atom), sub[], sup[], ...)\n    cur_x1 = None\n    prev_big = None   # último átomo de línea base (para huecos)\n    for a in atoms:\n        is_script = a.size < 0.82 * ref and a.kind in ("c", "n") and out and out[-1]["kind"] not in ("lp",)\n        if is_script and a.kind == "n":\n            is_script = abs(a.cy - out[-1]["ref"].cy) > 0.22 * ref\n        if is_script:\n            base = out[-1]["ref"]\n            dy = a.cy - base.cy\n            up = dy < -0.12 * ref\n            e = out[-1]\n            slot = "sup" if up else "sub"\n            e[slot].append(a)\n            continue\n        gap = (a.x0 - cur_x1) if cur_x1 is not None else 0\n        out.append({"kind": a.kind, "ref": a, "gap": gap, "sub": [], "sup": []})\n        cur_x1 = a.x1\n    # recomputar huecos teniendo en cuenta los scripts\n    last_x1 = None\n    for e in out:\n        a = e["ref"]\n        x1 = max([a.x1] + [s.x1 for s in e["sub"] + e["sup"]])\n        e["gap"] = (a.x0 - last_x1) if last_x1 is not None else 0\n        last_x1 = x1\n    return _emit(out, ref)\n\n\ndef _script_nodes(items, ref):\n    """Los scripts son átomos pequeños; se interpretan como una secuencia independiente."""\n    if not items:\n        return []\n    items = sorted(items, key=lambda a: a.x0)\n    sref = max((a.size for a in items if a.kind == "c"), default=ref)\n    out = []\n    last_x1 = None\n    for a in items:\n        gap = (a.x0 - last_x1) if last_x1 is not None else 0\n        out.append({"kind": a.kind, "ref": a, "gap": gap, "sub": [], "sup": []})\n        last_x1 = a.x1\n    return _emit(out, sref)\n\n\ndef _emit(entries, ref):\n    """entries -> nodos. Fusiona caracteres consecutivos en runs, paréntesis grandes en delimitadores."""\n    nodes = []\n    # primero: expandir cada entrada a tokens\n    toks = []\n    for e in entries:\n        a = e["ref"]\n        sub = _script_nodes(e["sub"], ref)\n        sup = _script_nodes(e["sup"], ref)\n        toks.append((a, e["gap"], sub, sup))\n\n    # delimitadores grandes\n    def build(lo, hi):\n        res = []\n        i = lo\n        while i < hi:\n            a, gap, sub, sup = toks[i]\n            if a.kind == "lp":\n                depth, j = 1, i + 1\n                while j < hi:\n                    if toks[j][0].kind == "lp":\n                        depth += 1\n                    elif toks[j][0].kind == "rp":\n                        depth -= 1\n                        if depth == 0:\n                            break\n                    j += 1\n                inner = build(i + 1, j)\n                node = ("d", inner)\n                if j < hi:\n                    sub2, sup2 = toks[j][2], toks[j][3]\n                    res.append(_with_scripts(node, sub2, sup2))\n                    i = j + 1\n                else:\n                    res.append(node)\n                    i = j\n                continue\n            if a.kind == "rp":\n                i += 1\n                continue\n            if a.kind == "n":\n                res.append(("gap", gap))\n                res.append(_with_scripts(a.node, sub, sup))\n            else:\n                res.append(("gap", gap))\n                res.append(("ch", a.ch, a.ital, sub, sup))\n            i += 1\n        return _merge(res, ref)\n\n    return build(0, len(toks))\n\n\ndef _with_scripts(node, sub, sup):\n    if sub and sup:\n        return ("ss", [node], sub, sup)\n    if sup:\n        return ("sup", [node], sup)\n    if sub:\n        return ("sub", [node], sub)\n    return node\n\n\ndef _is_letter(ch):\n    return ch.isalpha()\n\n\ndef _merge(items, ref):\n    """items: (\'gap\', g), (\'ch\', ...), nodos -> lista de nodos con runs fusionados."""\n    nodes = []\n    run = None            # [texto, estilo, nor]\n\n    def flush():\n        nonlocal run\n        if run and run[0]:\n            nodes.append(("t", run[0], run[1]))\n        run = None\n\n    pending_gap = 0.0\n    prev_kind = None\n    for it in items:\n        if it[0] == "gap":\n            pending_gap = it[1]\n            continue\n        if it[0] != "ch":\n            flush()\n            nodes.append(it)\n            prev_kind = "node"\n            pending_gap = 0\n            continue\n        _, ch, ital, sub, sup = it\n        is_op = ch in OPS\n        cls = None\n        if _is_letter(ch) and ch not in "ΔΩΦΣΠΓΛΨΞΘ":\n            greek = "Ͱ" <= ch <= "Ͽ"\n            cls = "i" if (ital or greek) else "p"\n        space = ""\n        if (pending_gap > 0.2 * ref and prev_kind == "ch" and not is_op and ch not in "\'′,.;:)%"\n                and not (run and run[0] and (run[0][-1] in OPS or run[0][-1] == "("))):\n            space = "\u2009"\n        if run is not None and (is_op or cls is None and False):\n            pass\n        if is_op or (sub or sup):\n            # los operadores y las letras con scripts van en runs propios\n            if is_op:\n                flush()\n                nodes.append(("t", ch, "o"))\n                prev_kind = "op"\n                pending_gap = 0\n                if sub or sup:\n                    nodes[-1] = _with_scripts(nodes[-1], sub, sup)\n                continue\n        # texto normal\n        if run is None:\n            run = [space + ch if prev_kind == "ch" else ch, cls or "n", False]\n        else:\n            style = run[1]\n            if cls is not None and style not in ("n", cls):\n                flush()\n                run = [space + ch, cls, False]\n            else:\n                if cls is not None and style == "n":\n                    run[1] = cls\n                run[0] += space + ch\n        prev_kind = "ch"\n        pending_gap = 0\n        if sub or sup:\n            # separar el último carácter (y dígitos precedentes) como base del script\n            txt = run[0]\n            style = run[1]\n            k = len(txt) - 1\n            if ch.isdigit():\n                while k > 0 and (txt[k - 1].isdigit() or txt[k - 1] in ",."):\n                    k -= 1\n            head, base = txt[:k], txt[k:]\n            run = None\n            if head:\n                nodes.append(("t", head, style))\n            nodes.append(_with_scripts(("t", base, style), sub, sup))\n    flush()\n    return nodes\n\n\n# --------------------------------------------------------------------------\ndef to_text(nodes):\n    """Representación legible (depuración)."""\n    s = ""\n    for n in nodes:\n        k = n[0]\n        if k == "t":\n            s += n[1]\n        elif k == "f":\n            s += "{(" + to_text(n[1]) + ")/(" + to_text(n[2]) + ")}"\n        elif k == "sup":\n            s += to_text(n[1]) + "^{" + to_text(n[2]) + "}"\n        elif k == "sub":\n            s += to_text(n[1]) + "_{" + to_text(n[2]) + "}"\n        elif k == "ss":\n            s += to_text(n[1]) + "_{" + to_text(n[2]) + "}^{" + to_text(n[3]) + "}"\n        elif k == "rad":\n            s += "√[" + to_text(n[1]) + "]"\n        elif k == "d":\n            s += "(" + to_text(n[1]) + ")"\n        elif k == "ob":\n            s += "‾[" + to_text(n[1]) + "]"\n    return s\n\n\n# --------------------------------------------------------------------------\ndef to_omml(nodes, font=None):\n    """nodos -> elemento <m:oMath> (lxml)."""\n    from lxml import etree\n\n    def q(ns, tag):\n        return "{%s}%s" % (ns, tag)\n\n    def m(tag, parent=None, **attrs):\n        e = etree.SubElement(parent, q(M_NS, tag)) if parent is not None else etree.Element(q(M_NS, tag), nsmap={"m": M_NS, "w": W_NS})\n        for k, v in attrs.items():\n            e.set(q(M_NS, k), v)\n        return e\n\n    def run(parent, text, style):\n        r = m("r", parent)\n        if style in ("p", "o"):\n            rp = m("rPr", r)\n            m("sty", rp, val="p")\n        if font:\n            wp = etree.SubElement(r, q(W_NS, "rPr"))\n            rf = etree.SubElement(wp, q(W_NS, "rFonts"))\n            for a in ("ascii", "hAnsi", "cs"):\n                rf.set(q(W_NS, a), font)\n        t = m("t", r)\n        t.text = text\n        if text != text.strip() or "\u2009" in text:\n            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")\n\n    def fill(parent, ns):\n        for n in ns:\n            emit(parent, n)\n\n    def box(parent, tag, ns):\n        e = m(tag, parent)\n        if ns:\n            fill(e, ns)\n        else:\n            run(e, "", "n")\n        return e\n\n    def emit(parent, n):\n        k = n[0]\n        if k == "t":\n            run(parent, n[1], n[2])\n        elif k == "f":\n            f = m("f", parent)\n            box(f, "num", n[1])\n            box(f, "den", n[2])\n        elif k == "sup":\n            s = m("sSup", parent)\n            box(s, "e", n[1])\n            box(s, "sup", n[2])\n        elif k == "sub":\n            s = m("sSub", parent)\n            box(s, "e", n[1])\n            box(s, "sub", n[2])\n        elif k == "ss":\n            s = m("sSubSup", parent)\n            box(s, "e", n[1])\n            box(s, "sub", n[2])\n            box(s, "sup", n[3])\n        elif k == "rad":\n            r = m("rad", parent)\n            rp = m("radPr", r)\n            m("degHide", rp, val="1")\n            m("deg", r)\n            box(r, "e", n[1])\n        elif k == "d":\n            d = m("d", parent)\n            dp = m("dPr", d)\n            m("begChr", dp, val="(")\n            m("endChr", dp, val=")")\n            box(d, "e", n[1])\n        elif k == "ob":\n            b = m("bar", parent)\n            bp = m("barPr", b)\n            m("pos", bp, val="top")\n            box(b, "e", n[1])\n\n    root = m("oMath")\n    fill(root, nodes)\n    return root\n'
_SRC_FIEL2 = '"""PDF -> DOCX: texto editable, tablas reales y fórmulas como ecuaciones nativas de Word (OMML).\nLo que no se sabe interpretar (dibujos, glifos vectoriales) se inserta como imagen."""\nimport io\nimport re\nfrom pathlib import Path\nfrom statistics import median\n\nimport docx\nfrom docx.enum.table import WD_ROW_HEIGHT_RULE\nfrom docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING\nfrom docx.oxml import OxmlElement\nfrom docx.oxml.ns import qn\nfrom docx.shared import Pt\nfrom lxml import etree\n\nimport mathpdf as mp\n\nM_NS = mp.M_NS\n_XML_ILLEGAL = re.compile("[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\ud800-\\udfff\ufffe\uffff]")\nRES = 200            # ppp de los recortes de imagen\nBAND_GAP = 4.0       # pt entre bloques verticales distintos\n\n\ndef clean_xml(t):\n    return _XML_ILLEGAL.sub("", t)\n\n\n# --------------------------------------------------------------------------\n# utilidades geométricas y de color\n# --------------------------------------------------------------------------\ndef color_hex(col):\n    if col is None:\n        return None\n    if isinstance(col, (int, float)):\n        col = (col,)\n    try:\n        n = len(col)\n    except TypeError:\n        return None\n    if n == 1:\n        r = g = b = col[0]\n    elif n == 3:\n        r, g, b = col\n    elif n == 4:\n        c, m, y, k = col\n        r, g, b = (1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)\n    else:\n        return None\n    return "%02X%02X%02X" % tuple(int(round(max(0, min(1, v)) * 255)) for v in (r, g, b))\n\n\ndef uniq(values, tol=1.5):\n    out = []\n    for v in sorted(values):\n        if not out or v - out[-1] > tol:\n            out.append(v)\n    return out\n\n\ndef inside(o, box, tol=1.0):\n    cx, cy = (o["x0"] + o["x1"]) / 2, (o["top"] + o["bottom"]) / 2\n    return box[0] - tol <= cx <= box[2] + tol and box[1] - tol <= cy <= box[3] + tol\n\n\ndef is_rule(o, pw, ph):\n    w, h = o["x1"] - o["x0"], o["bottom"] - o["top"]\n    if h < 3 and w > 0.5 * pw:\n        return True\n    if w < 3 and h > 100:\n        return True\n    return w * h > 0.8 * pw * ph\n\n\n# --------------------------------------------------------------------------\n# tablas\n# --------------------------------------------------------------------------\ndef table_page(p, tol=2.0):\n    """Página sin las barras de fracción (líneas horizontales que no tocan ninguna vertical)."""\n    vs = [o for o in p.lines if o["x1"] - o["x0"] < 1 and o["bottom"] - o["top"] > 3]\n\n    def touches(o):\n        for v in vs:\n            for (x, y) in ((o["x0"], o["top"]), (o["x1"], o["top"])):\n                if abs(v["x0"] - x) <= tol and v["top"] - tol <= y <= v["bottom"] + tol:\n                    return True\n        return False\n\n    def keep(o):\n        if o["object_type"] == "curve":\n            return False\n        if o["object_type"] == "line":\n            return (o["bottom"] - o["top"] >= 1) or touches(o)\n        return True\n\n    return p.filter(keep)\n\n\ndef find_tables(page):\n    """Tablas de datos (sin las figuras) con su jerarquía: lista de dicts."""\n    try:\n        raw = table_page(page).find_tables()\n    except Exception:\n        return []\n    pw, ph = float(page.width), float(page.height)\n    figs = [o for o in (page.curves + page.images)]\n    vlines = [l for l in page.lines if l["x1"] - l["x0"] < 1 and 3 < l["bottom"] - l["top"]]\n    out = []\n    for t in raw:\n        x0, top, x1, bottom = t.bbox\n        if (x1 - x0) < 20 or (bottom - top) < 8:\n            continue\n        # tabla = figura si hay muchos gráficos alrededor que no son bordes\n        near = [o for o in figs if o["x1"] > x0 - 5 and o["x0"] < x1 + 5 and o["bottom"] > top - 40 and o["top"] < bottom + 40\n                and not (o["x0"] >= x0 - 1 and o["x1"] <= x1 + 1 and o["top"] >= top - 1 and o["bottom"] <= bottom + 1\n                         and o in page.curves and (o["x1"] - o["x0"]) < 30)]\n        ticks = [l for l in vlines if l["x0"] > x0 - 5 and l["x0"] < x1 + 5 and l["top"] > top - 40 and l["bottom"] < bottom + 40\n                 and not (x0 - 1 <= l["x0"] <= x1 + 1 and top - 1 <= l["top"] and l["bottom"] <= bottom + 1)]\n        if len(near) >= 3 or len(ticks) >= 3:\n            continue\n        out.append({"t": t, "bbox": (x0, top, x1, bottom), "parent": None})\n    for a in out:\n        for b in out:\n            if a is not b:\n                ax0, at, ax1, ab = a["bbox"]\n                bx0, bt, bx1, bb = b["bbox"]\n                if bx0 - 1 <= ax0 and ax1 <= bx1 + 1 and bt - 1 <= at and ab <= bb + 1 and \\\n                        (bx1 - bx0) * (bb - bt) > (ax1 - ax0) * (ab - at):\n                    if a["parent"] is None or (bx1 - bx0) * (bb - bt) < (\n                            a["parent"]["bbox"][2] - a["parent"]["bbox"][0]) * (a["parent"]["bbox"][3] - a["parent"]["bbox"][1]):\n                        a["parent"] = b\n    return out\n\n\ndef cell_grid(t):\n    """Posiciones de columnas/filas y celdas con colspan/rowspan."""\n    cells = [c for row in t.rows for c in row.cells if c]\n    xs = uniq([c[0] for c in cells])\n    ys = uniq([c[1] for c in cells])\n    xr = max(c[2] for c in cells)\n    br = max(c[3] for c in cells)\n    res = []\n    for c in cells:\n        ci = min(range(len(xs)), key=lambda i: abs(xs[i] - c[0]))\n        ri = min(range(len(ys)), key=lambda i: abs(ys[i] - c[1]))\n        cs = sum(1 for x in xs if c[0] - 1.5 <= x < c[2] - 1.5)\n        rs = sum(1 for y in ys if c[1] - 1.5 <= y < c[3] - 1.5)\n        res.append({"bbox": c, "r": ri, "c": ci, "cs": max(1, cs), "rs": max(1, rs)})\n    return xs, ys, xr, br, res\n\n\n# --------------------------------------------------------------------------\n# texto\n# --------------------------------------------------------------------------\ndef char_style(c):\n    n = c.get("fontname", "").lower()\n    bold = any(k in n for k in ("bold", "semibold", "black", "heavy"))\n    italic = "italic" in n or n.endswith("-it") or "oblique" in n\n    fam = "Arial" if "arial" in n else ("Calibri" if "myriad" in n else None)\n    col = color_hex(c.get("non_stroking_color"))\n    if col and all(int(col[i:i + 2], 16) < 0x40 for i in (0, 2, 4)):\n        col = None\n    return (bold, italic, round(c["size"] * 2) / 2, fam, col)\n\n\ndef line_runs(chars):\n    chars = sorted(chars, key=lambda c: c["x0"])\n    runs = []\n    prev = None\n    for c in chars:\n        t = mp.norm_char(c)\n        if not t:\n            continue\n        txt = t\n        if prev is not None and not t.startswith(" ") and not runs[-1][0].endswith(" "):\n            gap = c["x0"] - prev["x1"]\n            if gap > min(3.0, 0.14 * c["size"]) and t[0] not in ".,;:)%!?" and not runs[-1][0].endswith("("):\n                txt = " " + t\n        st = char_style(c)\n        if runs and runs[-1][1] == st:\n            runs[-1][0] += txt\n        else:\n            runs.append([txt, st])\n        prev = c\n    return runs\n\n\ndef is_dotted(runs):\n    txt = "".join(r[0] for r in runs)\n    return txt.count(". .") >= 4 or txt.count("....") >= 1\n\n\n# --------------------------------------------------------------------------\n# escritura en Word\n# --------------------------------------------------------------------------\nclass Ctx:\n    def __init__(self, doc, left, text_w):\n        self.doc = doc\n        self.left = left\n        self.text_w = text_w\n        self._img = {}\n\n    avail = 0\n\n    def page_image(self, page):\n        k = page.page_number\n        if k not in self._img:\n            self._img[k] = page.to_image(resolution=RES).original.convert("RGB")\n        return self._img[k]\n\n\ndef fix_par(p, before=0.0, after=0.0):\n    pf = p.paragraph_format\n    pf.space_before = Pt(max(0, before))\n    pf.space_after = Pt(after)\n    pf.line_spacing = 1.0\n    return p\n\n\ndef tiny_mark(p, half_points=2):\n    pPr = p._p.get_or_add_pPr()\n    rPr = pPr.find(qn("w:rPr"))\n    if rPr is None:\n        rPr = OxmlElement("w:rPr")\n        pPr.append(rPr)\n    sz = OxmlElement("w:sz")\n    sz.set(qn("w:val"), str(half_points))\n    rPr.append(sz)\n\n\ndef spacer(sink, height, page_break=False):\n    p = sink.new_par()\n    pf = p.paragraph_format\n    pf.space_before = Pt(0)\n    pf.space_after = Pt(0)\n    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY\n    pf.line_spacing = Pt(max(1.0, height))\n    if page_break:\n        pf.page_break_before = True\n    tiny_mark(p)\n    r = p.add_run("")\n    r.font.size = Pt(1)\n    return p\n\n\nclass DocSink:\n    def __init__(self, d):\n        self.d = d\n\n    def new_par(self):\n        return self.d.add_paragraph()\n\n    def add_table(self, rows, cols):\n        return self.d.add_table(rows, cols)\n\n\nclass CellSink:\n    def __init__(self, cell):\n        self.cell = cell\n        self.used_first = False\n\n    def new_par(self):\n        if not self.used_first:\n            self.used_first = True\n            return self.cell.paragraphs[0]\n        return self.cell.add_paragraph()\n\n    def add_table(self, rows, cols):\n        if not self.used_first:\n            self.used_first = True       # el párrafo inicial queda como separador\n        return self.cell.add_table(rows, cols)\n\n\ndef add_text(sink, runs, before, indent, align, pitch=None):\n    p = fix_par(sink.new_par(), before)\n    if pitch:\n        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY\n        p.paragraph_format.line_spacing = Pt(pitch)\n    if indent > 3:\n        p.paragraph_format.left_indent = Pt(indent)\n    if align == "center":\n        p.alignment = WD_ALIGN_PARAGRAPH.CENTER\n    elif align == "right":\n        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT\n    for t, (bold, italic, size, fam, col) in runs:\n        r = p.add_run(clean_xml(t))\n        r.bold, r.italic = bold, italic\n        r.font.size = Pt(size)\n        if fam:\n            r.font.name = fam\n        if col:\n            from docx.shared import RGBColor\n            r.font.color.rgb = RGBColor.from_string(col)\n    return p\n\n\ndef add_math(sink, nodes, before, indent, align):\n    p = fix_par(sink.new_par(), before)\n    if indent > 3:\n        p.paragraph_format.left_indent = Pt(indent)\n    omath = mp.to_omml(nodes)\n    para = etree.SubElement(p._p, "{%s}oMathPara" % M_NS)\n    pr = etree.SubElement(para, "{%s}oMathParaPr" % M_NS)\n    jc = etree.SubElement(pr, "{%s}jc" % M_NS)\n    jc.set("{%s}val" % M_NS, "center" if align == "center" else "left")\n    para.append(omath)\n    return p\n\n\ndef add_image(sink, ctx, page, box, before, indent=0, align=None):\n    x0, top, x1, bottom = box\n    pw, ph = float(page.width), float(page.height)\n    x0, x1 = max(0, x0), min(pw, x1)\n    top, bottom = max(0, top), min(ph, bottom)\n    im = ctx.page_image(page)\n    s = RES / 72.0\n    crop = im.crop((int(x0 * s), int(top * s), int(x1 * s) + 1, int(bottom * s) + 1))\n    buf = io.BytesIO()\n    crop.save(buf, "PNG", optimize=True)\n    buf.seek(0)\n    p = fix_par(sink.new_par(), before)\n    if abs(indent) > 1:\n        p.paragraph_format.left_indent = Pt(indent)\n    over = (x1 - x0) + indent - ctx.avail\n    if over > 1:\n        p.paragraph_format.right_indent = Pt(-over)\n    if align == "center":\n        p.alignment = WD_ALIGN_PARAGRAPH.CENTER\n    tiny_mark(p)\n    run = p.add_run()\n    run.font.size = Pt(1)\n    run.add_picture(buf, width=Pt(x1 - x0))\n    return p\n\n\ndef add_rule(sink, before, indent, width, color):\n    p = fix_par(sink.new_par(), before)\n    p.paragraph_format.left_indent = Pt(max(0, indent))\n    p.paragraph_format.right_indent = Pt(0)\n    pf = p.paragraph_format\n    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY\n    pf.line_spacing = Pt(1)\n    tiny_mark(p)\n    pPr = p._p.get_or_add_pPr()\n    bd = OxmlElement("w:pBdr")\n    b = OxmlElement("w:bottom")\n    b.set(qn("w:val"), "single")\n    b.set(qn("w:sz"), "6")\n    b.set(qn("w:space"), "0")\n    b.set(qn("w:color"), color or "1F6FB2")\n    bd.append(b)\n    pPr.append(bd)\n    p.add_run("").font.size = Pt(1)\n    return p\n\n\n# --------------------------------------------------------------------------\n# elementos de una zona (celda o página): líneas -> ítems\n# --------------------------------------------------------------------------\ndef make_items(lines, container, merge_w):\n    """lines (de parse_lines) -> ítems (\'text\' | \'math\' | \'image\'), uniendo líneas de un mismo párrafo."""\n    items = []\n    for ln in lines:\n        if ln["image"]:\n            items.append({"type": "image", "top": ln["top"], "bottom": ln["bottom"],\n                          "x0": ln["x0"], "x1": ln["x1"]})\n        elif ln["math"]:\n            items.append({"type": "math", "top": ln["top"], "bottom": ln["bottom"],\n                          "x0": ln["x0"], "x1": ln["x1"], "nodes": ln["nodes"]})\n        else:\n            runs = line_runs(ln["chars"])\n            if not runs:\n                continue\n            if is_dotted(runs):\n                items.append({"type": "image", "top": ln["top"], "bottom": ln["bottom"],\n                              "x0": ln["x0"], "x1": ln["x1"]})\n                continue\n            size = max(r[1][2] for r in runs)\n            it = {"type": "text", "top": ln["top"], "bottom": ln["bottom"], "x0": ln["x0"], "x1": ln["x1"],\n                  "runs": runs, "size": size, "n": 1}\n            prev = items[-1] if items else None\n            if (prev and prev["type"] == "text" and abs(prev["size"] - size) <= 0.6\n                    and abs(prev["x0"] - it["x0"]) <= 3 and it["top"] - prev["bottom"] <= 0.3 * size\n                    and (prev["x1"] - prev["x0"]) >= 0.7 * merge_w):\n                prev["runs"].append([" ", prev["runs"][-1][1]])\n                prev["runs"].extend(it["runs"])\n                prev["bottom"] = it["bottom"]\n                prev["n"] += 1\n                prev["x1"] = max(prev["x1"], it["x1"])\n                continue\n            items.append(it)\n    return items\n\n\ndef alignment_for(it, box_x0, box_x1, pad):\n    w = it["x1"] - it["x0"]\n    cx = (it["x0"] + it["x1"]) / 2\n    if abs(cx - (box_x0 + box_x1) / 2) <= 4 and it["x0"] - box_x0 > 8 + pad:\n        return "center", 0\n    if it["type"] == "text" and abs(it["x1"] - box_x1) <= 3 and it["x0"] - box_x0 > 40:\n        return "right", 0\n    return "left", it["x0"] - box_x0 - pad\n\n\ndef emit_items(sink, ctx, page, items, box, top_ref, pad, first_via_anchor=False):\n    """Escribe los ítems en orden. box = (x0, x1) de la zona; top_ref = y de partida."""\n    prev_bottom = top_ref\n    ctx.avail = box[1] - box[0] - pad * 2 if pad else box[1] - box[0]\n    for k, it in enumerate(items):\n        gap = it["top"] - prev_bottom\n        before = max(0.0, gap - 1.0) if (k > 0 or not first_via_anchor) else 0.0\n        align, indent = alignment_for(it, box[0], box[1], pad)\n        t = it["type"]\n        if t == "text":\n            add_text(sink, it["runs"], before, indent, align, (it["bottom"] - it["top"]) / it["n"])\n        elif t == "math":\n            add_math(sink, it["nodes"], before, indent, align)\n        elif t == "image":\n            add_image(sink, ctx, page, (it["x0"] - 1.5, it["top"] - 1.0, it["x1"] + 1.5, it["bottom"] + 1.0),\n                      before, it["x0"] - 1.5 - box[0] - pad, None)\n        elif t == "rule":\n            add_rule(sink, before, it["x0"] - box[0] - pad, it["x1"] - it["x0"], it.get("color"))\n        elif t == "table":\n            if before > 1.5 or k == 0 and not first_via_anchor:\n                spacer(sink, before if before > 1.5 else 1)\n            elif k > 0 and items[k - 1]["type"] == "table":\n                spacer(sink, 1)\n            build_table(sink, ctx, page, it, box, pad)\n        prev_bottom = max(it["bottom"], prev_bottom if it["type"] == "rule" else it["bottom"])\n        if t == "image":\n            prev_bottom += 2.5\n\n\n# --------------------------------------------------------------------------\n# tablas -> Word\n# --------------------------------------------------------------------------\ndef set_tbl_indent(tbl, twips):\n    tblPr = tbl._tbl.tblPr\n    for e in tblPr.findall(qn("w:tblInd")):\n        tblPr.remove(e)\n    ind = OxmlElement("w:tblInd")\n    ind.set(qn("w:w"), str(int(twips)))\n    ind.set(qn("w:type"), "dxa")\n    succ = [qn("w:tblBorders"), qn("w:shd"), qn("w:tblLayout"), qn("w:tblCellMar"), qn("w:tblLook")]\n    for i, ch in enumerate(list(tblPr)):\n        if ch.tag in succ:\n            tblPr.insert(i, ind)\n            return\n    tblPr.append(ind)\n\n\ndef set_shading(cell, hexcol):\n    tcPr = cell._tc.get_or_add_tcPr()\n    for e in tcPr.findall(qn("w:shd")):\n        tcPr.remove(e)\n    shd = OxmlElement("w:shd")\n    shd.set(qn("w:val"), "clear")\n    shd.set(qn("w:color"), "auto")\n    shd.set(qn("w:fill"), hexcol)\n    tcPr.append(shd)\n\n\ndef cell_fill(page, bbox):\n    x0, top, x1, bottom = bbox\n    area = max(1.0, (x1 - x0) * (bottom - top))\n    best = None\n    for r in page.rects:\n        if not r.get("fill"):\n            continue\n        ix = min(x1, r["x1"]) - max(x0, r["x0"])\n        iy = min(bottom, r["bottom"]) - max(top, r["top"])\n        if ix > 0 and iy > 0 and ix * iy >= 0.85 * area:\n            hx = color_hex(r.get("non_stroking_color"))\n            if hx and hx != "FFFFFF":\n                best = hx\n    return best\n\n\ndef build_table(sink, ctx, page, it, box, pad):\n    node = it["node"]\n    t = node["t"]\n    xs, ys, xr, br, cells = cell_grid(t)\n    tbl = sink.add_table(len(ys), len(xs))\n    tbl.style = "Table Grid"\n    tbl.autofit = False\n    widths = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)] + [xr - xs[-1]]\n    total = sum(widths)\n    tblPr = tbl._tbl.tblPr\n    for e in tblPr.findall(qn("w:tblW")):\n        tblPr.remove(e)\n    w_el = OxmlElement("w:tblW")\n    w_el.set(qn("w:w"), str(int(total * 20)))\n    w_el.set(qn("w:type"), "dxa")\n    tblPr.insert(1 if tblPr.find(qn("w:tblStyle")) is not None else 0, w_el)\n    set_tbl_indent(tbl, max(0, (xs[0] - box[0] - pad)) * 20)\n    for i, wd in enumerate(widths):\n        tbl.columns[i].width = Pt(wd)\n    row_h = [ (ys[i + 1] if i + 1 < len(ys) else br) - ys[i] for i in range(len(ys))]\n    for i, row in enumerate(tbl.rows):\n        row.height = Pt(max(1.0, row_h[i]))\n        row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST\n    done = []\n    # fusiones primero\n    for c in cells:\n        a = tbl.cell(c["r"], c["c"])\n        if c["cs"] > 1 or c["rs"] > 1:\n            a = a.merge(tbl.cell(min(len(ys) - 1, c["r"] + c["rs"] - 1), min(len(xs) - 1, c["c"] + c["cs"] - 1)))\n    for c in cells:\n        cell = tbl.cell(c["r"], c["c"])\n        if any(cell._tc is e for e in done):\n            continue\n        done.append(cell._tc)\n        cell.width = Pt(sum(widths[c["c"]:c["c"] + c["cs"]]))\n        fill = cell_fill(page, c["bbox"])\n        if fill:\n            set_shading(cell, fill)\n        fill_cell(cell, ctx, page, c["bbox"], node)\n\n\ndef fill_cell(cell, ctx, page, bbox, tnode):\n    x0, top, x1, bottom = bbox\n    clean = ctx.clean\n    nested = [n for n in ctx.tables if n["parent"] is tnode and\n              x0 - 1.5 <= n["bbox"][0] and n["bbox"][2] <= x1 + 1.5 and top - 1.5 <= n["bbox"][1] and n["bbox"][3] <= bottom + 1.5]\n\n    def in_nested(o):\n        return any(inside(o, n["bbox"], 1.5) for n in nested)\n\n    chars = [c for c in clean.chars if c["text"].strip() and inside(c, bbox, 0) and not in_nested(c)]\n    bars = [(l["x0"], l["x1"], l["top"]) for l in page.lines\n            if l["bottom"] - l["top"] < 1 and l["x1"] - l["x0"] >= 2\n            and l["x0"] > x0 + 1.5 and l["x1"] < x1 - 1.5 and top + 1 < l["top"] < bottom - 1 and not in_nested(l)]\n    curves = [(c["x0"], c["x1"], c["top"], c["bottom"]) for c in page.curves\n              if c["x0"] >= x0 - 0.5 and c["x1"] <= x1 + 0.5 and c["top"] >= top - 0.5 and c["bottom"] <= bottom + 0.5\n              and not in_nested(c)]\n    images = [(i["x0"], i["x1"], i["top"], i["bottom"]) for i in page.images\n              if i["x0"] >= x0 - 0.5 and i["x1"] <= x1 + 0.5 and i["top"] >= top - 0.5 and i["bottom"] <= bottom + 0.5\n              and not in_nested(i)]\n    lines = mp.parse_lines(chars, bars, curves, images)\n    items = make_items(lines, (x0, x1), (x1 - x0) - 12)\n    for n in nested:\n        items.append({"type": "table", "node": n, "top": n["bbox"][1], "bottom": n["bbox"][3],\n                      "x0": n["bbox"][0], "x1": n["bbox"][2]})\n    items.sort(key=lambda it: it["top"])\n    sink = CellSink(cell)\n    if not items:\n        return\n    emit_items(sink, ctx, page, items, (x0, x1), top, 5.4)\n    # el último elemento de una celda debe ser un párrafo\n    last = cell._tc[-1]\n    if last.tag != qn("w:p"):\n        p = cell.add_paragraph()\n        tiny_mark(p)\n        p.paragraph_format.space_after = Pt(0)\n\n\n# --------------------------------------------------------------------------\n# página\n# --------------------------------------------------------------------------\ndef flow_items(page, clean, top_tables, ctx):\n    pw, ph = float(page.width), float(page.height)\n    boxes = [t["bbox"] for t in top_tables]\n\n    def out(o):\n        return not any(inside(o, b, 1.5) for b in boxes)\n\n    chars = [c for c in clean.chars if c["text"].strip() and out(c)]\n    hbars, others, curves, rules = [], [], [], []\n    for l in page.lines:\n        if is_rule(l, pw, ph):\n            if l["bottom"] - l["top"] < 3 and l["x1"] - l["x0"] > 0.5 * pw and out(l):\n                rules.append(l)\n            continue\n        if not out(l):\n            continue\n        if l["bottom"] - l["top"] < 1:\n            if l["x1"] - l["x0"] >= 3:\n                hbars.append((l["x0"], l["x1"], l["top"]))\n            else:\n                others.append((l["x0"], l["x1"], l["top"], l["bottom"]))\n        else:\n            others.append((l["x0"], l["x1"], l["top"], l["bottom"]))\n    for c in page.curves:\n        if out(c) and not is_rule(c, pw, ph):\n            curves.append((c["x0"], c["x1"], c["top"], c["bottom"]))\n    for r in page.rects:\n        if out(r) and not is_rule(r, pw, ph):\n            others.append((r["x0"], r["x1"], r["top"], r["bottom"]))\n    for i in page.images:\n        if out(i):\n            others.append((i["x0"], i["x1"], i["top"], i["bottom"]))\n\n    curves = [c for c in curves if c[1] - c[0] > 0.3 or c[3] - c[2] > 0.3]\n    others = [o for o in others if o[1] - o[0] > 0.3 or o[3] - o[2] > 0.3]\n    seen, rr = set(), []\n    for r in rules:\n        k = (round(r["top"]), round(r["x0"]), round(r["x1"]))\n        if k not in seen:\n            seen.add(k)\n            rr.append(r)\n    rules = rr\n    ents = [(c["top"], c["bottom"], "c", c) for c in chars]\n    ents += [(b[2] - 0.4, b[2] + 0.4, "b", b) for b in hbars]\n    ents += [(c[2], c[3], "v", c) for c in curves]\n    ents += [(o[2], o[3], "o", o) for o in others]\n    bands = []\n    big = [e for e in ents if e[2] == "c" and e[3]["size"] >= 14]\n    rest = [e for e in ents if not (e[2] == "c" and e[3]["size"] >= 14)]\n    for grp in (big, rest):\n        grp.sort(key=lambda e: e[0])\n        cur = []\n        for e in grp:\n            if cur and e[0] - cur[-1]["bottom"] <= BAND_GAP:\n                cur[-1]["e"].append(e)\n                cur[-1]["bottom"] = max(cur[-1]["bottom"], e[1])\n            else:\n                cur.append({"e": [e], "top": e[0], "bottom": e[1]})\n        bands += cur\n    bands.sort(key=lambda b: b["top"])\n    items = []\n    lines_all = []\n    for b in bands:\n        ch = [e[3] for e in b["e"] if e[2] == "c"]\n        bs = [e[3] for e in b["e"] if e[2] == "b"]\n        cv = [e[3] for e in b["e"] if e[2] == "v"]\n        ot = [e[3] for e in b["e"] if e[2] == "o"]\n        lines = mp.parse_lines(ch, bs, cv, ot)\n        if any(l["image"] for l in lines) or not lines:\n            xs0 = min(e[3]["x0"] if e[2] == "c" else (e[3][0]) for e in b["e"])\n            xs1 = max(e[3]["x1"] if e[2] == "c" else (e[3][1]) for e in b["e"])\n            items.append({"type": "image", "top": b["top"], "bottom": b["bottom"], "x0": xs0, "x1": xs1})\n        else:\n            lines_all.append(lines)\n            items += make_items(lines, (0, pw), ctx.text_w)\n    for r in rules:\n        items.append({"type": "rule", "top": r["top"], "bottom": r["top"] + 1, "x0": r["x0"], "x1": r["x1"],\n                      "color": color_hex(r.get("stroking_color"))})\n    return items\n\n\ndef convert(src, out, progress=None):\n    import pdfplumber\n    src, out = Path(src), Path(out)\n    pdf = pdfplumber.open(str(src))\n    first = pdf.pages[0]\n    pw, ph = float(first.width), float(first.height)\n\n    # márgenes a partir de las tablas y del texto\n    xs0, xs1 = [], []\n    for pg in pdf.pages[1:]:\n        for t in find_tables(pg):\n            xs0.append(t["bbox"][0])\n            xs1.append(t["bbox"][2])\n    left = median(xs0) if xs0 else 72.0\n    right_edge = max(xs1) if xs1 else pw - 72.0\n    left = max(0.0, left)\n    text_w = right_edge - left\n\n    d = docx.Document()\n    sec = d.sections[0]\n    sec.page_width, sec.page_height = Pt(pw), Pt(ph)\n    sec.left_margin, sec.right_margin = Pt(left), Pt(max(0, pw - right_edge))\n    TOP = 18.0\n    sec.top_margin, sec.bottom_margin = Pt(TOP), Pt(0)\n    sec.header_distance = sec.footer_distance = Pt(0)\n    normal = d.styles["Normal"]\n    normal.font.size = Pt(11)\n    normal.font.name = "Calibri"\n    normal.paragraph_format.space_before = Pt(0)\n    normal.paragraph_format.space_after = Pt(0)\n    normal.paragraph_format.line_spacing = 1.0\n    ctx = Ctx(d, left, text_w)\n    sink = DocSink(d)\n\n    for n, page in enumerate(pdf.pages):\n        try:\n            clean = page.dedupe_chars(tolerance=1)\n        except AttributeError:\n            clean = page\n        ctx.clean = clean\n        tables = find_tables(page)\n        ctx.tables = tables\n        top_tables = [t for t in tables if t["parent"] is None]\n        try:\n            items = flow_items(page, clean, top_tables, ctx)\n            for t in top_tables:\n                b = t["bbox"]\n                items.append({"type": "table", "node": t, "top": b[1], "bottom": b[3], "x0": b[0], "x1": b[2]})\n            items.sort(key=lambda it: (it["top"], 0 if it["type"] == "rule" else 1))\n            if not items:\n                spacer(sink, 1, page_break=n > 0)\n                continue\n            first_top = items[0]["top"]\n            spacer(sink, max(1.0, first_top - TOP), page_break=n > 0)\n            emit_items(sink, ctx, page, items, (left, left + text_w), first_top, 0.0, first_via_anchor=True)\n        except Exception:\n            # último recurso: la página entera como imagen\n            import traceback\n            traceback.print_exc()\n            sink_p = spacer(sink, 1, page_break=n > 0)\n            add_image(sink, ctx, page, (0, 0, pw, ph), 0, 0)\n        if progress:\n            progress(n + 1, len(pdf.pages))\n    d.save(str(out))\n    return out\n\n\nif __name__ == "__main__":\n    import sys\n    print(convert(sys.argv[1], sys.argv[2]))\n'
_ENGINE = {}


def _engine():
    """Carga (una vez) los módulos incrustados mathpdf y pdfword."""
    if "mod" not in _ENGINE:
        import types
        mp = types.ModuleType("mathpdf")
        sys.modules["mathpdf"] = mp
        exec(compile(_SRC_MATHPDF, "mathpdf", "exec"), mp.__dict__)
        fm = types.ModuleType("pdfword")
        exec(compile(_SRC_FIEL2, "pdfword", "exec"), fm.__dict__)
        _ENGINE["mod"] = fm
    return _ENGINE["mod"]


def pdf_to_docx(src, _):
    """PDF -> DOCX: texto editable, tablas reales y fórmulas como ecuaciones de Word; lo no interpretable, como imagen."""
    try:
        import pdfplumber  # noqa: F401
    except ImportError:
        raise RuntimeError("Para esta opción falta pdfplumber.\nInstálalo con:\n"
                           "python -m pip install pdfplumber")
    if docx is None:
        raise RuntimeError("Falta python-docx: pip install python-docx")
    out = out_path(src, "", ".docx")
    try:
        return _engine().convert(src, out)
    except Exception:
        traceback.print_exc()          # si el motor nuevo falla, se usa el antiguo (todo con imágenes)
        return _pdf_to_docx_formulas(src, out)


def parse_pages(text: str, total: int):
    """'1-3, 5, 8-' -> [1, 2, 3, 5, 8, ..., total]"""
    pages = []
    for part in text.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            pages += range(int(a) if a else 1, (int(b) if b else total) + 1)
        else:
            pages.append(int(part))
    if not pages or any(p < 1 or p > total for p in pages):
        raise ValueError(f"Páginas fuera de rango (el PDF tiene {total}).")
    return pages


def pdf_merge(src, others):
    if fitz is None:
        raise RuntimeError("Falta PyMuPDF: pip install pymupdf")
    new = fitz.open()
    for f in [src, *map(Path, others)]:
        new.insert_pdf(fitz.open(f))
    out = out_path(src, "_unido", ".pdf")
    new.save(out)
    return out


def pdf_extract(src, text):
    if fitz is None:
        raise RuntimeError("Falta PyMuPDF: pip install pymupdf")
    doc = fitz.open(src)
    new = fitz.open()
    for p in parse_pages(text, len(doc)):
        new.insert_pdf(doc, from_page=p - 1, to_page=p - 1)
    out = out_path(src, "_paginas", ".pdf")
    new.save(out)
    return out


def pdf_rotate(src, value):
    if fitz is None:
        raise RuntimeError("Falta PyMuPDF: pip install pymupdf")
    angle = {"90° a la derecha": 90, "180°": 180, "90° a la izquierda": 270}[value]
    doc = fitz.open(src)
    for page in doc:
        page.set_rotation((page.rotation + angle) % 360)
    out = out_path(src, "_rotado", ".pdf")
    doc.save(out)
    return out


def pdf_split(src, _):
    if fitz is None:
        raise RuntimeError("Falta PyMuPDF: pip install pymupdf")
    doc = fitz.open(src)
    folder = out_path(src, "_paginas", "")
    folder.mkdir()
    for i in range(len(doc)):
        new = fitz.open()
        new.insert_pdf(doc, from_page=i, to_page=i)
        new.save(folder / f"{src.stem}_{i + 1:03d}.pdf")
    return folder


def img_merge_pdf(src, others):
    paths = [src, *map(Path, others)]
    ims = [flatten(open_image(p)) for p in paths]
    out = out_path(src, "_unido", ".pdf")
    ims[0].save(out, "PDF", save_all=True, append_images=ims[1:])
    return out


def docx_to_txt(src, _):
    if docx is None:
        raise RuntimeError("Falta python-docx: pip install python-docx")
    d = docx.Document(str(src))
    out = out_path(src, "", ".txt")
    out.write_text("\n".join(p.text for p in d.paragraphs), encoding="utf-8")
    return out


def docx_to_pdf(src, _):
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("Para DOCX → PDF necesito LibreOffice instalado.")
    subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir",
                    str(src.parent), str(src)], check=True, capture_output=True)
    return src.with_suffix(".pdf")


def txt_to_docx(src, _):
    if docx is None:
        raise RuntimeError("Falta python-docx: pip install python-docx")
    d = docx.Document()
    for line in src.read_text(encoding="utf-8", errors="replace").splitlines():
        d.add_paragraph(clean_xml(line))
    out = out_path(src, "", ".docx")
    d.save(str(out))
    return out


# --------------------------------------------------------------------------
# Vídeo y audio (FFmpeg)
# --------------------------------------------------------------------------
def vid_to(fmt: str):
    def run(src, _):
        if fmt == "MP4":
            return run_ffmpeg(src, out_path(src, "", ".mp4"), "-c:v", "libx264",
                              "-c:a", "aac", "-movflags", "+faststart")
        if fmt == "WEBM":
            return run_ffmpeg(src, out_path(src, "", ".webm"), "-c:v", "libvpx-vp9",
                              "-crf", "33", "-b:v", "0", "-c:a", "libopus")
        if fmt == "MKV":
            return run_ffmpeg(src, out_path(src, "", ".mkv"), "-c", "copy")
        if fmt == "GIF":
            return run_ffmpeg(src, out_path(src, "", ".gif"), "-an", "-vf",
                              "fps=12,scale=480:-1:flags=lanczos")
        raise ValueError(fmt)
    return run


def vid_extract_mp3(src, _):
    return run_ffmpeg(src, out_path(src, "", ".mp3"), "-vn", "-q:a", "2")


def vid_compress(src, _):
    return run_ffmpeg(src, out_path(src, "_comprimido", ".mp4"), "-c:v", "libx264",
                      "-crf", "28", "-preset", "medium", "-c:a", "aac", "-b:a", "128k")


def av_strip_metadata(src, _):
    return run_ffmpeg(src, out_path(src, "_sin_metadatos", src.suffix),
                      "-map_metadata", "-1", "-c", "copy")


AUDIO_OPTS = {
    "MP3": (".mp3", ["-q:a", "2"]),
    "WAV": (".wav", []),
    "FLAC": (".flac", []),
    "OGG": (".ogg", ["-c:a", "libvorbis", "-q:a", "5"]),
    "OPUS": (".opus", ["-c:a", "libopus"]),
    "M4A": (".m4a", ["-c:a", "aac", "-b:a", "192k"]),
}


def aud_to(fmt: str):
    ext, opts = AUDIO_OPTS[fmt]

    def run(src, _):
        return run_ffmpeg(src, out_path(src, "", ext), "-vn", *opts)
    return run


def aud_compress(src, _):
    return run_ffmpeg(src, out_path(src, "_comprimido", ".mp3"), "-vn", "-b:a", "128k")


# --------------------------------------------------------------------------
# Qué opciones ofrecer según el tipo de archivo
# Cada acción: (etiqueta, función, pregunta previa o None)
# --------------------------------------------------------------------------
def actions_for(path: Path):
    ext = path.suffix.lower()
    acts = []

    if ext in IMG:
        same = {".jpeg": "JPG", ".jpg": "JPG", ".tif": "TIFF"}.get(ext, ext[1:].upper())
        for f in IMG_FORMATS:
            if f != same:
                acts.append((f"Convertir a {f}", img_to(f), None))
        acts += [
            ("Comprimir (equilibrada)", img_compress(False), None),
            ("Comprimir (fuerte)", img_compress(True), None),
            ("Redimensionar…", img_resize, ("int", "Redimensionar", "Ancho en píxeles:", 1280, 16, 20000)),
            ("Recortar (centrado)…", img_crop, ("item", "Recortar", "Proporción:",
                                                ["1:1 · cuadrado", "16:9 · panorámico", "4:3", "3:4", "9:16 · vertical"])),
            ("Quitar metadatos", img_strip_metadata, None),
            ("Unir con otras imágenes en un PDF…", img_merge_pdf,
             ("files", "Elegir las imágenes que quieres añadir",
              "Imágenes (*.jpg *.jpeg *.png *.webp *.heic *.bmp *.tif *.tiff)")),
        ]
    elif ext == ".pdf":
        acts += [
            ("PDF → DOCX (Word)", pdf_to_docx, None),
            ("PDF → imágenes JPG", pdf_to_images("JPG"), None),
            ("PDF → imágenes PNG", pdf_to_images("PNG"), None),
            ("PDF → texto (TXT)", pdf_to_txt, None),
            ("Comprimir PDF", pdf_compress, None),
            ("Unir con otros PDF…", pdf_merge,
             ("files", "Elegir los PDF que quieres añadir", "PDF (*.pdf)")),
            ("Extraer páginas…", pdf_extract,
             ("text", "Extraer páginas", "Páginas (ej.: 1-3, 5, 8-):", "1")),
            ("Rotar páginas…", pdf_rotate,
             ("item", "Rotar", "Giro:", ["90° a la derecha", "180°", "90° a la izquierda"])),
            ("Dividir en páginas sueltas", pdf_split, None),
        ]
    elif ext == ".docx":
        acts += [("DOCX → TXT", docx_to_txt, None), ("DOCX → PDF", docx_to_pdf, None)]
    elif ext == ".txt":
        acts += [("TXT → DOCX", txt_to_docx, None)]
    elif ext in VID:
        for f in ("MP4", "WEBM", "MKV", "GIF"):
            if ext[1:].upper() != f:
                acts.append((f"Convertir a {f}", vid_to(f), None))
        acts += [
            ("Extraer audio (MP3)", vid_extract_mp3, None),
            ("Comprimir vídeo", vid_compress, None),
            ("Quitar metadatos", av_strip_metadata, None),
        ]
    elif ext in AUD:
        for f in AUDIO_OPTS:
            if ext[1:].upper() != f:
                acts.append((f"Convertir a {f}", aud_to(f), None))
        acts += [("Comprimir (MP3 128 kbps)", aud_compress, None),
                 ("Quitar metadatos", av_strip_metadata, None)]
    return acts


# --------------------------------------------------------------------------
# Interfaz
# --------------------------------------------------------------------------
STYLE = """
QWidget { background: #1e1e22; color: #f0f0f0; font-size: 14px; }
#drop { border: 2px dashed #ff9f1c; border-radius: 14px; padding: 18px; color: #ffb84d; }
QPushButton { background: #2c2c33; border: 1px solid #3a3a44; border-radius: 8px; padding: 9px; }
QPushButton:hover { background: #ff9f1c; color: #1e1e22; }
QPushButton:disabled { color: #777; background: #25252b; }
#status { color: #bdbdbd; }
"""


class Bridge(QObject):
    done = Signal(bool, str)


class DropArea(QLabel):
    fileDropped = Signal(str)

    def __init__(self):
        super().__init__("Arrastra un archivo aquí\no haz clic para elegirlo")
        self.setObjectName("drop")
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.setMinimumHeight(110)
        self.setCursor(Qt.PointingHandCursor)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls:
            self.fileDropped.emit(urls[0].toLocalFile())

    def mousePressEvent(self, e):
        path, _ = QFileDialog.getOpenFileName(self, "Elegir archivo")
        if path:
            self.fileDropped.emit(path)


class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Conversor v6")
        self.resize(440, 620)
        self.src = None
        self.last_output = None
        self.buttons = []

        self.drop = DropArea()
        self.drop.fileDropped.connect(self.load_file)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.grid = QGridLayout()
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.reveal_btn = QPushButton("Mostrar en la carpeta")
        self.reveal_btn.hide()
        self.reveal_btn.clicked.connect(self.reveal)

        lay = QVBoxLayout(self)
        lay.addWidget(self.drop)
        lay.addWidget(self.info)
        lay.addLayout(self.grid)
        lay.addStretch()
        lay.addWidget(self.status)
        lay.addWidget(self.reveal_btn)

        self.bridge = Bridge()
        self.bridge.done.connect(self.on_done)

    def load_file(self, p: str):
        path = Path(p)
        if not path.is_file():
            return
        self.src = path
        self.reveal_btn.hide()
        self.status.setText("")
        for b in self.buttons:
            b.deleteLater()
        self.buttons.clear()

        self.info.setText(f"<b>{path.name}</b><br>{human_size(path.stat().st_size)}")
        acts = actions_for(path)
        if not acts:
            self.status.setText(f"No tengo opciones para archivos «{path.suffix}».")
            return
        for i, (label, func, prompt) in enumerate(acts):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, l=label, f=func, p=prompt: self.run_action(l, f, p))
            self.grid.addWidget(b, i // 2, i % 2)
            self.buttons.append(b)

    def run_action(self, label, func, prompt):
        value = None
        if prompt:
            kind = prompt[0]
            if kind == "int":
                _k, title, text, default, lo, hi = prompt
                value, ok = QInputDialog.getInt(self, title, text, default, lo, hi)
            elif kind == "item":
                _k, title, text, items = prompt
                value, ok = QInputDialog.getItem(self, title, text, items, 0, False)
            elif kind == "text":
                _k, title, text, default = prompt
                value, ok = QInputDialog.getText(self, title, text, text=default)
            elif kind == "files":
                _k, title, file_filter = prompt
                value, _f = QFileDialog.getOpenFileNames(
                    self, title, str(self.src.parent), file_filter)
                ok = bool(value)
            else:
                return
            if not ok:
                return
        for b in self.buttons:
            b.setEnabled(False)
        self.reveal_btn.hide()
        self.status.setText(f"Procesando: {label}…")
        src = self.src

        def worker():
            try:
                res = func(src, value)
                self.bridge.done.emit(True, str(res))
            except Exception as ex:  # se muestra al usuario
                traceback.print_exc()
                self.bridge.done.emit(False, str(ex))

        threading.Thread(target=worker, daemon=True).start()

    def on_done(self, ok: bool, msg: str):
        for b in self.buttons:
            b.setEnabled(True)
        if ok:
            self.last_output = Path(msg)
            self.status.setText(f"✔ Guardado en:\n{msg}")
            self.reveal_btn.show()
        else:
            self.status.setText("✖ Error")
            QMessageBox.warning(self, "No se pudo completar", msg)

    def reveal(self):
        p = self.last_output
        if not p:
            return
        if sys.platform == "win32":
            subprocess.Popen(["explorer", f"/select,{p}"])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p if p.is_dir() else p.parent)])


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    w = App()
    w.show()
    sys.exit(app.exec())
