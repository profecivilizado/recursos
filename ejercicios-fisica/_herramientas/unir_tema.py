#!/usr/bin/env python3
"""Une todos los problemas de un tema en UNA sola página.

Antes cada problema eran varios archivos (N.htm con dos marcos, N_0.htm con el
enunciado, N_a.htm, N_b.htm… con los apartados) y las aclaraciones se abrían en
ventanas (unidades, desarrollos, mensajes, ayudas). Este script lo junta todo en
una página por tema, con el formato de _plantilla/0.htm:

  · cada problema: enunciado + «Solución» desplegable;
  · cada apartado: botones «Paso a paso» / «Siguiente paso» / «Ver todo»;
  · lo que antes era una ventana se despliega en el mismo sitio;
  · los subproblemas (p. ej. «energía de enlace del N-15») se despliegan dentro;
  · las hojas de «Problemas sueltos» pasan a ser listas de enlaces.

Uso:
    python3 _herramientas/unir_tema.py nuclear            # genera la página
    python3 _herramientas/unir_tema.py nuclear --borrar   # y además borra los archivos antiguos

Las figuras (carpetas imagenes/) y las ayudas (que usa la página de Teoría) no se tocan.
Después edita _herramientas/menu-fisica.json y ejecuta actualizar_indice.py.
"""
import re, sys, html, posixpath
from pathlib import Path
from bs4 import BeautifulSoup, NavigableString, Comment, Tag

RAIZ = Path(__file__).resolve().parent.parent          # carpeta ejercicios-fisica

TEMAS = {
    'cuantica': dict(
        salida='fisica/cuantica/problemas.htm',
        titulo='Tema 11. Física cuántica',
        secciones=[('f', 'Fotones', 'fisica/cuantica/cuantica1'),
                   ('d', 'Dualidad', 'fisica/cuantica/cuantica2'),
                   ('m', 'Preguntas malvadas', 'fisica/cuantica/faq')],
        hojas=[('curso', 'Propuestos en el curso', 'fisica/cuantica/buscar'),
               ('acceso', 'Propuestos en la prueba de acceso', 'fisica/cuantica/buscar2')],
    ),
    'nuclear': dict(
        salida='fisica/nuclear/problemas.htm',
        titulo='Tema 12. Física nuclear',
        secciones=[('r', 'Reacciones nucleares', 'fisica/nuclear/nuclear1'),
                   ('d', 'Desintegraciones radiactivas', 'fisica/nuclear/nuclear2'),
                   ('m', 'Preguntas malvadas', 'fisica/nuclear/faq')],
        hojas=[('curso', 'Propuestos en el curso', 'fisica/nuclear/buscar'),
               ('acceso', 'Propuestos en la prueba de acceso', 'fisica/nuclear/buscar2')],
    ),
}

KATEX = '''<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js" onload="pcKatex()"></script>'''


def leer(p):
    return (RAIZ / p).read_text(encoding='utf-8', errors='replace')


def norm(p):
    return posixpath.normpath(p)


def texto(el):
    return re.sub(r'\s+', ' ', el.get_text(' ')).strip()


def resumen_html(h, maximo=150):
    """Principio del enunciado para las listas: sin etiquetas salvo <sub>/<sup>, sin cortar fórmulas."""
    h = re.sub(r'<span class="num">.*?</span>', '', h, flags=re.S)
    h = re.sub(r'<(?!/?su[bp]\b)[^>]+>', ' ', h)
    h = re.sub(r'\s+', ' ', html.unescape(h)).strip()
    trozos = re.split(r'(\$[^$]*\$|<su[bp]>.*?</su[bp]>)', h)
    out, n = [], 0
    for t in trozos:
        largo = 14 if t.startswith('$') else len(re.sub(r'<[^>]+>', '', t))
        if n + largo > maximo:
            if not t.startswith(('$', '<')):
                out.append(html.escape(t[:max(0, maximo - n)].rsplit(' ', 1)[0]))
            out.append('…')
            break
        out.append(t if t.startswith(('$', '<')) else html.escape(t))
        n += largo
    return ''.join(out)


