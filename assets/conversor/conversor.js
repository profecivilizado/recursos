// Conversor de archivos de Profe Civilizado (versión web de conversor.py).
// Todo se procesa en el navegador: los archivos no se suben a ningún servidor.
//
// Motores (cada uno se carga solo cuando hace falta):
//   - Canvas del navegador: imágenes (instantáneo)
//   - pdf.js y pdf-lib (en assets/vendor): PDF
//   - heic2any: fotos HEIC del iPhone
//   - Pyodide + conversor.py: PDF → Word, Word/TXT, TIFF, ICO, compresión PNG
//   - ffmpeg.wasm: vídeo y audio

const BASE = new URL("./", import.meta.url).href;
const VENDOR = new URL("../vendor/", import.meta.url).href;

const IMG = [".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tiff", ".tif", ".avif", ".ico", ".bmp"];
const VID = [".mp4", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".gif"];
const AUD = [".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aiff", ".wma"];
const CANVAS_OUT = { ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp" };

const $ = (s) => document.querySelector(s);

// ------------------------------------------------------------------ utilidades
function splitName(name) {
  const i = name.lastIndexOf(".");
  return i > 0 ? [name.slice(0, i), name.slice(i).toLowerCase()] : [name, ""];
}
function outName(name, suffix, ext) {
  const [stem] = splitName(name);
  return `${stem}${suffix}${ext}`;
}
function humanSize(n) {
  for (const u of ["B", "KB", "MB", "GB"]) {
    if (n < 1024 || u === "GB") return u === "B" ? `${n.toFixed(0)} ${u}` : `${n.toFixed(1).replace(".", ",")} ${u}`;
    n /= 1024;
  }
}
function loadScript(src) {
  return new Promise((ok, ko) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = ok;
    s.onerror = () => ko(new Error("No se pudo cargar " + src.split("/").pop() + ". Revisa tu conexión."));
    document.head.appendChild(s);
  });
}
function canvasToBlob(canvas, type, quality) {
  return new Promise((ok) => canvas.toBlob(ok, type, quality));
}

// ZIP sencillo (sin compresión) para resultados con varios archivos
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();
function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
async function makeZip(files) { // [{name, data:Uint8Array|Blob}]
  const enc = new TextEncoder();
  const parts = [], central = [];
  let offset = 0;
  for (const f of files) {
    const data = f.data instanceof Blob ? new Uint8Array(await f.data.arrayBuffer()) : f.data;
    const name = enc.encode(f.name);
    const crc = crc32(data);
    const h = new DataView(new ArrayBuffer(30));
    h.setUint32(0, 0x04034b50, true); h.setUint16(4, 20, true); h.setUint16(6, 0x0800, true);
    h.setUint32(14, crc, true); h.setUint32(18, data.length, true); h.setUint32(22, data.length, true);
    h.setUint16(26, name.length, true);
    parts.push(h.buffer, name, data);
    const c = new DataView(new ArrayBuffer(46));
    c.setUint32(0, 0x02014b50, true); c.setUint16(4, 20, true); c.setUint16(6, 20, true); c.setUint16(8, 0x0800, true);
    c.setUint32(16, crc, true); c.setUint32(20, data.length, true); c.setUint32(24, data.length, true);
    c.setUint16(28, name.length, true); c.setUint32(42, offset, true);
    central.push(c.buffer, name);
    offset += 30 + name.length + data.length;
  }
  const size = central.reduce((s, p) => s + (p.byteLength ?? p.length), 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true); end.setUint16(10, files.length, true);
  end.setUint32(12, size, true); end.setUint32(16, offset, true);
  return new Blob([...parts, ...central, end.buffer], { type: "application/zip" });
}

// "1-3, 5, 8-" -> [1,2,3,5,8,...,total]  (igual que parse_pages de conversor.py)
function parsePages(text, total) {
  const pages = [];
  for (const part of text.replace(/\s/g, "").split(",")) {
    if (!part) continue;
    if (part.includes("-")) {
      const [a, b] = part.split("-", 2);
      const from = a ? parseInt(a, 10) : 1, to = b ? parseInt(b, 10) : total;
      for (let p = from; p <= to; p++) pages.push(p);
    } else pages.push(parseInt(part, 10));
  }
  if (!pages.length || pages.some((p) => isNaN(p) || p < 1 || p > total)) {
    throw new Error(`Páginas fuera de rango (el PDF tiene ${total}).`);
  }
  return pages;
}

