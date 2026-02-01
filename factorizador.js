const btnCrear = document.getElementById("crear");
const btnFact  = document.getElementById("factorizar");

const contCoef = document.getElementById("coeficientes");
const bloqueFact = document.getElementById("bloqueFactorizar");
const salida = document.getElementById("salida");

const superIdx = ["⁰","¹","²","³","⁴","⁵","⁶","⁷","⁸","⁹"];
const exp = n => n.toString().split("").map(d => superIdx[d]).join("");

const gcd = (a,b) => b === 0 ? a : gcd(b, a % b);

function limpiar(coefs){
  while (coefs.length > 1 && coefs[0] === 0) coefs.shift();
  return coefs;
}

function mostrar(coefs){
  const g = coefs.length - 1;
  let res = [];
  coefs.forEach((c,i)=>{
    if (c === 0) return;
    const e = g - i;
    const signo = c > 0 && res.length ? " + " : c < 0 ? " - " : "";
    const v = Math.abs(c);
    const coef = (v === 1 && e > 0) ? "" : v;
    let t = "";
    if (e > 1) t = `${coef}x${exp(e)}`;
    else if (e === 1) t = `${coef}x`;
    else t = `${coef}`;
    res.push(signo + t);
  });
  return res.length ? res.join("") : "0";
}

btnCrear.onclick = () => {
  const grado = parseInt(document.getElementById("grado").value);
  contCoef.innerHTML = "";
  bloqueFact.classList.add("hidden");
  salida.classList.add("hidden");

  if (isNaN(grado) || grado < 1) return;

  for (let i = grado; i >= 0; i--) {
    contCoef.innerHTML += `
      <div class="fila">
        Coef. x${exp(i)}:
        <input class="coef" type="number" value="0">
      </div>`;
  }
  bloqueFact.classList.remove("hidden");
};

btnFact.onclick = () => {
  let coefs = [...document.querySelectorAll(".coef")]
    .map(i => parseInt(i.value) || 0);

  coefs = limpiar(coefs);

  let pasos = [];
  pasos.push("Polinomio:");
  pasos.push(mostrar(coefs));
  pasos.push("");

  let m = Math.abs(coefs[0]);
  for (let i = 1; i < coefs.length; i++) {
    m = gcd(m, Math.abs(coefs[i]));
  }
  if (m === 1) m = null;

  let k = 0;
  while (coefs.length > k + 1 && coefs[coefs.length - 1 - k] === 0) k++;

  if (!m && k === 0) {
    pasos.push("No se puede extraer factor común.");
    salida.textContent = pasos.join("\n");
    salida.classList.remove("hidden");
    return;
  }

  let nuevo = [...coefs];
  if (m) nuevo = nuevo.map(c => c / m);
  if (k) nuevo = nuevo.slice(0, -k);

  let fc = "";
  if (m) fc += m;
  if (k === 1) fc += "x";
  else if (k > 1) fc += `x${exp(k)}`;

  pasos.push(`Factor común: ${fc}`);
  pasos.push(`${fc}·(${mostrar(nuevo)})`);

  salida.textContent = pasos.join("\n");
  salida.classList.remove("hidden");
};
