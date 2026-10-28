// Motor Python del conversor (Pyodide), en un hilo aparte para no congelar la página.
// Carga conversor.py a través de puente.py y ejecuta sus acciones.
const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/";
importScripts(PYODIDE + "pyodide.js");

let py = null;
let readyPromise = null;

async function init(base) {
  py = await loadPyodide({ indexURL: PYODIDE });
  // Las dependencias se cargan desde Pyodide (rápido); de PyPI solo los tres paquetes puros
  await py.loadPackage(["micropip", "Pillow", "lxml", "cryptography", "typing-extensions", "charset-normalizer"]);
  await py.runPythonAsync(`
import micropip
await micropip.install(["python-docx==1.2.0", "pdfminer.six==20260107", "pdfplumber==0.11.10"], deps=False)
`);
  py.FS.mkdirTree("/conversor");
  py.FS.mkdirTree("/work");
  for (const name of ["conversor.py", "puente.py"]) {
    const r = await fetch(base + name + "?v=3", { cache: "no-cache" });
    if (!r.ok) throw new Error("No se pudo descargar " + name);
    py.FS.writeFile("/conversor/" + name, new Uint8Array(await r.arrayBuffer()));
  }
  await py.runPythonAsync(`
import sys
sys.path.insert(0, "/conversor")
import puente
`);
}

function cleanWork() {
  for (const f of py.FS.readdir("/work")) {
    if (f === "." || f === "..") continue;
    try { py.FS.unlink("/work/" + f); } catch (e) { /* carpeta: se ignora */ }
  }
}

self.onmessage = async (ev) => {
  const { id, cmd } = ev.data;
  try {
    if (cmd === "init") {
      readyPromise = readyPromise || init(ev.data.base);
      await readyPromise;
      self.postMessage({ id, ok: true });
      return;
    }
    await readyPromise;
    if (cmd === "run") {
      const { name, data, label, func, value, pages } = ev.data;
      cleanWork();
      const path = "/work/" + name;
      py.FS.writeFile(path, new Uint8Array(data));
      const puente = py.pyimport("puente");
      puente.clear_pages();
      if (pages) pages.forEach((png, i) => puente.set_page_png(i + 1, new Uint8Array(png)));
      const out = func
        ? puente.run_func(func, path, value ?? null)
        : puente.run(path, label, value ?? null);
      const bytes = py.FS.readFile(out);
      puente.clear_pages();
      cleanWork();
      self.postMessage({ id, ok: true, name: out.split("/").pop(), data: bytes.buffer }, [bytes.buffer]);
    }
  } catch (err) {
    let msg = String(err && err.message || err);
    // De un error de Python, quedarse con la última línea (la que explica el problema)
    const lines = msg.trim().split("\n");
    if (lines.length > 1 && /Error|Exception/.test(lines[lines.length - 1])) {
      msg = lines[lines.length - 1].replace(/^\w+(Error|Exception):\s*/, "");
    }
    self.postMessage({ id, ok: false, error: msg });
  }
};
