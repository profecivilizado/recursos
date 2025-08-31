// Tema oscuro con persistencia
(function themeInit(){
  const key = "pc-theme";
  const root = document.documentElement;
  const saved = localStorage.getItem(key);
  if (saved === "dark") root.setAttribute("data-theme", "dark");

  const btn = document.getElementById("themeToggle");
  if (btn){
    btn.addEventListener("click", () => {
      const isDark = root.getAttribute("data-theme") === "dark";
      if (isDark) root.removeAttribute("data-theme");
      else root.setAttribute("data-theme", "dark");
      localStorage.setItem(key, isDark ? "light" : "dark");
    });
  }
})();

// Año dinámico
(function yearInit(){
  const y = document.getElementById("y");
  if (y) y.textContent = new Date().getFullYear();
})();
