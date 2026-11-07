#!/usr/bin/env python3
"""Construye el índice (colección → bloque → tema → apartados) leyendo las páginas
de índice originales. Salida: JSON con rutas relativas a la carpeta ejercicios/."""
import re, sys, json, html, os
from pathlib import Path
ROOT = Path(sys.argv[1])  # carpeta ejercicios/ ya convertida

ROW = re.compile(r'<tr\b.*?</tr>', re.S | re.I)
def clean(s):
    s = re.sub(r'<[^>]+>', ' ', s); s = html.unescape(s); return re.sub(r'\s+', ' ', s).strip()

def rows(page):
    t = page.read_text(encoding='utf-8')
    out = []
    for r in ROW.findall(t):
        txt = clean(r)
        if not txt: continue
        red = re.search(r'color="?#?FF0000', r, re.I)
        m = re.search(r"cambiar\('([^']+)'", r) or re.search(r"abrirVentana\('([^']+)'", r)
        modal = bool(re.search(r"abrirVentana\('", r))
        if m and not red:
            url = os.path.normpath(os.path.join(page.parent, m.group(1)))
            out.append({'t': txt, 'u': os.path.relpath(url, ROOT).replace('\\', '/'), **({'m': 1} if modal else {})})
        elif red or not m:
            out.append({'h': txt})
    return out

def group(items):
    """Agrupa una lista plana [cabecera, elementos, cabecera, ...]."""
    G, cur = [], None
    for it in items:
        if 'h' in it: cur = {'h': it['h'], 'c': []}; G.append(cur)
        else:
            if cur is None: cur = {'h': '', 'c': []}; G.append(cur)
            cur['c'].append(it)
    return [g for g in G if g['c']]

tree = []
for key, name in (('fisica', 'Física'), ('aplicada', 'Física aplicada')):
    if not (ROOT / key / '0_a.htm').exists(): continue   # colección no publicada
    col = {'k': key, 'n': name, 'home': f'{key}/0.htm', 'g': []}
    for g in group(rows(ROOT / key / '0_a.htm')):
        G = {'h': g['h'], 'c': []}
        for t in g['c']:
            idx = ROOT / Path(t['u']).parent / '0_a.htm'
            T = {'t': t['t'], 'u': t['u']}
            if idx.exists() and 'indices' in t['u']: T['g'] = group(rows(idx))
            G['c'].append(T)
        col['g'].append(G)
    tree.append(col)
print(json.dumps(tree, ensure_ascii=False))