// ------------------------------------------------------------------ motores
let pdfjsPromise = null;
function pdfjs() {
  pdfjsPromise = pdfjsPromise || import(VENDOR + "pdf.min.mjs").then((lib) => {
    lib.GlobalWorkerOptions.workerSrc = VENDOR + "pdf.worker.min.mjs";
    return lib;
  });
  return pdfjsPromise;
}
let pdfLibPromise = null;
function pdfLib() {
  pdfLibPromise = pdfLibPromise || loadScript(VENDOR + "pdf-lib.min.js").then(() => window.PDFLib);
  return pdfLibPromise;
}
let heicPromise = null;
function heic() {
  heicPromise = heicPromise || loadScript("https://cdn.jsdelivr.net/npm/heic2any@0.0.4/dist/heic2any.min.js").then(() => window.heic2any);
  return heicPromise;
}

// Trabajadores (Python y FFmpeg) con mensajes numerados
function makeWorker(url, onEvent) {
  const w = new Worker(url);
  const pending = new Map();
  let seq = 0;
  w.onmessage = (ev) => {
    const m = ev.data;
    if (m.id === undefined) { onEvent && onEvent(m); return; }
    const p = pending.get(m.id);
    pending.delete(m.id);
    m.ok ? p.ok(m) : p.ko(new Error(m.error));
  };
  return {
    call(msg, transfer = []) {
      const id = ++seq;
      return new Promise((ok, ko) => { pending.set(id, { ok, ko }); w.postMessage({ id, ...msg }, transfer); });
    },
  };
}

const engines = {
  py: { state: "idle", worker: null, ready: null },
  ff: { state: "idle", worker: null, ready: null },
};

function pyReady() {
  const e = engines.py;
  if (!e.ready) {
    e.worker = makeWorker(BASE + "py-worker.js?v=3");
    e.state = "loading";
    renderEngines();
    e.ready = e.worker.call({ cmd: "init", base: BASE })
      .then(() => { e.state = "ready"; renderEngines(); })
      .catch((err) => { e.state = "error"; e.ready = null; renderEngines(); throw err; });
  }
  return e.ready;
}
function ffReady() {
  const e = engines.ff;
  if (!e.ready) {
    e.worker = makeWorker(BASE + "ff-worker.js?v=3", (m) => {
      if (m.type === "download") setProgress(Math.min(1, m.bytes / 32e6), `Descargando el motor de vídeo (solo la primera vez)… ${Math.round(m.bytes / 1e6)} de 32 MB`);
      if (m.type === "progress") setProgress(Math.max(0, Math.min(1, m.progress)), `Procesando… ${Math.round(Math.max(0, Math.min(1, m.progress)) * 100)} %`);
    });
    e.state = "loading";
    renderEngines();
    e.ready = e.worker.call({ cmd: "init" })
      .then(() => { e.state = "ready"; renderEngines(); })
      .catch((err) => { e.state = "error"; e.ready = null; renderEngines(); throw err; });
  }
  return e.ready;
}

async function runPython(file, { label, func, value, pages, stemName }) {
  if (engines.py.state !== "ready") {
    setProgress(null);
    status("");
    $("#cv-wait").hidden = false;
    try { await pyReady(); } finally { $("#cv-wait").hidden = true; }
  }
  status("Procesando con Python…");
  const data = await file.arrayBuffer();
  const transfer = [data, ...(pages || [])];
  const r = await engines.py.worker.call({ cmd: "run", name: stemName || file.name, data, label, func, value, pages }, transfer);
  return { blob: new Blob([r.data]), name: r.name };
}
async function runFFmpeg(file, outExt, args) {
  status(engines.ff.state === "ready" ? "Procesando…" : "Descargando el motor de vídeo (solo la primera vez)…");
  await ffReady();
  setProgress(0, "Procesando…");
  const [, ext] = splitName(file.name);
  const data = await file.arrayBuffer();
  const r = await engines.ff.worker.call({ cmd: "exec", input: "entrada" + ext, data, output: "salida" + outExt, args }, [data]);
  return new Blob([r.data]);
}

