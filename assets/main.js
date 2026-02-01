console.log("main.js cargado");

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


/* ============================
   FACTORIZADOR DE POLINOMIOS
   ============================ */
  
  document.addEventListener("DOMContentLoaded", () => {
  
    const btnCrear = document.getElementById("btn-crear-pol");
    const btnFact  = document.getElementById("btn-factorizar-pol");
  
    if (!btnCrear || !btnFact) return;
  
    const superIndices = {"0":"⁰","1":"¹","2":"²","3":"³","4":"⁴","5":"⁵","6":"⁶","7":"⁷","8":"⁸","9":"⁹"};
    const expSuper = n => n.toString().split("").map(c => superIndices[c]).join("");
    const gcd = (a,b) => b === 0 ? a : gcd(b, a % b);
  
    function mostrarPolinomio(coefs){
      let grado = coefs.length - 1;
      let partes = [];
    
      coefs.forEach((c,i)=>{
        if(c === 0) return;
        let exp = grado - i;
        let signo = c > 0 && partes.length ? " + " : c < 0 ? " - " : "";
        let val = Math.abs(c);
        let coef = (val === 1 && exp > 0) ? "" : val;
    
        let term;
        if(exp > 1) term = `${coef}x${expSuper(exp)}`;
        else if(exp === 1) term = `${coef}x`;
        else term = `${coef}`;
    
        partes.push(signo + term);
      });
    
      return partes.length ? partes.join("") : "0";
    }
    
    function limpiarCoeficientes(coefs) {
      while (coefs.length > 1 && coefs[0] === 0) {
        coefs.shift();
      }
      return coefs;
    }
  
    btnCrear.addEventListener("click", () => {
      const grado = parseInt(document.getElementById("grado-pol").value);
      const cont  = document.getElementById("coeficientes-pol");
      const bloque = document.getElementById("bloque-factorizar-pol");
  
      cont.innerHTML = "";
      bloque.classList.add("hidden");
  
      if (isNaN(grado) || grado < 1) return;
  
      for (let i = grado; i >= 0; i--) {
        cont.innerHTML += `
          <div class="form-row">
            <label>Coef. x${expSuper(i)}</label>
            <input class="coef-pol" type="number" value="0">
          </div>`;
      }
  
      bloque.classList.remove("hidden");
    });
  
    btnFact.addEventListener("click", () => {
      const salida = document.getElementById("salida-pol");
      salida.textContent = "";
      salida.classList.remove("hidden");
  
      let coefs = [...document.querySelectorAll(".coef-pol")]
        .map(i => {
          const v = parseInt(i.value);
          return isNaN(v) ? 0 : v;
        });
      
      coefs = limpiarCoeficientes(coefs);

  
      let pasos = [];
      pasos.push("Polinomio leído:");
      pasos.push(mostrarPolinomio(coefs));
      pasos.push("");
  
      // 1) Factor numérico
      let m = Math.abs(coefs[0]);
      for (let i = 1; i < coefs.length; i++) {
        m = gcd(m, Math.abs(coefs[i]));
      }
      if (m === 1) m = null;
      
      // 2) Potencia común de x (ceros finales)
      let k = 0;
      while (coefs.length > k + 1 && coefs[coefs.length - 1 - k] === 0) {
        k++;
      }
      
      // 3) Si no hay factor común
      if (!m && k === 0) {
        pasos.push("No se puede extraer factor común.");
        salida.textContent = pasos.join("\n");
        return;
      }
      
      // 4) Nuevo polinomio
      let nuevo = [...coefs];
      if (m) nuevo = nuevo.map(c => c / m);
      if (k) nuevo = nuevo.slice(0, -k);
      
      // 5) Construir factor común
      let fc = "";
      if (m) fc += m;
      if (k === 1) fc += "x";
      else if (k > 1) fc += `x${expSuper(k)}`;
      
      pasos.push(`Factor común: ${fc}`);
      pasos.push(`${fc}·(${mostrarPolinomio(nuevo)})`);

  
      salida.textContent = pasos.join("\n");
    });
  
  });








