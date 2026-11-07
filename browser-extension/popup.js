const $ = (id) => document.getElementById(id);

function say(text, bad = false) {
  $("status").textContent = text;
  $("status").className = bad ? "bad" : "";
}

async function show() {
  const code = await connectCode();
  $("connect").hidden = !!code;
  $("save").hidden = !code;
  if (!code) return $("code").focus();
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  $("title").value = tab?.title || "";
  $("url").textContent = tab?.url || "";
  $("save").dataset.url = tab?.url || "";
  if (!/^https?:/i.test(tab?.url || "")) {
    $("save").hidden = true;
    return say("This tab is not a web page. Right-click a link or a picture to save it.");
  }
  $("note").focus();
}

$("connect").addEventListener("submit", async (event) => {
  event.preventDefault();
  const code = $("code").value.trim();
  if (!code) return;
  await chrome.storage.local.set({ code });
  try {
    await call("/extension/check", { method: "POST" });
  } catch (err) {
    await chrome.storage.local.remove("code");
    return say(err.message, true);
  }
  say("Connected.");
  show();
});

$("save").addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = $("save").dataset.url;
  if (!/^https?:/i.test(url)) return say("Only web pages can be saved.", true);
  $("save").querySelector("button[type=submit]").disabled = true;
  try {
    const saved = await saveLink(url, $("title").value.trim(), $("note").value);
    say(saved.created === false ? "Already saved. It moved to the front." : "Saved to Enqueue.");
    setTimeout(() => window.close(), 1200);
  } catch (err) {
    $("save").querySelector("button[type=submit]").disabled = false;
    say(err.message, true);
  }
});

$("forget").addEventListener("click", async () => {
  await chrome.storage.local.remove("code");
  say("");
  show();
});

show();