// ------------------------------------------------------------------ imágenes
async function decodeImage(file) {
  const [, ext] = splitName(file.name);
  let blob = file;
  if (ext === ".heic" || ext === ".heif") {
    status("Leyendo la foto HEIC…");
    const h = await heic();
    const res = await h({ blob: file, toType: "image/png" });
    blob = Array.isArray(res) ? res[0] : res;
  }
  try {
    return await createImageBitmap(blob, { imageOrientation: "from-image" });
  } catch (e) {
    // El navegador no sabe leerlo (p. ej. TIFF en Chrome): lo abre Pillow
    const r = await runPython(file, { func: "__to_png__" });
    return await createImageBitmap(r.blob);
  }
}
// Pasa la imagen a PNG para que la lea Python (necesario con HEIC)
async function asPillowFile(file) {
  const [stem, ext] = splitName(file.name);
  if (ext !== ".heic" && ext !== ".heif") return file;
  const bmp = await decodeImage(file);
  const c = draw(bmp, bmp.width, bmp.height);
  return new File([await canvasToBlob(c, "image/png")], stem + ".png");
}
function draw(bmp, w, h, box, white) {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  const ctx = c.getContext("2d");
  if (white) { ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, w, h); }
  ctx.imageSmoothingQuality = "high";
  if (box) ctx.drawImage(bmp, box[0], box[1], box[2], box[3], 0, 0, w, h);
  else ctx.drawImage(bmp, 0, 0, w, h);
  return c;
}
// Codifica con el navegador; si no admite el formato (WebP en Safari antiguo…), lo hace Pillow
async function encodeOrPython(canvas, mime, quality, file, pyLabel, name) {
  const blob = await canvasToBlob(canvas, mime, quality);
  if (blob && blob.type === mime) return { blob, name };
  return runPython(await asPillowFile(file), { label: pyLabel });
}
async function imageToPdf(bitmaps) {
  const { PDFDocument } = await pdfLib();
  const doc = await PDFDocument.create();
  for (const bmp of bitmaps) {
    const c = draw(bmp, bmp.width, bmp.height, null, true);
    const jpg = await (await canvasToBlob(c, "image/jpeg", 0.92)).arrayBuffer();
    const img = await doc.embedJpg(jpg);
    const page = doc.addPage([bmp.width, bmp.height]);
    page.drawImage(img, { x: 0, y: 0, width: bmp.width, height: bmp.height });
  }
  return new Blob([await doc.save()], { type: "application/pdf" });
}
function sameOrPng(ext) {
  return CANVAS_OUT[ext] ? [ext === ".jpeg" ? ".jpg" : ext, CANVAS_OUT[ext]] : [".png", "image/png"];
}

// ------------------------------------------------------------------ PDF
async function openPdfJs(file) {
  const lib = await pdfjs();
  return lib.getDocument({ data: new Uint8Array(await file.arrayBuffer()) }).promise;
}
function closePdf(doc) {
  try { (doc.loadingTask && doc.loadingTask.destroy) ? doc.loadingTask.destroy() : doc.destroy && doc.destroy(); } catch (e) { /* nada */ }
}
async function renderPage(doc, n, dpi, mime, quality) {
  const page = await doc.getPage(n);
  const vp = page.getViewport({ scale: dpi / 72 });
  const c = document.createElement("canvas");
  c.width = Math.round(vp.width); c.height = Math.round(vp.height);
  const ctx = c.getContext("2d");
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, c.width, c.height);
  await page.render({ canvasContext: ctx, viewport: vp }).promise;
  const blob = await canvasToBlob(c, mime, quality);
  page.cleanup();
  return { blob, width: page.view[2] - page.view[0], height: page.view[3] - page.view[1] };
}
async function loadPdfLib(file) {
  const { PDFDocument } = await pdfLib();
  return PDFDocument.load(await file.arrayBuffer(), { ignoreEncryption: true });
}
const pdfBlob = (bytes) => new Blob([bytes], { type: "application/pdf" });

