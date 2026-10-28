"""
Puente entre la web y conversor.py (se ejecuta dentro del navegador con Pyodide).

- Carga conversor.py tal cual, sustituyendo PySide6 por objetos vacíos
  (la ventana de escritorio no se usa en la web).
- pdfplumber dibuja las páginas con pypdfium2, que no existe en el navegador:
  la web dibuja cada página con pdf.js y se la pasa aquí ya convertida en PNG.
- Cada acción recibe un archivo del sistema de archivos virtual de Pyodide
  y devuelve la ruta del resultado.
"""
import io
import sys
import types
from pathlib import Path


# ---------- 1. PySide6 de mentira ----------
class _Dummy:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        return _Dummy()

    def __call__(self, *a, **k):
        return _Dummy()


def _fake_module(name):
    m = types.ModuleType(name)
    m.__getattr__ = lambda attr: type(attr, (_Dummy,), {})
    return m


_qtcore = _fake_module("PySide6.QtCore")
_qtcore.Signal = lambda *a, **k: None
_qtcore.Qt = _Dummy()
sys.modules["PySide6"] = _fake_module("PySide6")
sys.modules["PySide6.QtCore"] = _qtcore
sys.modules["PySide6.QtWidgets"] = _fake_module("PySide6.QtWidgets")
sys.modules.setdefault("pypdfium2", types.ModuleType("pypdfium2"))


# ---------- 2. Páginas dibujadas por pdf.js ----------
PAGE_PNG = {}       # número de página -> PNG (bytes)
PAGE_DPI = 200


def set_page_png(n, data):
    PAGE_PNG[int(n)] = bytes(data)


def clear_pages():
    PAGE_PNG.clear()


def _patch_pdfplumber():
    import pdfplumber.page
    from PIL import Image

    def to_image(self, resolution=None, width=None, height=None, **kw):
        if self.page_number not in PAGE_PNG:
            raise RuntimeError(f"Falta la imagen de la página {self.page_number}")
        im = Image.open(io.BytesIO(PAGE_PNG[self.page_number]))
        im.load()
        res = resolution or 72
        target = (max(1, round(float(self.width) * res / 72)),
                  max(1, round(float(self.height) * res / 72)))
        if width:
            target = (int(width), max(1, round(int(width) * im.height / im.width)))
        if im.size != target:
            im = im.resize(target, Image.LANCZOS)
        return types.SimpleNamespace(original=im)

    pdfplumber.page.Page.to_image = to_image


# ---------- 3. Cargar conversor.py ----------
conv = types.ModuleType("conversor")
conv.__file__ = "/conversor/conversor.py"
sys.modules["conversor"] = conv
exec(compile(Path("/conversor/conversor.py").read_text(encoding="utf-8"),
             "conversor.py", "exec"), conv.__dict__)
_patch_pdfplumber()


# ---------- 4. Acciones que la web pide a Python ----------
def _pick(path, label):
    """Busca la acción de conversor.py por su etiqueta (la misma que en la app)."""
    for lab, func, _prompt in conv.actions_for(Path(path)):
        if lab == label:
            return func
    raise ValueError(f"Acción no disponible: {label}")


def run(path, label, value=None):
    """Ejecuta una acción de conversor.py y devuelve la ruta del resultado."""
    func = _pick(path, label)
    out = func(Path(path), value)
    return str(out)


def run_func(name, path, value=None):
    """Ejecuta directamente una función de conversor.py por su nombre."""
    if name == "__to_png__":
        return to_png(path)
    func = getattr(conv, name)
    return str(func(Path(path), value))


def page_count(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return len(pdf.pages)


def to_png(path):
    """Abre con Pillow formatos que el navegador no sabe leer (TIFF…) y devuelve un PNG."""
    im = conv.open_image(Path(path))
    out = Path(path).with_suffix(".decod.png")
    im.save(out, "PNG")
    return str(out)