class Generador:
    def __init__(self, cfg):
        self.cfg = cfg
        self.out_dir = posixpath.dirname(cfg['salida'])
        self.ac_key, self.ac_html = {}, {}      # aclaraciones: ruta → clave, clave → (título, html)
        self.avisos, self.usados = [], set()
        self.ap_ids = {}                         # 'carpeta/problemaN/N_a.htm' → id del apartado

    def aviso(self, s):
        self.avisos.append(s)

    # ---------- utilidades sobre fragmentos ----------
    def accion(self, on, srcdir, ctx):
        """Traduce un onclick antiguo a (atributo, valor) nuevo, o None."""
        m = re.search(r"abrirVentana\(\s*'([^']+)'", on) or re.search(r"MM_openBrWindow\(\s*'([^']+)'", on)
        if m:
            return 'data-ac', self.aclaracion(norm(posixpath.join(srcdir, m.group(1))))
        m = re.search(r"cambiar\(\s*'[^']*'\s*,\s*'([^']+)'\s*\)", on)
        if m and ctx is not None:
            dest = norm(posixpath.join(srcdir, m.group(1)))
            if dest in self.ap_ids:
                return 'data-go', self.ap_ids[dest]
            sid = ctx.get('sub') and ctx['sub'](dest)
            if sid:
                return 'data-go', sid
        return None

    def fragmento(self, ruta, ctx=None, raiz='auto'):
        """Lee una página antigua y devuelve (soup, nodo raíz del contenido, onload del body)."""
        self.usados.add(ruta)
        srcdir = posixpath.dirname(ruta)
        s = BeautifulSoup(leer(ruta), 'html.parser')
        for c in s.find_all(string=lambda x: isinstance(x, Comment)):
            c.extract()
        mapas = {}
        for m in s.find_all('map'):
            mapas[m.get('name') or m.get('id')] = [a.get('onclick') or a.get('onmouseover') or '' for a in m.find_all('area')]
            m.decompose()
        body = s.body or s
        onload = body.get('onload', '') if isinstance(body, Tag) else ''
        # zonas pulsables dentro de fórmulas: \htmlData{pc-map=Map, pc-area=0}{…}
        for t in body.find_all(string=re.compile(r'pc-map=')):
            def rep(m):
                areas = mapas.get(m.group(1), [])
                i = int(m.group(2))
                a = self.accion(areas[i], srcdir, ctx) if i < len(areas) else None
                if not a:
                    self.aviso(f'{ruta}: zona {m.group(1)}[{i}] sin destino conocido')
                    return ''
                return r'\htmlData{pc-%s=%s}' % ('ac' if a[0] == 'data-ac' else 'go', a[1])
            t.replace_with(re.sub(r'\\htmlData\{pc-map=([^,}]+),\s*pc-area=(\d+)\}', rep, str(t)))
        pref = re.sub(r'\W', '_', ruta)
        # manejadores antiguos
        for el in body.find_all(True):
            for at in [k for k in list(el.attrs) if k.lower().startswith('on')]:
                on = el.attrs.pop(at)
                if at.lower() != 'onclick':
                    continue
                pares = re.findall(r'(\w+)\.innerHTML\s*=\s*(\w+)\.innerHTML', on)
                if pares:      # selector: copia una celda oculta en otra visible
                    el['data-pc-swap'] = ';'.join(f'{pref}_{x}:{pref}_{y}' for x, y in pares)
                    el['class'] = (el.get('class') or []) + ['pc-swap']
                    continue
                a = self.accion(on, srcdir, ctx)
                if a:
                    el[a[0]] = a[1]
                    if el.name not in ('area',):
                        el['class'] = (el.get('class') or []) + ['enlace_texto'] if 'enlace_texto' not in (el.get('class') or []) else el['class']
                elif not re.search(r"cambiar\(|_pctop|problema\(|nuevoTitulo|cerrar|siguiente\(|verHasta\(", on):
                    self.aviso(f'{ruta}: onclick sin traducir: {on[:80]}')
            for at in ('usemap', 'name') if el.name == 'img' else ('usemap',):
                el.attrs.pop(at, None)
            if el.get('style', '').replace(' ', '').find('cursor:pointer') >= 0 and not any(k.startswith('data-') for k in el.attrs):
                el['style'] = re.sub(r'cursor\s*:\s*pointer;?', '', el['style'])
        # figuras: rutas relativas a la página nueva
        for img in body.find_all('img'):
            src = img.get('src', '')
            if 'formulas/' in src:
                self.aviso(f'{ruta}: queda una imagen de fórmula ({src})')
            if src and not re.match(r'^(https?:|data:|/)', src):
                img['src'] = posixpath.relpath(norm(posixpath.join(srcdir, src)), self.out_dir)
        for a in body.find_all('a', href=True):
            if not re.match(r'^(https?:|#|mailto:|javascript:)', a['href']):
                self.aviso(f'{ruta}: enlace interno {a["href"]}')
        # celdas de origen de los selectores: ocultas sin ocupar sitio
        origen = {y for el in body.find_all(attrs={'data-pc-swap': True})
                  for par in el['data-pc-swap'].split(';') for y in [par.split(':')[1][len(pref) + 1:]]}
        for el in body.find_all(id=True):
            if el['id'] in origen:
                el['style'] = 'display:none'
        # ids: únicos en la página nueva
        for el in body.find_all(id=True):
            el['id'] = pref + '_' + el['id']
        if raiz == 'auto':
            hijos = [c for c in body.children if isinstance(c, Tag) and c.name not in ('script', 'style')]
            if len(hijos) == 1 and hijos[0].name == 'table':
                tds = hijos[0].find_all('td', recursive=True)
                filas = hijos[0].find_all('tr', recursive=False) or hijos[0].find('tbody', recursive=False) and hijos[0].tbody.find_all('tr', recursive=False) or []
                if len(filas) == 1 and len(filas[0].find_all('td', recursive=False)) == 1:
                    return s, filas[0].td, onload
            return s, body, onload
        return s, raiz(body), onload

    @staticmethod
    def interior(nodo):
        return ''.join(str(c) for c in nodo.contents).strip()

    def pasos(self, nodo, quitar_etiqueta=True):
        """Hijos del contenido como pasos (<p>, tablas…). Quita la etiqueta «a)» inicial."""
        out = []
        for c in list(nodo.contents):
            if isinstance(c, NavigableString):
                if str(c).strip():
                    out.append(f'<p>{str(c).strip()}</p>')
                continue
            if not isinstance(c, Tag) or c.name in ('script', 'style', 'map'):
                continue
            t = texto(c)
            if quitar_etiqueta and not out and re.fullmatch(r'[a-z]\d?\s*\)', t) and not c.find('img'):
                continue
            if not t and not c.find(['img', 'table', 'input']):
                continue
            out.append(str(c))
        return out

    # ---------- aclaraciones (antes, ventanas) ----------
    def aclaracion(self, ruta):
        if ruta in self.ac_key:
            return self.ac_key[ruta]
        if not (RAIZ / ruta).exists():
            # enlaces rotos del original: probar la carpeta de arriba (ayudas) o la misma ventana en otro problema
            alt = norm(posixpath.join(posixpath.dirname(ruta), '..', '..', posixpath.basename(posixpath.dirname(ruta)), posixpath.basename(ruta)))
            m = re.match(r'(.*)/problema\d+/(.*)$', ruta)
            copias = sorted(RAIZ.glob(f'{m.group(1)}/problema*/{m.group(2)}')) if m else []
            textos = {c.read_text(encoding='utf-8', errors='replace').split('<body', 1)[-1] for c in copias}
            if (RAIZ / alt).exists():
                self.aviso(f'enlace roto {ruta}: uso {alt}')
                return self.aclaracion(alt)
            if copias and len(textos) == 1:
                otra = copias[0].relative_to(RAIZ).as_posix()
                self.aviso(f'enlace roto {ruta}: uso {otra} (mismo contenido en todos los problemas)')
                return self.aclaracion(otra)
            self.aviso(f'aclaración que no existe: {ruta}')
            k = 'ac0'
            self.ac_key[ruta] = k
            self.ac_html[k] = ('No disponible', '<p>No disponible.</p>')
            return k
        k = f'ac{len(self.ac_key) + 1}'
        self.ac_key[ruta] = k
        bruto = leer(ruta)
        s, nodo, _ = self.fragmento(ruta, ctx={})
        tit = texto(s.title) if s.title else ''
        if re.search(r'siguiente\(|verHasta\(', bruto):        # desarrollo paso a paso: celdas celda1, celda2…
            celdas = sorted(((int(m.group(1)), td) for td in s.find_all('td', id=True)
                             if (m := re.search(r'celda(\d+)$', td['id']))), key=lambda x: x[0])
            trozos = [self.interior(td) for _, td in celdas if not td.find('input') and texto(td).replace('\xa0', '').strip()]
            # lo que hay fuera de la tabla de celdas (comentarios finales) va como último paso
            tabla = celdas[0][1].find_parent('table') if celdas else None
            for c in (nodo.find_all(recursive=False) if tabla else []):
                if c is not tabla and not c.find(id=re.compile(r'celda\d+$')) and texto(c).replace('\xa0', '').strip():
                    trozos.append(str(c))
            cuerpo = '<div class="pasos" data-modo="pasos">' + ''.join(f'<div>{t}</div>' for t in trozos) + '</div>' \
                     + '<div class="ctl"><button data-cmd="sig">Siguiente paso</button> <button data-cmd="todo">Ver todo</button></div>'
            tit = tit or 'Desarrollo'
        else:
            cuerpo = '<div class="pasos">' + ''.join(self.pasos(nodo, False)) + '</div>'
        self.ac_html[k] = (tit.strip() or 'Aclaración', cuerpo)
        return k

    # ---------- problemas ----------
    def en_hojas(self):
        refs = set()
        for _, _, c in self.cfg.get('hojas', []):
            for u in re.findall(r"'([^']*problema\d+/\d+\.htm)'", leer(f'{c}/0_0.htm')):
                refs.add(norm(posixpath.join(c, posixpath.dirname(u))))
        return refs

    def orden(self, carpeta):
        """[(número, oculto)] según el índice original de la sección."""
        t = BeautifulSoup(leer(f'{carpeta}/0_a.htm'), 'html.parser')
        out = []
        for td in t.find_all('td', id=re.compile(r'^\d+$')):
            out.append((int(td['id']), 'hidden' in td.get('style', '').replace(' ', '')))
        hay = sorted(int(p.name[8:]) for p in (RAIZ / carpeta).glob('problema*') if p.name[8:].isdigit())
        refs = self.en_hojas()
        out = [(n, o and f'{carpeta}/problema{n}' not in refs) for n, o in out]
        for n in hay:
            if n not in [x for x, _ in out]:
                vis = f'{carpeta}/problema{n}' in refs
                self.aviso(f'{carpeta}/problema{n}: no está en el índice; ' + ('está en una hoja, se incluye al final' if vis else 'se incluye oculto'))
                out.append((n, not vis))
        self.usados.update({f'{carpeta}/0.htm', f'{carpeta}/0_0.htm', f'{carpeta}/0_a.htm'})
        return [(n, o) for n, o in out if n in hay]

    def problema(self, pref, carpeta, n, num, oculto):
        d = f'{carpeta}/problema{n}'
        pid = f'{pref}{n}'
        archivos = sorted(p.name for p in (RAIZ / d).glob(f'{n}_*.htm'))
        self.usados.add(f'{d}/{n}.htm')
        aps = [f for f in archivos if re.fullmatch(rf'{n}_[a-v]\d?\.htm', f)]
        for f in aps:
            self.ap_ids[f'{d}/{f}'] = pid + f[len(str(n)) + 1:-4]
        usados_sub = []
        subs = {}                                     # 'z' → id del subproblema
        for f in archivos:
            m = re.fullmatch(rf'{n}_([w-z])\.htm', f)
            if m:
                subs[m.group(1)] = f'{pid}-{m.group(1)}'
                self.usados.add(f'{d}/{f}')

        def sub(dest):
            m = re.fullmatch(rf'{re.escape(d)}/{n}_([w-z])\.htm', dest)
            if m and m.group(1) in subs:
                usados_sub.append(m.group(1))
                return subs[m.group(1)]
        # enunciado
        s, _, _ = self.fragmento(f'{d}/{n}_0.htm', ctx={'sub': sub})
        tds = s.find_all('td')
        enun = tds[0]
        examen = variante = ''
        for td in s.find_all('td', id=re.compile(r'celda\d$')):
            t = texto(td)
            if td['id'].endswith('celda1') and t and t.lower() not in ('volver',):
                examen = t
            if 'Variante' in t:
                sp = td.find(attrs={'data-go': True})
                m = re.search(r'problema(\d+)', str(BeautifulSoup(leer(f'{d}/{n}_0.htm'), 'html.parser').find('td', id='celda2')))
                if m:
                    variante = f'{pref}{m.group(1)}'
        enun_html = ''.join(self.pasos(enun, False))
        enun_html = re.sub(r'^(\s*<p[^>]*>)', r'\1<span class="num">%d</span>' % num, enun_html, count=1) \
            if enun_html.lstrip().startswith('<p') else f'<span class="num">{num}</span>' + enun_html
        meta = []
        if examen:
            meta.append(f'<span class="tag">{html.escape(examen)}</span>')
        if variante:
            meta.append(f'<a class="enlace_texto var" data-go="{variante}">Variante</a>')
        # apartados
        bloques = []
        for f in aps:
            usados_sub.clear()
            ruta = f'{d}/{f}'
            s2, nodo, onload = self.fragmento(ruta, ctx={'sub': sub})
            letra = f[len(str(n)) + 1:-4]
            ayuda = ''
            m = re.search(r"nuevoTitulo\([^,]*,\s*'([^']+)'", onload)
            if m:
                ayuda = f' <button data-ac="{self.aclaracion(norm(posixpath.join(d, m.group(1))))}" class="ayuda">Ayuda</button>'
            cab = f'<b>{letra[0]})</b>' + (f' <span class="nota">forma {letra[1:]}</span>' if letra[1:] else '') if len(aps) > 1 else ''
            html_sub = ''
            for z in usados_sub:
                _, w0, _ = self.fragmento(f'{d}/{n}_{z}0.htm', ctx={})
                _, wa, _ = self.fragmento(f'{d}/{n}_{z}a.htm', ctx={'sub': sub})
                tit = ''.join(self.pasos(w0.find('td') or w0, False))
                tit = re.sub(r'</?(p|b|font|strong)[^>]*>', ' ', tit)
                tit = re.sub(r'<span[^>]*>\s*Volver\s*</span>', '', tit)
                html_sub += (f'<details class="sub" id="{subs[z]}"><summary>{tit.strip()}</summary><div class="sol">'
                             f'<div class="pasos">{"".join(self.pasos(wa, False))}</div></div></details>')
            bloques.append(
                f'<section class="ap" id="{pid}{letra}"><div class="aph">{cab}<span class="ctl">'
                f'<button data-cmd="pasos">Paso a paso</button><button data-cmd="sig" hidden>Siguiente paso</button>'
                f'<button data-cmd="todo" hidden>Ver todo</button>{ayuda}</span></div>'
                f'<div class="pasos">{"".join(self.pasos(nodo))}</div>{html_sub}</section>')
        if not aps:
            self.aviso(f'{d}: sin apartados')
        return (f'<div class="prob" id="{pid}"{" hidden" if oculto else ""}>\n'
                f'<div class="enun">{enun_html}</div>\n'
                + (f'<p class="meta">{" ".join(meta)}</p>\n' if meta else '')
                + f'<details class="solucion"><summary>Solución</summary><div class="sol">\n'
                + '\n'.join(bloques) + '\n</div></details>\n</div>'), resumen_html(enun_html)

    # ---------- hojas de problemas sueltos ----------
    def hoja(self, hid, titulo, carpeta, resumen, secciones):
        t = leer(f'{carpeta}/0_0.htm')
        self.usados.update({f'{carpeta}/0.htm', f'{carpeta}/0_0.htm'})
        nombres = dict(re.findall(r'<option value="(hoja\d+)"[^>]*>([^<]+)</option>', t))
        out = [f'<section class="hojas" id="{hid}"><h2>{html.escape(titulo)}</h2>']
        for var, lista in re.findall(r'var (hoja\d+)\s*=\s*\[(.*?)\]', t, re.S):
            out.append(f'<h3>{html.escape(nombres.get(var, var))}</h3><ol>')
            for u in re.findall(r"'([^']+)'", lista):
                dest = norm(posixpath.join(carpeta, u))
                m = re.search(r'^(.*)/problema(\d+)/', dest)
                pref = next((p for p, _, c in secciones if m and c == m.group(1)), None)
                if not pref:
                    self.aviso(f'{carpeta}: no sé enlazar {u}')
                    continue
                pid = f'{pref}{m.group(2)}'
                out.append(f'<li><a class="enlace_texto" data-go="{pid}">{resumen.get(pid, pid)}</a></li>')
            out.append('</ol>')
        out.append('</section>')
        return '\n'.join(out)

    def generar(self):
        cfg = self.cfg
        # primero se registran todos los apartados (para enlaces entre ellos)
        for pref, _, carpeta in cfg['secciones']:
            for p in (RAIZ / carpeta).glob('problema*/*_[a-v]*.htm'):
                n = p.parent.name[8:]
                m = re.fullmatch(rf'{n}_([a-v]\d?)\.htm', p.name)
                if m:
                    self.ap_ids[f'{carpeta}/{p.parent.name}/{p.name}'] = f'{pref}{n}{m.group(1)}'
        cuerpo, resumen, chips = [], {}, []
        for pref, titulo, carpeta in cfg['secciones']:
            sid = carpeta.rsplit('/', 1)[1]
            chips.append(f'<a class="chip" data-go="{sid}">{html.escape(titulo)}</a>')
            cuerpo.append(f'<section class="seccion" id="{sid}"><h2>{html.escape(titulo)}</h2>')
            num = 0
            for n, oculto in self.orden(carpeta):
                if not oculto:
                    num += 1
                h, r = self.problema(pref, carpeta, n, num if not oculto else 0, oculto)
                resumen[f'{pref}{n}'] = r
                cuerpo.append(h)
            cuerpo.append('</section>')
        for hid, titulo, carpeta in cfg.get('hojas', []):
            chips.append(f'<a class="chip" data-go="{hid}">{html.escape(titulo)}</a>')
            cuerpo.append(self.hoja(hid, titulo, carpeta, resumen, cfg['secciones']))
        plantillas = '\n'.join(f'<template id="{k}" data-t="{html.escape(t)}">{h}</template>' for k, (t, h) in self.ac_html.items())
        prof = '../' * (cfg['salida'].count('/'))
        pagina = PAGINA.format(titulo=html.escape(cfg['titulo']), prof=prof, katex=KATEX, chips=' '.join(chips),
                               cuerpo='\n'.join(cuerpo), plantillas=plantillas, js=JS.replace('__TITULO__', cfg['titulo']))
        (RAIZ / cfg['salida']).write_text(pagina, encoding='utf-8')
        return pagina


