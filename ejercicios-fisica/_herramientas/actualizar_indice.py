#!/usr/bin/env python3
"""Vuelve a generar el menú lateral (const TREE de index.html) a partir de las
páginas de índice originales: fisica/0_a.htm, fisica/indices/temaN/0_a.htm, etc.

Úsalo después de añadir una fila nueva en algún indices/temaN/0_a.htm:
    python3 _herramientas/actualizar_indice.py
(se puede lanzar desde cualquier carpeta)."""
import re, subprocess, sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent          # carpeta ejercicios-fisica
arbol = subprocess.check_output([sys.executable, str(RAIZ / '_herramientas' / 'arbol.py'), str(RAIZ)], text=True).strip()
index = RAIZ / 'index.html'
t = index.read_text(encoding='utf-8')
t2, n = re.subn(r'const TREE = .*?;\n', lambda m: 'const TREE = ' + arbol + ';\n', t, count=1)
if n != 1: sys.exit('No encuentro «const TREE = …;» en index.html')
index.write_text(t2, encoding='utf-8')
print('Menú actualizado:', t2 != t and 'con cambios' or 'sin cambios')
