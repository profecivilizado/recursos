/* Capa de compatibilidad para el repositorio de ejercicios (hecho para Internet Explorer y frames).
   - _pctop: la ventana del visor (lo que antes era «top»), aunque el visor esté incrustado en otra web.
   - window.open → ventana modal del visor.  F1 → ayuda.
   - Cada página ajusta la altura de su iframe a su contenido. */
(function () {
  var w = window;
  try { while (!w.__pcShell && w.parent !== w) w = w.parent; } catch (e) {}
  window._pctop = w.__pcShell ? w : window.top;
  window._pcabs = function (u) { return u ? new URL(u, location.href).href : u; };
  // tema claro / oscuro (el mismo que la web)
  var r = document.documentElement;
  function theme() { var t = null; try { t = localStorage.getItem('pc-theme'); } catch (e) {} if (t === 'dark' || t === 'light') r.setAttribute('data-theme', t); else r.removeAttribute('data-theme'); }
  theme(); addEventListener('storage', function (e) { if (e.key === 'pc-theme') theme(); });
  // ventanas emergentes → modal del visor
  var realOpen = window.open;
  window.open = function (url) {
    if (_pctop.pcModal) return _pctop.pcModal(_pcabs(url));
    return realOpen.apply(window, arguments);
  };
  if (window.frameElement && window.frameElement.classList.contains('pc-modal-frame')) window.close = function () { _pctop.pcModalClose && _pctop.pcModalClose(); };
  // dentro de la página «Teoría»: el título azul de la ayuda ya está como subtítulo
  if (window.frameElement && window.frameElement.classList.contains('pc-teoria')) addEventListener('DOMContentLoaded', function () {
    var f = document.querySelector('p b font[color="#0000FF"], p b font[color="#0000ff"]'); if (f) f.closest('p').style.display = 'none';
    // tablas ocultas que solo sirven de plantilla (su contenido se copia con innerHTML): que no ocupen hueco
    document.querySelectorAll('table[style*="visibility:hidden"], table[style*="visibility: hidden"]').forEach(function (t) { t.style.display = 'none'; });
  });
  // altura automática
  var pending = 0;
  function fit() {
    var fe = window.frameElement; if (!fe || !document.body) return;
    var cs = getComputedStyle(document.body), h = Math.ceil(document.body.getBoundingClientRect().height + parseFloat(cs.marginTop) + parseFloat(cs.marginBottom)) + 2;
    var all = document.body.querySelectorAll('*'); for (var k = 0; k < all.length && k < 4000; k++) { var b = all[k].getBoundingClientRect(); if (b.bottom + scrollY > h) h = Math.ceil(b.bottom + scrollY) + 2; }
    if (document.body.classList.contains('pc-fs')) { h = 0; var fr = document.querySelectorAll('iframe.pc-frame:not(.pc-hide)'); for (var i = 0; i < fr.length; i++) h += fr[i].offsetHeight + 12; }
    if (Math.abs(fe.offsetHeight - h) > 2) fe.style.height = h + 'px';
    try { if (parent !== window && parent.pcFit) parent.pcFit(); } catch (e) {}
  }
  window.pcFit = function () { if (!pending) pending = requestAnimationFrame(function () { pending = 0; fit(); }); };
  addEventListener('load', function () {
    fit();
    try { new ResizeObserver(window.pcFit).observe(document.body); } catch (e) {}
    setTimeout(fit, 250); setTimeout(fit, 1200);
    document.querySelectorAll('img').forEach(function (im) { if (!im.complete) im.addEventListener('load', window.pcFit); });
    if (_pctop.pcPageLoaded) try { _pctop.pcPageLoaded(window); } catch (e) {}
  });
  // Zonas pulsables dentro de fórmulas KaTeX (sustituyen a los <map>/<area> de las antiguas imágenes)
  function pcArea(el) { var m = document.querySelector('map[name="' + el.getAttribute('data-pc-map') + '"]'); return m && m.areas[+el.getAttribute('data-pc-area')]; }
  document.addEventListener('click', function (e) { var el = e.target.closest && e.target.closest('[data-pc-area]'), a = el && pcArea(el); if (a && a.onclick) a.onclick.call(a, e); });
  document.addEventListener('mouseover', function (e) { var el = e.target.closest && e.target.closest('[data-pc-area]'), a = el && pcArea(el); if (a && !el.title) el.title = a.title || ''; });
  addEventListener('keydown', function (e) { if (e.key === 'F1') { e.preventDefault(); _pctop.pcHelp && _pctop.pcHelp(); } });
})();
