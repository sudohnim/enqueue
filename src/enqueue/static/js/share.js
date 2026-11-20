// The shared-note viewer. The key is the part of the address after "#", which the
// browser never sends to a server; the relay serves only sealed bytes. Format: see
// share.py in the engine.
(() => {
  const $ = (id) => document.getElementById(id);
  const sid = location.pathname.split("/").pop();
  const frag = location.hash.slice(1);

  const unb64 = (s) => {
    const t = s.replace(/-/g, "+").replace(/_/g, "/");
    return Uint8Array.from(atob(t + "=".repeat((4 - (t.length % 4)) % 4)), (c) =>
      c.charCodeAt(0),
    );
  };

  const say = (text) => {
    $("state").textContent = text;
    $("state").hidden = false;
  };

  async function sealKey(linkKey, passphrase) {
    if (!passphrase) return linkKey;
    const word = new TextEncoder().encode(passphrase.normalize("NFC"));
    const base = await crypto.subtle.importKey("raw", word, "PBKDF2", false, ["deriveBits"]);
    const bits = await crypto.subtle.deriveBits(
      { name: "PBKDF2", hash: "SHA-256", salt: linkKey, iterations: 600000 },
      base,
      256,
    );
    return new Uint8Array(bits);
  }

  async function unseal(data, key) {
    const k = await crypto.subtle.importKey("raw", key, "AES-GCM", false, ["decrypt"]);
    const plain = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: data.slice(6, 18), additionalData: data.slice(0, 18) },
      k,
      data.slice(18),
    );
    return JSON.parse(new TextDecoder().decode(plain));
  }

  function showExpiry(res) {
    const at = new Date(Number(res.headers.get("X-Expires-At")) * 1000);
    if (!res.headers.get("X-Expires-At") || isNaN(at)) return;
    const when = at.toLocaleString(undefined, { dateStyle: "long", timeStyle: "short" });
    $("expiry").textContent = "This link stops working on " + when + ".";
    $("expiry").hidden = false;
  }

  function show(note) {
    const title = (note.title || "").trim();
    const body = note.body || "";
    document.title = title || "A shared note";
    const lead = body.match(/^\s*#\s+(.+)/);
    const html = (lead ? "" : title ? "<h1>" + esc(title) + "</h1>" : "") + md(body);
    $("body").innerHTML = html;
    // Pictures in a note live on its owner's Mac; nothing here can load them.
    $("body").querySelectorAll("img").forEach((img) => img.remove());
    const at = new Date(note.shared_at);
    $("meta").textContent = isNaN(at)
      ? ""
      : "Updated " + at.toLocaleDateString(undefined, { dateStyle: "long" });
    $("state").hidden = true;
    $("lock").hidden = true;
    $("note").hidden = false;
  }

  async function main() {
    if (!/^[A-Za-z0-9_-]{43}$/.test(frag)) {
      say("This link is not complete. Ask for the whole link, with the part after #.");
      return;
    }
    if (!window.crypto || !crypto.subtle) {
      say("This browser cannot open shared notes. Try a current Safari, Chrome or Firefox.");
      return;
    }
    let res;
    try {
      res = await fetch("/share/" + sid, { cache: "no-store", referrerPolicy: "no-referrer" });
    } catch (_) {
      say("Could not reach the note. Check your connection and reload.");
      return;
    }
    if (res.status === 404) {
      say("This note is no longer shared. The link expired or its owner stopped sharing it.");
      return;
    }
    if (!res.ok) {
      say("Could not open the note right now. Try again in a moment.");
      return;
    }
    showExpiry(res);
    const data = new Uint8Array(await res.arrayBuffer());
    const head = String.fromCharCode(...data.slice(0, 4));
    if (head !== "ENQS" || data[4] !== 1) {
      say("This note was shared by a newer Enqueue. Update the page or ask for a new link.");
      return;
    }
    const linkKey = unb64(frag);
    if (!(data[5] & 1)) {
      try {
        show(await unseal(data, linkKey));
      } catch (_) {
        say("This link does not open the note. Ask for the whole link again.");
      }
      return;
    }
    $("state").hidden = true;
    $("lock").hidden = false;
    $("pass").focus();
    $("lock").addEventListener("submit", async (e) => {
      e.preventDefault();
      const button = $("lock").querySelector("button");
      button.disabled = true;
      $("passError").hidden = true;
      try {
        show(await unseal(data, await sealKey(linkKey, $("pass").value)));
      } catch (_) {
        $("passError").hidden = false;
        $("pass").select();
      } finally {
        button.disabled = false;
      }
    });
  }

  function esc(s) {
    return String(s ?? "").replace(
      /[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
    );
  }
  window.esc = esc;
  main();
})();
