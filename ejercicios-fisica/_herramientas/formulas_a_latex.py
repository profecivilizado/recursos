#!/usr/bin/env python3
r"""Convierte las imágenes de fórmulas de una carpeta del repositorio a LaTeX, sin internet
(salvo la primera vez, que descarga el modelo), y genera una página para revisarlas.

Instalación (una vez):
    pip3 install "pix2tex>=0.1.2"

Uso:
    python3 ejercicios-fisica/_herramientas/formulas_a_latex.py  ejercicios-fisica/fisica/magnetico
    (en Windows: py ejercicios-fisica\_herramientas\formulas_a_latex.py ejercicios-fisica\fisica\magnetico)

Resultado, dentro de esa carpeta:
    formulas_latex.json    {ruta de la imagen: "LaTeX"}  ← lo puedes corregir a mano
    revisar_formulas.html  imagen original al lado de la fórmula en LaTeX, para comparar

Si vuelves a ejecutarlo, no repite las imágenes que ya están en el JSON (así se conservan
tus correcciones); sí repite las que dieron error. Para rehacer una, bórrala del JSON.
"""
import sys, json, html
from pathlib import Path
from PIL import Image

AQUI = Path(__file__).resolve().parent.parent.parent   # carpeta que contiene ejercicios-fisica
if len(sys.argv) > 1:
    carpeta = Path(sys.argv[1])
else:  # sin argumento (por ejemplo, ejecutado desde IDLE o con doble clic): se pregunta
    print('¿Qué bloque convierto? Ejemplos: magnetico, electrico, gravitatorio, vibraciones, ondas, optica…')
    carpeta = AQUI / 'ejercicios-fisica' / 'fisica' / (input('Bloque: ').strip() or 'magnetico')
if not carpeta.is_absolute() and not carpeta.exists():
    carpeta = AQUI / carpeta
if not carpeta.is_dir():
    sys.exit(f'No encuentro la carpeta {carpeta}')
salida = carpeta / 'formulas_latex.json'
hechas = json.loads(salida.read_text(encoding='utf-8')) if salida.exists() else {}

imagenes = sorted(p for p in carpeta.rglob('*') if p.parent.name == 'formulas' and p.suffix.lower() in ('.gif', '.png'))
pendientes = [p for p in imagenes if not hechas.get(p.relative_to(carpeta).as_posix(), '%% ERROR').strip() or hechas.get(p.relative_to(carpeta).as_posix(), '%% ERROR').startswith('%% ERROR')]
print(f'{len(imagenes)} fórmulas, {len(pendientes)} pendientes')

if pendientes:
    from pix2tex.cli import LatexOCR
    modelo = LatexOCR()  # la primera vez descarga el modelo (~100 MB)

    def preparar(p):
        """GIF con transparencia → fondo blanco, y más grande si es muy pequeña."""
        im = Image.open(p).convert('RGBA')
        fondo = Image.new('RGBA', im.size, 'white'); fondo.alpha_composite(im)
        im = fondo.convert('RGB')
        if im.height < 60:
            k = 60 / im.height
            im = im.resize((round(im.width * k), 60), Image.LANCZOS)
        return im

    for i, p in enumerate(pendientes, 1):
        try:
            hechas[p.relative_to(carpeta).as_posix()] = modelo(preparar(p))
        except Exception as e:
            hechas[p.relative_to(carpeta).as_posix()] = f'%% ERROR: {e}'
        print(f'{i}/{len(pendientes)}  {p.relative_to(carpeta)}  →  {hechas[p.relative_to(carpeta).as_posix()]}')
        if i % 20 == 0:  # guarda cada poco por si lo cortas
            salida.write_text(json.dumps(hechas, ensure_ascii=False, indent=1), encoding='utf-8')
    salida.write_text(json.dumps(hechas, ensure_ascii=False, indent=1), encoding='utf-8')

# página de revisión: original | LaTeX dibujado | código
filas = '\n'.join(
    f'<tr><td><img src="{html.escape(r)}"></td><td>$${html.escape(tex)}$$</td><td><code>{html.escape(tex)}</code><br><small>{html.escape(r)}</small></td></tr>'
    for r, tex in sorted(hechas.items()))
(carpeta / 'revisar_formulas.html').write_text(f"""<!DOCTYPE html><meta charset="utf-8"><title>Revisar fórmulas</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js" onload="renderMathInElement(document.body)"></script>
<style>body{{font:15px system-ui;margin:20px}}td{{border-bottom:1px solid #ddd;padding:8px;vertical-align:middle}}code{{font-size:12px;color:#555}}small{{color:#999}}</style>
<h1>Revisar fórmulas ({len(hechas)})</h1><p>Izquierda: imagen original. Centro: lo que ha leído el programa. Si no coinciden, corrige el LaTeX en formulas_latex.json y vuelve a ejecutar el script.</p>
<table>{filas}</table>""", encoding='utf-8')
print('Abre', carpeta / 'revisar_formulas.html', 'para revisarlas')
