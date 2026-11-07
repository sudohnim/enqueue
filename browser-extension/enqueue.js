// Talking to Enqueue on this Mac: the engine listens on 127.0.0.1:8787 only.
const ENGINE = "http://127.0.0.1:8787";

async function connectCode() {
  const { code } = await chrome.storage.local.get("code");
  return code || "";
}

async function call(path, init = {}) {
  const code = await connectCode();
  let r;
  try {
    r = await fetch(ENGINE + path, { ...init, headers: { ...(init.headers || {}), "X-Enqueue-Key": code } });
  } catch (err) {
    throw new Error("Enqueue is not open on this Mac.");
  }
  if (r.status === 403) throw new Error("Enqueue did not accept the connect code. Paste a new one.");
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "Enqueue said no (" + r.status + ").");
  return r.json();
}

const json = (body) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

async function saveLink(url, title, note) {
  const saved = await call("/capture/link", json({ url, title: title || null }));
  if (note && note.trim()) await call("/artifacts/" + saved.id + "/annotations", json({ text: note.trim() }));
  return saved;
}

async function saveWords(text, url, title, note) {
  const quoted = text.trim().split("\n").map((line) => "> " + line).join("\n");
  const source = url ? "\n\n[" + (title || url) + "](" + url + ")" : "";
  const mine = note && note.trim() ? note.trim() + "\n\n" : "";
  return call("/notes", json({ body: mine + quoted + source }));
}

async function savePicture(src, pageUrl) {
  const r = await fetch(src);
  if (!r.ok) throw new Error("Could not read that picture.");
  const blob = await r.blob();
  const name = (new URL(src, pageUrl).pathname.split("/").pop() || "picture").slice(0, 120);
  const form = new FormData();
  form.append("file", blob, /\.[a-z0-9]{2,5}$/i.test(name) ? name : name + "." + (blob.type.split("/")[1] || "png"));
  return call("/capture/upload", { method: "POST", body: form });
}
