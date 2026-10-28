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

// Año dinámico en el pie
(function yearInit(){
  const y = document.getElementById("y");
  if (y) y.textContent = new Date().getFullYear();
})();