// ------------------------------------------------------------------ Word → PDF
let docxPromise = null;
function docxPreview() {
  docxPromise = docxPromise || loadScript("https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js")
    .then(() => loadScript("https://cdn.jsdelivr.net/npm/docx-preview@0.3.5/dist/docx-preview.min.js"))
    .then(() => window.docx);
  return docxPromise;
}
async function docxToPdf(file) {
  status("Preparando el documento…");
  const lib = await docxPreview();
  const frame = document.createElement("iframe");
  frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden";
  document.body.appendChild(frame);
  const doc = frame.contentDocument;
  doc.open();
  doc.write(`<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><title>${splitName(file.name)[0]}</title>
    <style>@page{margin:0}html,body{margin:0;background:#fff}.docx-wrapper{padding:0!important;background:#fff!important}
    .docx-wrapper>section.docx{margin:0!important;box-shadow:none!important;page-break-after:always}</style></head><body></body></html>`);
  doc.close();
  await lib.renderAsync(await file.arrayBuffer(), doc.body, doc.head, { inWrapper: true, breakPages: true, ignoreLastRenderedPageBreak: true });
  await new Promise((r) => setTimeout(r, 300));
  frame.contentWindow.focus();
  frame.contentWindow.print();
  setTimeout(() => frame.remove(), 60000);
  return { printed: true };
}

