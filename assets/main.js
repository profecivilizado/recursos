// Tema claro/oscuro con el botón 🌓 (recuerda la elección)
(function themeInit(){
  const key = "pc-theme";
  const root = document.documentElement;
  let saved = null;
  try { saved = localStorage.getItem(key); } catch (e) {}
  if (saved === "dark" || saved === "light") root.setAttribute("data-theme", saved);

  const btn = document.getElementById("themeToggle");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const current = root.getAttribute("data-theme") ||
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem(key, next); } catch (e) {}
  });
})();

// Simuladores incrustados: la altura del iframe se ajusta a su contenido
(function autoHeight(){
  document.querySelectorAll("iframe[data-autoheight]").forEach((frame) => {
    const fit = () => {
      try {
        const body = frame.contentDocument && frame.contentDocument.body;
        if (!body) return;
        const h = Math.ceil(body.getBoundingClientRect().height);
        if (h > 0) frame.style.height = h + "px";
      } catch (e) {}
    };
    frame.addEventListener("load", () => {
      fit();
      try { new ResizeObserver(fit).observe(frame.contentDocument.body); } catch (e) {}
    });
  });
})();

// Año dinámico en el pie
(function yearInit(){
  const y = document.getElementById("y");
  if (y) y.textContent = new Date().getFullYear();
})();
