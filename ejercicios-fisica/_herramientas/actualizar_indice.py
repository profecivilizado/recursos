#!/usr/bin/env python3
"""Genera el menú lateral y las páginas de índice de cada tema.

- Colección «Física»: sale de _herramientas/menu-fisica.json (edítalo tú: temas,
  apartados, orden). Se generan fisica/indices/temas/0.htm (lista de temas) y
  fisica/indices/tNN/0.htm (un índice por tema).
- Colección «Física aplicada»: sale de las páginas de índice originales (arbol.py).

Uso (desde cualquier carpeta):
    python3 _herramientas/actualizar_indice.py
"""
import json, re, subprocess, sys, html
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent          # carpeta ejercicios-fisica
H = RAIZ / '_herramientas'
menu = json.loads((H / 'menu-fisica.json').read_text(encoding='utf-8'))
esc = lambda s: html.escape(s, quote=True)

PAGINA = """<!DOCTYPE html>
<!-- Página generada por _herramientas/actualizar_indice.py: no la edites a mano, cambia menu-fisica.json -->
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="../../../_pc/compat.js"></script>
<title>{titulo}</title>
<link rel="stylesheet" href="../../../_pc/pc.css">
<link rel="stylesheet" href="../../../_pc/problemas.css">
<style>
.grp{{color:var(--red);font-weight:700;font-size:.9em;margin:16px 0 4px}}
.it{{display:block;width:100%;text-align:left;font:inherit;color:var(--accent);font-weight:600;background:none;border:0;border-bottom:1px solid var(--line);padding:10px 8px;cursor:pointer;border-radius:8px}}
.it:hover{{background:var(--hover)}}
.it small{{display:block;color:var(--muted);font-weight:400}}
</style>
</head>
<body onload="{onload}">
<div class="cab"><b>{cabecera}</b></div>
{cuerpo}
</body>
</html>
"""
def boton(u, texto, ventana=False, extra=''):
    destino = '../../../' + u
    accion = f"window.open('{destino}')" if ventana else f"location.href='{destino}'"
    return f'<button class="it" onclick="{accion}">{esc(texto)}{extra}</button>'