// ------------------------------------------------------------------ acciones
// Igual que actions_for() de conversor.py. Cada acción: {label, run, ask?, engine}
function actionsFor(file) {
  const [, ext] = splitName(file.name);
  const acts = [];
  const name = file.name;

  if (IMG.includes(ext)) {
    const same = { ".jpeg": "JPG", ".jpg": "JPG", ".tif": "TIFF", ".heif": "HEIC" }[ext] || ext.slice(1).toUpperCase();
    const canvasFmt = { JPG: ["image/jpeg", ".jpg"], PNG: ["image/png", ".png"], WEBP: ["image/webp", ".webp"] };
    for (const f of ["JPG", "PNG", "WEBP", "PDF", "ICO", "TIFF"]) {
      if (f === same) continue;
      const label = `Convertir a ${f}`;
      if (canvasFmt[f]) {
        acts.push({ label, run: async () => {
          const bmp = await decodeImage(file);
          const [mime, e] = canvasFmt[f];
          return encodeOrPython(draw(bmp, bmp.width, bmp.height, null, f === "JPG"), mime, 0.92, file, label, outName(name, "", e));
        } });
      } else if (f === "PDF") {
        acts.push({ label, run: async () => ({ blob: await imageToPdf([await decodeImage(file)]), name: outName(name, "", ".pdf") }) });
      } else {
        acts.push({ label, engine: "py", run: async () => runPython(await asPillowFile(file), { label }) });
      }
    }
    for (const strong of [false, true]) {
      const label = strong ? "Comprimir (fuerte)" : "Comprimir (equilibrada)";
      acts.push({ label, engine: ext === ".png" ? "py" : null, run: async () => {
        if (ext === ".png") return runPython(file, { label });
        const bmp = await decodeImage(file);
        const q = strong ? 0.5 : 0.75;
        if (ext === ".webp") return encodeOrPython(draw(bmp, bmp.width, bmp.height), "image/webp", q, file, label, outName(name, "_comprimido", ".webp"));
        return { blob: await canvasToBlob(draw(bmp, bmp.width, bmp.height, null, true), "image/jpeg", q), name: outName(name, "_comprimido", ".jpg") };
      } });
    }
    acts.push({ label: "Redimensionar…", ask: { kind: "int", text: "Ancho en píxeles", def: 1280, min: 16, max: 20000 },
      run: async (width) => {
        const bmp = await decodeImage(file);
        const h = Math.max(1, Math.round(bmp.height * width / bmp.width));
        const [e, mime] = sameOrPng(ext);
        const c = draw(bmp, width, h, null, mime === "image/jpeg");
        return { blob: await canvasToBlob(c, mime, 0.92), name: outName(name, `_${width}x${h}`, e) };
      } });
    acts.push({ label: "Recortar (centrado)…", ask: { kind: "item", text: "Proporción", items: ["1:1 · cuadrado", "16:9 · panorámico", "4:3", "3:4", "9:16 · vertical"] },
      run: async (value) => {
        const [wr, hr] = value.split(" ")[0].split(":").map(Number);
        const bmp = await decodeImage(file);
        const w = bmp.width, h = bmp.height, target = wr / hr;
        let box;
        if (w / h > target) { const nw = Math.floor(h * target); box = [Math.floor((w - nw) / 2), 0, nw, h]; }
        else { const nh = Math.floor(w / target); box = [0, Math.floor((h - nh) / 2), w, nh]; }
        const [e, mime] = sameOrPng(ext);
        const c = draw(bmp, box[2], box[3], box, mime === "image/jpeg");
        return { blob: await canvasToBlob(c, mime, 0.92), name: outName(name, "_recortado", e) };
      } });
    acts.push({ label: "Quitar metadatos", run: async () => {
      const bmp = await decodeImage(file);
      const [e, mime] = sameOrPng(ext);
      const c = draw(bmp, bmp.width, bmp.height, null, mime === "image/jpeg");
      return { blob: await canvasToBlob(c, mime, 0.95), name: outName(name, "_sin_metadatos", e) };
    } });
    acts.push({ label: "Unir con otras imágenes en un PDF…", ask: { kind: "files", text: "Elige las imágenes que quieres añadir", accept: "image/*,.heic,.heif,.tif,.tiff" },
      run: async (others) => {
        const bmps = [];
        for (const f of [file, ...others]) bmps.push(await decodeImage(f));
        return { blob: await imageToPdf(bmps), name: outName(name, "_unido", ".pdf") };
      } });
  } else if (ext === ".pdf") {
    acts.push({ label: "PDF → DOCX (Word)", engine: "py", run: async () => {
      const doc = await openPdfJs(file);
      const pages = [];
      for (let n = 1; n <= doc.numPages; n++) {
        setProgress((n - 1) / doc.numPages, `Leyendo página ${n} de ${doc.numPages}…`);
        const { blob } = await renderPage(doc, n, 200, "image/png");
        pages.push(await blob.arrayBuffer());
      }
      closePdf(doc);
      return runPython(file, { label: "PDF → DOCX (Word)", pages });
    } });
    for (const [fmt, mime, ext2] of [["JPG", "image/jpeg", ".jpg"], ["PNG", "image/png", ".png"]]) {
      acts.push({ label: `PDF → imágenes ${fmt}`, run: async () => {
        const doc = await openPdfJs(file);
        const [stem] = splitName(name);
        const files = [];
        for (let n = 1; n <= doc.numPages; n++) {
          setProgress((n - 1) / doc.numPages, `Página ${n} de ${doc.numPages}…`);
          const { blob } = await renderPage(doc, n, 150, mime, 0.92);
          files.push({ name: `${stem}_${String(n).padStart(3, "0")}${ext2}`, data: blob });
        }
        closePdf(doc);
        if (files.length === 1) return { blob: files[0].data, name: files[0].name };
        return { blob: await makeZip(files), name: `${stem}_imagenes.zip` };
      } });
    }
    acts.push({ label: "PDF → texto (TXT)", run: async () => {
      const doc = await openPdfJs(file);
      const out = [];
      for (let n = 1; n <= doc.numPages; n++) {
        const tc = await (await doc.getPage(n)).getTextContent();
        out.push(tc.items.map((it) => it.str + (it.hasEOL ? "\n" : "")).join(""));
      }
      closePdf(doc);
      return { blob: new Blob([out.join("\n\n")], { type: "text/plain;charset=utf-8" }), name: outName(name, "", ".txt") };
    } });
    acts.push({ label: "Comprimir PDF", run: async () => {
      const doc = await loadPdfLib(file);
      const bytes = await doc.save({ useObjectStreams: true });
      if (bytes.length >= file.size) throw new Error("Este PDF ya está optimizado. Prueba «Comprimir PDF (fuerte)».");
      return { blob: pdfBlob(bytes), name: outName(name, "_comprimido", ".pdf") };
    } });
    acts.push({ label: "Comprimir PDF (fuerte)", hint: "Convierte cada página en imagen: el texto deja de poder seleccionarse.", run: async () => {
      const doc = await openPdfJs(file);
      const { PDFDocument } = await pdfLib();
      const out = await PDFDocument.create();
      for (let n = 1; n <= doc.numPages; n++) {
        setProgress((n - 1) / doc.numPages, `Página ${n} de ${doc.numPages}…`);
        const r = await renderPage(doc, n, 110, "image/jpeg", 0.6);
        const img = await out.embedJpg(await r.blob.arrayBuffer());
        out.addPage([r.width, r.height]).drawImage(img, { x: 0, y: 0, width: r.width, height: r.height });
      }
      closePdf(doc);
      const bytes = await out.save();
      if (bytes.length >= file.size) throw new Error("Este PDF es casi todo texto: pasarlo a imágenes lo haría más grande. Usa «Comprimir PDF».");
      return { blob: pdfBlob(bytes), name: outName(name, "_comprimido", ".pdf") };
    } });
    acts.push({ label: "Unir con otros PDF…", ask: { kind: "files", text: "Elige los PDF que quieres añadir", accept: ".pdf,application/pdf" },
      run: async (others) => {
        const { PDFDocument } = await pdfLib();
        const out = await PDFDocument.create();
        for (const f of [file, ...others]) {
          const d = await loadPdfLib(f);
          (await out.copyPages(d, d.getPageIndices())).forEach((p) => out.addPage(p));
        }
        return { blob: pdfBlob(await out.save()), name: outName(name, "_unido", ".pdf") };
      } });
    acts.push({ label: "Extraer páginas…", ask: { kind: "text", text: "Páginas (ej.: 1-3, 5, 8-)", def: "1" },
      run: async (text) => {
        const { PDFDocument } = await pdfLib();
        const d = await loadPdfLib(file);
        const pages = parsePages(text, d.getPageCount());
        const out = await PDFDocument.create();
        (await out.copyPages(d, pages.map((p) => p - 1))).forEach((p) => out.addPage(p));
        return { blob: pdfBlob(await out.save()), name: outName(name, "_paginas", ".pdf") };
      } });
    acts.push({ label: "Rotar páginas…", ask: { kind: "item", text: "Giro", items: ["90° a la derecha", "180°", "90° a la izquierda"] },
      run: async (value) => {
        const { degrees } = await pdfLib();
        const angle = { "90° a la derecha": 90, "180°": 180, "90° a la izquierda": 270 }[value];
        const d = await loadPdfLib(file);
        d.getPages().forEach((p) => p.setRotation(degrees((p.getRotation().angle + angle) % 360)));
        return { blob: pdfBlob(await d.save()), name: outName(name, "_rotado", ".pdf") };
      } });
    acts.push({ label: "Dividir en páginas sueltas", run: async () => {
      const { PDFDocument } = await pdfLib();
      const d = await loadPdfLib(file);
      const [stem] = splitName(name);
      const files = [];
      for (let i = 0; i < d.getPageCount(); i++) {
        const out = await PDFDocument.create();
        const [p] = await out.copyPages(d, [i]);
        out.addPage(p);
        files.push({ name: `${stem}_${String(i + 1).padStart(3, "0")}.pdf`, data: await out.save() });
      }
      return { blob: await makeZip(files), name: `${stem}_paginas.zip` };
    } });
  } else if (ext === ".docx") {
    acts.push({ label: "DOCX → TXT", engine: "py", run: () => runPython(file, { label: "DOCX → TXT" }) });
    acts.push({ label: "DOCX → PDF", hint: "Se abre el cuadro de imprimir: elige «Guardar como PDF».", run: () => docxToPdf(file) });
  } else if (ext === ".txt") {
    acts.push({ label: "TXT → DOCX", engine: "py", run: () => runPython(file, { label: "TXT → DOCX" }) });
  } else if (VID.includes(ext)) {
    const vid = {
      MP4: [".mp4", ["-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart"]],
      WEBM: [".webm", ["-c:v", "libvpx-vp9", "-crf", "33", "-b:v", "0", "-c:a", "libopus"]],
      MKV: [".mkv", ["-c", "copy"]],
      GIF: [".gif", ["-an", "-vf", "fps=12,scale=480:-1:flags=lanczos"]],
    };
    for (const [f, [e, args]] of Object.entries(vid)) {
      if (ext.slice(1).toUpperCase() === f) continue;
      acts.push({ label: `Convertir a ${f}`, engine: "ff", hint: f === "WEBM" ? "WebM es lento en el navegador." : null,
        run: async () => ({ blob: await runFFmpeg(file, e, args), name: outName(name, "", e) }) });
    }
    acts.push({ label: "Extraer audio (MP3)", engine: "ff", run: async () => ({ blob: await runFFmpeg(file, ".mp3", ["-vn", "-q:a", "2"]), name: outName(name, "", ".mp3") }) });
    acts.push({ label: "Comprimir vídeo", engine: "ff", run: async () => ({ blob: await runFFmpeg(file, ".mp4", ["-c:v", "libx264", "-crf", "28", "-preset", "medium", "-c:a", "aac", "-b:a", "128k"]), name: outName(name, "_comprimido", ".mp4") }) });
    acts.push({ label: "Quitar metadatos", engine: "ff", run: async () => ({ blob: await runFFmpeg(file, ext, ["-map_metadata", "-1", "-c", "copy"]), name: outName(name, "_sin_metadatos", ext) }) });
  } else if (AUD.includes(ext)) {
    const aud = {
      MP3: [".mp3", ["-q:a", "2"]], WAV: [".wav", []], FLAC: [".flac", []],
      OGG: [".ogg", ["-c:a", "libvorbis", "-q:a", "5"]], OPUS: [".opus", ["-c:a", "libopus"]],
      M4A: [".m4a", ["-c:a", "aac", "-b:a", "192k"]],
    };
    for (const [f, [e, opts]] of Object.entries(aud)) {
      if (ext.slice(1).toUpperCase() === f) continue;
      acts.push({ label: `Convertir a ${f}`, engine: "ff", run: async () => ({ blob: await runFFmpeg(file, e, ["-vn", ...opts]), name: outName(name, "", e) }) });
    }
    acts.push({ label: "Comprimir (MP3 128 kbps)", engine: "ff", run: async () => ({ blob: await runFFmpeg(file, ".mp3", ["-vn", "-b:a", "128k"]), name: outName(name, "_comprimido", ".mp3") }) });
    acts.push({ label: "Quitar metadatos", engine: "ff", run: async () => ({ blob: await runFFmpeg(file, ext, ["-map_metadata", "-1", "-c", "copy"]), name: outName(name, "_sin_metadatos", ext) }) });
  }
  return acts;
}

