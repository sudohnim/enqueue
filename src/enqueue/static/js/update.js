// A new version of the Mac app, downloaded and put in place while this one ran
// (desktop/src/lib.rs watch_for_updates), the way Claude's app does it: a card at the
// bottom right offers Update now (restart into it) or Update on close (put it in place
// when the app quits, which also happens if the card is ignored). The shell calls window.__enqUpdateReady when the install
// lands, and the page asks once at load in case it landed before the page did.

function showUpdateReady(version) {
	if (!version || document.getElementById("updateReady")) return;
	const node = document.createElement("div");
	node.id = "updateReady";
	node.className = "update-ready";
	node.setAttribute("role", "status");
	node.innerHTML =
		'<div class="update-words"><div class="update-title">Update available</div>' +
		'<div class="update-sub">Enqueue ' +
		esc(version) +
		" is downloaded and ready.</div></div>" +
		'<div class="update-actions">' +
		'<button class="btn tertiary sm" onclick="updateOnClose()">Update on close</button>' +
		'<button class="btn primary sm" onclick="restartForUpdate(this)">Update now</button>' +
		"</div>";
	document.body.appendChild(node);
}

// The update is put in place when the app quits (desktop/src/lib.rs, RunEvent::Exit),
// whether or not this is pressed; it only puts the card away.
function updateOnClose() {
	const node = document.getElementById("updateReady");
	if (node) node.remove();
	toast("Enqueue will update the next time you quit it.");
}

async function restartForUpdate(button) {
	button.disabled = true;
	button.textContent = "Updating...";
	try {
		await window.__TAURI__.core.invoke("app_restart");
	} catch (err) {
		button.disabled = false;
		button.textContent = "Update now";
		toast("Enqueue could not update now. It will try again when you quit it.", true);
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