TEORIA = """<!DOCTYPE html>
<!-- Página generada por _herramientas/actualizar_indice.py a partir de las ayudas originales: no la edites a mano -->
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="../../../_pc/compat.js"></script>
<title>Teoría · {tema}</title>
<link rel="stylesheet" href="../../../_pc/pc.css">
<link rel="stylesheet" href="../../../_pc/problemas.css">
<style>
.toc{{columns:2 240px;margin:0 0 8px;padding:0 0 0 1.2em}}
.toc a{{text-decoration:none}}
h2{{font-size:1.15em;color:var(--accent);border-top:1px solid var(--line);padding-top:14px;margin:18px 0 4px}}
iframe.pc-teoria{{display:block;width:100%;border:0;height:200px;background:transparent}}
</style>
</head>
<body onload="_pctop.indice='../../indices/{carpeta}/0.htm'">
<div class="cab"><b>TEORÍA</b><span class="nuevo">{tema}</span></div>
<ol class="toc">{indice}</ol>
{secciones}
<script>
// el índice salta a la sección aunque la página esté dentro del visor (que es quien hace scroll)
document.querySelectorAll('.toc a').forEach(a => a.onclick = e => {{
  e.preventDefault(); const h = document.querySelector(a.getAttribute('href'));
  try {{ let y = h.getBoundingClientRect().top, w = window; while (w.frameElement) {{ y += w.frameElement.getBoundingClientRect().top; w = w.parent; }} w.scrollBy({{top: y - 12, behavior: 'smooth'}}); }} catch (_) {{ h.scrollIntoView(); }}
}});
</script>
</body>
</html>
"""
def ayudas_de(fuente):
    """[(título, ruta de la ayuda relativa a RAIZ)] según el desplegable original de buscarAyudas."""
    t = (RAIZ / fuente).read_text(encoding='utf-8', errors='replace')
    base = Path(fuente).parent
    out = []
    for u, tit in re.findall(r'value="\'([^\']*)\'"[^>]*>(.*?)</option', t, re.S):
        ruta = (base / u).as_posix()
        partes = []
        for p in ruta.split('/'):
            if p == '..': partes.pop()
            else: partes.append(p)
        out.append((re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', tit))).strip(), '/'.join(partes)))
    return out

# carpetas de apartados de cada tema (para repartir las ayudas de un bloque entre sus temas)
carpetas = [{'/'.join(it['u'].split('/')[:3]) for it in t['items'] if 'ayudas' not in it} for t in menu['temas']]

temas_tree = []
lista = []
for n, tema in enumerate(menu['temas'], 1):
    carpeta = f't{n:02d}'
    u_tema = f'fisica/indices/{carpeta}/0.htm'
    cuerpo, grupo, g_tree = [], None, []
    for it in tema['items']:
        if it.get('grupo', '') != grupo:
            grupo = it.get('grupo', '')
            if grupo: cuerpo.append(f'<p class="grp">{esc(grupo)}</p>')
            g_tree.append({'h': grupo, 'c': []})
        cuerpo.append(boton(it['u'], it['t'], it.get('ventana')))
        g_tree[-1]['c'].append({'t': it['t'], 'u': it['u'], **({'m': 1} if it.get('ventana') else {})})
    d = RAIZ / 'fisica' / 'indices' / carpeta; d.mkdir(parents=True, exist_ok=True)
    for it in tema['items']:
        if 'ayudas' not in it: continue
        bloque = '/'.join(it['ayudas'].split('/')[:2])
        hermanos = [c for k, c in enumerate(carpetas) if any(x.startswith(bloque + '/') for x in c)]
        secc = []
        for tit, ruta in ayudas_de(it['ayudas']):
            sub = '/'.join(ruta.split('/')[:3])
            # la ayuda va a este tema si es de uno de sus apartados, o si no es de ningún tema del bloque
            if sub in carpetas[n - 1] or not any(sub in c for c in hermanos):
                secc.append((tit, ruta))
        indice = ''.join(f'<li><a href="#s{k}">{esc(tit)}</a></li>' for k, (tit, _) in enumerate(secc, 1))
        secciones = '\n'.join(f'<h2 id="s{k}">{esc(tit)}</h2>\n<iframe class="pc-teoria" src="../../../{ruta}" title="{esc(tit)}" scrolling="no"></iframe>'
                              for k, (tit, ruta) in enumerate(secc, 1))
        (RAIZ / it['u']).write_text(TEORIA.format(tema=esc(tema['n']), carpeta=carpeta, indice=indice, secciones=secciones), encoding='utf-8')
    (d / '0.htm').write_text(PAGINA.format(titulo=esc(tema['n']), cabecera=esc(tema['n'].upper()),
        onload=f"_pctop.indice='../../indices/{carpeta}/0.htm'", cuerpo='\n'.join(cuerpo)), encoding='utf-8')
    temas_tree.append({'t': tema['n'], 'u': u_tema, 'g': g_tree})
    lista.append(boton(u_tema, tema['n']))

d = RAIZ / 'fisica' / 'indices' / 'temas'; d.mkdir(parents=True, exist_ok=True)
(d / '0.htm').write_text(PAGINA.format(titulo=esc(menu['coleccion']), cabecera=esc(menu['coleccion'].upper()),
    onload='', cuerpo='\n'.join(lista)), encoding='utf-8')

# Física aplicada: como antes, desde los índices originales
antiguo = json.loads(subprocess.check_output([sys.executable, str(H / 'arbol.py'), str(RAIZ)], text=True))
arbol = [{'k': 'fisica', 'n': 'Física', 'home': 'fisica/indices/temas/0.htm', 'g': [{'h': '', 'c': temas_tree}]}]
arbol += [c for c in antiguo if c['k'] != 'fisica']

index = RAIZ / 'index.html'
t = index.read_text(encoding='utf-8')
t2, k = re.subn(r'const TREE = .*?;\n', lambda m: 'const TREE = ' + json.dumps(arbol, ensure_ascii=False) + ';\n', t, count=1)
if k != 1: sys.exit('No encuentro «const TREE = …;» en index.html')
index.write_text(t2, encoding='utf-8')
print(f'Menú actualizado: {len(temas_tree)} temas de Física', '(con cambios)' if t2 != t else '(sin cambios)')