// ------------------------------------------------------------------ interfaz
let current = null;   // archivo elegido
let busy = false;
let lastUrl = null;

function status(text, kind = "") {
  const s = $("#cv-status");
  s.hidden = !text;
  s.textContent = text || "";
  s.dataset.kind = kind;
}
function setProgress(p, text) {
  const bar = $("#cv-progress");
  bar.hidden = p == null;
  if (p != null) bar.value = p;
  if (text) status(text);
}
function renderEngines() { /* el estado se muestra con el aviso grande */ }

function chooseFile(file) {
  if (!file || busy) return;
  current = file;
  $("#cv-result").hidden = true;
  $("#cv-ask").hidden = true;
  status("");
  setProgress(null);
  const [, ext] = splitName(file.name);
  $("#cv-file-name").textContent = file.name;
  $("#cv-file-size").textContent = humanSize(file.size);
  $("#cv-file").hidden = false;

  const grid = $("#cv-actions");
  grid.innerHTML = "";
  const acts = actionsFor(file);
  if (!acts.length) {
    status(`No tengo opciones para archivos «${ext || "sin extensión"}».`, "error");
    return;
  }
  if (VID.includes(ext) || AUD.includes(ext)) {
    if (file.size > 150 * 1024 * 1024) status("Es un archivo grande: en el navegador puede tardar mucho o quedarse sin memoria. Funciona mejor con clips cortos.", "warn");
    ffReady().catch(() => {});
  }
  acts.forEach((a, i) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "cv-action";
    b.id = "cv-act-" + i;
    b.textContent = a.label;
    if (a.disabled) { b.disabled = true; b.dataset.desktop = "1"; b.title = a.disabled; b.textContent += " · solo escritorio"; }
    else b.addEventListener("click", () => startAction(a));
    grid.appendChild(b);
  });
}

