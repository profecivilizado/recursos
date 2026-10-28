// Motor de vídeo y audio del conversor: FFmpeg compilado para el navegador (ffmpeg.wasm).
// Solo se descarga cuando alguien elige un vídeo o un audio.
const CORE = "https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.12.6/dist/umd/";
let core = null;
let loading = null;

async function toBlobURL(url, type, onProgress) {
  const r = await fetch(url);
  if (!r.ok) throw new Error("No se pudo descargar el motor de vídeo (" + r.status + ")");
  const reader = r.body.getReader();
  const chunks = [];
  let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    got += value.length;
    if (onProgress) onProgress(got);
  }
  return URL.createObjectURL(new Blob(chunks, { type }));
}

async function load() {
  const coreURL = await toBlobURL(CORE + "ffmpeg-core.js", "text/javascript");
  const wasmURL = await toBlobURL(CORE + "ffmpeg-core.wasm", "application/wasm",
    (bytes) => self.postMessage({ type: "download", bytes }));
  importScripts(coreURL);
  core = await self.createFFmpegCore({
    mainScriptUrlOrBlob: coreURL + "#" + btoa(JSON.stringify({ wasmURL })),
  });
  core.setLogger((d) => { lastLog.push(d.message); if (lastLog.length > 20) lastLog.shift(); });
  core.setProgress((d) => self.postMessage({ type: "progress", progress: d.progress }));
}

const lastLog = [];

self.onmessage = async (ev) => {
  const { id, cmd } = ev.data;
  try {
    if (cmd === "init") {
      loading = loading || load();
      await loading;
      self.postMessage({ id, ok: true });
      return;
    }
    await loading;
    if (cmd === "exec") {
      const { input, data, output, args } = ev.data;
      lastLog.length = 0;
      core.FS.writeFile(input, new Uint8Array(data));
      core.setTimeout(-1);
      core.exec("-y", "-i", input, ...args, output);
      const ret = core.ret;
      core.reset();
      let bytes = null;
      if (ret === 0) bytes = core.FS.readFile(output);
      try { core.FS.unlink(input); } catch (e) {}
      try { core.FS.unlink(output); } catch (e) {}
      if (ret !== 0 || !bytes) throw new Error("FFmpeg falló:\n" + lastLog.slice(-4).join("\n"));
      self.postMessage({ id, ok: true, data: bytes.buffer }, [bytes.buffer]);
    }
  } catch (err) {
    self.postMessage({ id, ok: false, error: String(err && err.message || err) });
  }
};
