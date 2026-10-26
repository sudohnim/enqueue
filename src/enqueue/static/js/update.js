// A new version of the Mac app, downloaded and put in place while this one ran
// (desktop/src/lib.rs watch_for_updates). It runs at the next start either way; this
// offers to start it now. The shell calls window.__enqUpdateReady when the install
// lands, and the page asks once at load in case it landed before the page did.

function showUpdateReady(version) {
	if (!version || document.getElementById("updateReady")) return;
	const node = document.createElement("div");
	node.id = "updateReady";
	node.className = "update-ready";
	node.setAttribute("role", "status");
	node.innerHTML =
		"<span>Enqueue " +
		esc(version) +
		' is ready.</span><button class="btn primary sm" onclick="restartForUpdate(this)">Restart</button>' +
		'<button class="update-later" aria-label="Later" onclick="this.parentNode.remove()">Later</button>';
	document.body.appendChild(node);
}

async function restartForUpdate(button) {
	button.disabled = true;
	button.textContent = "Restarting...";
	try {
		await window.__TAURI__.core.invoke("app_restart");
	} catch (err) {
		button.disabled = false;
		button.textContent = "Restart";
		toast("Enqueue could not restart. Quit it and open it again.", true);
	}
}

window.__enqUpdateReady = showUpdateReady;

(async () => {
	if (!(window.__TAURI__ && window.__TAURI__.core)) return;
	try {
		showUpdateReady(await window.__TAURI__.core.invoke("update_ready"));
	} catch {
		// an older shell without the command: nothing to offer
	}
})();