function startAction(a) {
  if (busy) return;
  if (!a.ask) return execute(a);
  const box = $("#cv-ask");
  box.innerHTML = "";
  const form = document.createElement("form");
  form.className = "cv-ask-form";
  const lab = document.createElement("label");
  lab.htmlFor = "cv-ask-input";
  lab.textContent = a.ask.text;
  let input;
  if (a.ask.kind === "item") {
    input = document.createElement("select");
    a.ask.items.forEach((t) => { const o = document.createElement("option"); o.textContent = t; input.appendChild(o); });
  } else if (a.ask.kind === "files") {
    input = document.createElement("input");
    input.type = "file"; input.multiple = true; input.accept = a.ask.accept; input.required = true;
  } else {
    input = document.createElement("input");
    input.type = a.ask.kind === "int" ? "number" : "text";
    if (a.ask.kind === "int") { input.min = a.ask.min; input.max = a.ask.max; input.step = 1; }
    input.value = a.ask.def; input.required = true;
  }
  input.id = "cv-ask-input";
  const ok = document.createElement("button");
  ok.className = "btn"; ok.type = "submit"; ok.textContent = a.label.replace("…", "");
  const cancel = document.createElement("button");
  cancel.className = "btn btn-link cv-cancel"; cancel.type = "button"; cancel.textContent = "Cancelar";
  cancel.addEventListener("click", () => { box.hidden = true; });
  form.append(lab, input, ok, cancel);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    let v = input.value;
    if (a.ask.kind === "int") {
      v = parseInt(v, 10);
      if (isNaN(v) || v < a.ask.min || v > a.ask.max) { status(`Escribe un número entre ${a.ask.min} y ${a.ask.max}.`, "error"); return; }
    }
    if (a.ask.kind === "files") v = [...input.files];
    box.hidden = true;
    execute(a, v);
  });
  box.appendChild(form);
  box.hidden = false;
  input.focus();
}