PAGINA = """<!DOCTYPE html>
<!-- Página generada por _herramientas/unir_tema.py a partir de los problemas originales. -->
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="{prof}_pc/compat.js"></script>
<title>{titulo} · Problemas</title>
<link href="{prof}fisica/comunes/js/estilos.css" rel="stylesheet" type="text/css">
<link rel="stylesheet" href="{prof}_pc/pc.css">
<link rel="stylesheet" href="{prof}_pc/problemas.css">
<style>
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 6px}}
.chip{{border:1px solid var(--line);border-radius:999px;padding:3px 12px;font-size:14px;font-weight:600;text-decoration:none;cursor:pointer}}
.chip:hover{{background:var(--hover)}}
h2{{font-size:1.2em;color:var(--accent);border-top:2px solid var(--line);padding-top:14px;margin:22px 0 2px}}
h3{{font-size:1em;color:var(--red);margin:14px 0 4px}}
.enun p:first-child{{margin-top:0}}
.enun table{{width:auto!important}}
p.meta{{margin:.2em 0 0 1.8em}}
.var{{font-size:14px;margin-left:8px}}
.ap{{border-top:1px dashed var(--line);padding:8px 0 4px}}
.ap:first-child{{border-top:0}}
.aph{{display:flex;flex-wrap:wrap;align-items:center;gap:8px;min-height:30px}}
.aph>b{{color:var(--accent);font-size:1.05em}}
.ctl{{display:inline-flex;flex-wrap:wrap;gap:6px;margin-left:auto}}
.ctl button{{font:inherit;font-size:13px;color:var(--accent);background:var(--card);border:1px solid var(--line);border-radius:999px;padding:3px 11px;cursor:pointer}}
.ctl button:hover{{background:var(--hover)}}
.ctl button.ayuda{{color:var(--red)}}
.pasos>.oculto{{display:none}}
.pasos>.nuevo-paso{{animation:aparece .35s ease}}
@keyframes aparece{{from{{opacity:0;transform:translateY(-4px)}}to{{opacity:1}}}}
details.sub{{margin:.6em 0 .2em 0}}
.ac-box{{border:1px solid var(--accent);border-left-width:4px;border-radius:10px;background:var(--card);margin:.4em 0 .6em;padding:4px 12px 8px}}
.ac-h{{display:flex;justify-content:space-between;align-items:center;font-weight:700;color:var(--accent);font-size:14px}}
.ac-h button{{font:inherit;font-size:13px;background:none;border:0;color:var(--muted);cursor:pointer}}
.ac-box .ctl{{margin:.3em 0 0}}
[data-pc-ac],[data-pc-go]{{cursor:pointer}}
[data-pc-ac]:hover,[data-pc-go]:hover{{color:var(--red)}}
.pc-swap{{cursor:pointer;color:var(--accent);text-decoration:underline;text-decoration-color:var(--line);text-underline-offset:3px}}
.pc-swap.sel{{color:var(--red);font-weight:700}}
.hojas ol{{margin:.2em 0 .6em 1.6em;padding:0}}
.hojas li{{margin:.25em 0}}
</style>
{katex}
</head>
<body>
<div class="cab"><b>{titulo}</b><span class="nuevo">Problemas</span></div>
<nav class="chips">{chips}</nav>
{cuerpo}
{plantillas}
<script>{js}</script>
</body>
</html>
"""