async function execute(a, value) {
  busy = true;
  document.querySelectorAll(".cv-action").forEach((b) => (b.disabled = true));
  $("#cv-result").hidden = true;
  setProgress(null);
  status(`Procesando: ${a.label.replace("…", "")}…`);
  const t0 = performance.now();
  try {
    const r = await a.run(value);
    if (r && r.printed) status("En el cuadro de imprimir, elige «Guardar como PDF».");
    else { showResult(r, ((performance.now() - t0) / 1000)); status(""); }
  } catch (err) {
    console.error(err);
    status("No se pudo completar: " + (err.message || err), "error");
  } finally {
    busy = false;
    setProgress(null);
    document.querySelectorAll(".cv-action").forEach((b) => (b.disabled = b.dataset.desktop === "1"));
  }
}

function showResult({ blob, name }, secs) {
  if (lastUrl) URL.revokeObjectURL(lastUrl);
  lastUrl = URL.createObjectURL(blob);
  const link = $("#cv-download");
  link.href = lastUrl;
  link.download = name;
  $("#cv-result-name").textContent = name;
  const diff = blob.size - current.size;
  const pct = current.size ? Math.round(Math.abs(diff) / current.size * 100) : 0;
  let cmp = "";
  if (pct >= 1) cmp = diff < 0 ? ` · ${pct} % más pequeño` : ` · ${pct} % más grande`;
  $("#cv-result-size").textContent = `${humanSize(blob.size)}${cmp} · ${secs.toFixed(1).replace(".", ",")} s`;
  $("#cv-result").hidden = false;
}

export function init() {
  const drop = $("#cv-drop"), input = $("#cv-input");
  drop.addEventListener("click", () => input.click());
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  input.addEventListener("change", () => { chooseFile(input.files[0]); input.value = ""; });
  ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => chooseFile(e.dataTransfer.files[0]));
  renderEngines();
  // Python se va cargando en segundo plano para que esté listo cuando haga falta
  const warm = () => pyReady().catch(() => {});
  if ("requestIdleCallback" in window) requestIdleCallback(warm, { timeout: 3000 }); else setTimeout(warm, 1500);
}

// Para las pruebas automáticas
export const _test = { actionsFor, parsePages, makeZip, outName, engines };