JS = r"""
(function () {
  var OPT = { delimiters: [{ left: '$$', right: '$$', display: true }, { left: '$', right: '$', display: false }],
              trust: function (c) { return c.command === '\\htmlData'; }, strict: 'ignore' };
  function render(el) {
    if (!window.renderMathInElement || !el || el.dataset.r) return;
    el.dataset.r = 1; renderMathInElement(el, OPT);
  }
  // al cargar KaTeX: solo lo visible (enunciados y hojas); cada solución se dibuja al abrirla
  window.pcKatex = function () {
    document.querySelectorAll('.enun, .hojas, .cab, details[open]').forEach(render);
    irAHash(); window.pcFit && pcFit();
  };
  document.addEventListener('toggle', function (e) { if (e.target.open) { render(e.target); window.pcFit && pcFit(); } }, true);

  // desplazar la página aunque esté dentro del visor (es el visor quien hace scroll)
  function verEl(el) {
    try { var y = el.getBoundingClientRect().top, w = window; while (w.frameElement) { y += w.frameElement.getBoundingClientRect().top; w = w.parent; } w.scrollBy({ top: y - 12, behavior: 'smooth' }); }
    catch (_) { el.scrollIntoView({ behavior: 'smooth' }); }
  }
  function ir(id) {
    var el = document.getElementById(id); if (!el) return;
    el.hidden = false;
    for (var p = el; p; p = p.parentElement) if (p.tagName === 'DETAILS') { p.open = true; render(p); }
    if (el.tagName === 'DETAILS') { el.open = true; render(el); }
    setTimeout(function () { verEl(el); el.classList.add('nuevo-paso'); }, 30);
  }
  function irAHash() { var h = decodeURIComponent(location.hash.slice(1)); if (h) ir(h); }
  addEventListener('hashchange', irAHash);

  // paso a paso
  function modo(cont, m) {
    var ps = cont.querySelector(':scope > .pasos'); if (!ps) return;
    var hs = [].slice.call(ps.children), b = function (c) { return cont.querySelector(':scope > .aph [data-cmd="' + c + '"], :scope > .ctl [data-cmd="' + c + '"]'); };
    if (m === 'pasos') { hs.forEach(function (h, i) { h.classList.toggle('oculto', i > 0); }); }
    else if (m === 'sig') { var o = ps.querySelector(':scope > .oculto'); if (o) { o.classList.remove('oculto'); o.classList.add('nuevo-paso'); } }
    else { hs.forEach(function (h) { h.classList.remove('oculto'); }); }
    var quedan = !!ps.querySelector(':scope > .oculto');
    if (b('sig')) { b('sig').hidden = !quedan; }
    if (b('todo')) { b('todo').hidden = !quedan; }
    if (b('pasos')) { b('pasos').hidden = quedan; }
    window.pcFit && pcFit();
  }

  // aclaraciones (antes, ventanas): se despliegan debajo del párrafo
  function aclarar(src, k) {
    var tpl = document.getElementById(k); if (!tpl) return;
    var a = src;
    while (a.parentElement && !a.parentElement.matches('.pasos, .enun, .ac-body, .sol, .aph')) a = a.parentElement;
    if (a.parentElement && a.parentElement.matches('.aph')) a = a.parentElement;
    var sig = a.nextElementSibling;
    if (sig && sig.classList.contains('ac-box') && sig.dataset.k === k) { sig.remove(); window.pcFit && pcFit(); return; }
    var box = document.createElement('div'); box.className = 'ac-box'; box.dataset.k = k;
    box.innerHTML = '<div class="ac-h"><span></span><button aria-label="Cerrar">✕</button></div><div class="ac-body"></div>';
    box.querySelector('span').textContent = tpl.dataset.t;
    box.querySelector('.ac-body').appendChild(tpl.content.cloneNode(true));
    a.after(box); render(box);
    var ps = box.querySelector('.ac-body > .pasos[data-modo="pasos"]'); if (ps) modo(box.querySelector('.ac-body'), 'pasos');
    window.pcFit && pcFit();
  }

  document.addEventListener('click', function (e) {
    var sw = e.target.closest('[data-pc-swap]');
    if (sw) {
      sw.dataset.pcSwap.split(';').forEach(function (par) {
        var p = par.split(':'), dst = document.getElementById(p[0]), src = document.getElementById(p[1]);
        if (dst && src) { dst.innerHTML = src.innerHTML; dst.style.visibility = 'visible'; }
      });
      var grupo = sw.closest('table') || document;
      grupo.querySelectorAll('.pc-swap.sel').forEach(function (x) { x.classList.remove('sel'); });
      sw.classList.add('sel'); window.pcFit && pcFit(); return;
    }
    var t = e.target.closest('[data-cmd], [data-ac], [data-pc-ac], [data-go], [data-pc-go], .ac-h button');
    if (!t) return;
    if (t.matches('.ac-h button')) { t.closest('.ac-box').remove(); window.pcFit && pcFit(); return; }
    e.preventDefault();
    if (t.dataset.cmd) return modo(t.closest('.ap, .ac-body'), t.dataset.cmd);
    if (t.dataset.ac || t.dataset.pcAc) return aclarar(t, t.dataset.ac || t.dataset.pcAc);
    var id = t.dataset.go || t.dataset.pcGo;
    if (history.replaceState) history.replaceState(null, '', '#' + id);
    ir(id);
  });
  try { _pctop.document.title = '__TITULO__'; _pctop.archivoAyuda = null; } catch (e) {}
})();
"""

if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in TEMAS:
        sys.exit('Uso: unir_tema.py <tema> [--borrar]   temas: ' + ', '.join(TEMAS))
    g = Generador(TEMAS[sys.argv[1]])
    g.generar()
    print(f"Generada {g.cfg['salida']}: {len(g.ac_html)} aclaraciones, {len(g.usados)} archivos antiguos usados")
    for a in g.avisos:
        print('AVISO', a)
    lista = Path('/tmp') / f'usados-{sys.argv[1]}.txt'
    lista.write_text('\n'.join(sorted(g.usados)) + '\n', encoding='utf-8')
    if '--borrar' in sys.argv:
        for u in g.usados:
            if '/ayuda/' in u or '/buscarAyudas/' in u:
                continue
            (RAIZ / u).unlink(missing_ok=True)
        print('Borrados los archivos antiguos (salvo ayudas)')
