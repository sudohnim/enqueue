// Device approval (sync/join.py): one Mac asks to join the account's library, another
// that holds the key approves it. Both show the same six digits, worked out on each Mac
// from the asking Mac's public key: matching digits mean the key went through untouched.

// ---- the asking Mac: the Sync tab while it waits --------------------------------

function joinCodeHtml(code) {
	return '<div class="joincode" aria-label="Code ' + esc(code || "") + '">' + esc(code || "") + "</div>";
}

function renderAccountJoin(me) {
	const j = (me && me.join) || {};
	const err = (me && me.sign_in && me.sign_in.error) || j.error;
	const again =
		'<div class="actions"><button class="btn primary" onclick="askToJoinAgain()">Ask again</button>' +
		'<button class="btn ghost" onclick="stopJoining()">Not now</button></div>';
	if (j.state === "waiting") {
		const mins = j.expires_at ? Math.max(1, Math.round((j.expires_at * 1000 - Date.now()) / 60000)) : 10;
		return (
			'<div class="field"><span class="rowlabel">Approve this Mac from your other computer</span>' +
			'<div class="aside">Your library is already on Enqueue sync. Open Enqueue on a computer that has it: ' +
			"it will ask whether this Mac may join. Approve it there if it shows this code.</div>" +
			joinCodeHtml(j.code) +
			'<div class="aside joinwait">Waiting for approval. ' +
			"This code works for " +
			mins +
			(mins === 1 ? " more minute." : " more minutes.") +
			"</div></div>" +
			'<div class="actions"><button class="btn ghost" onclick="stopJoining()">Cancel</button></div>'
		);
	}
	if (j.state === "denied") {
		return (
			'<div class="field"><span class="rowlabel">Turned down</span>' +
			'<div class="aside">The other computer said no. If that was a slip, ask again.</div></div>' +
			again
		);
	}
	if (j.state === "expired") {
		return (
			'<div class="field"><span class="rowlabel">The request ran out</span>' +
			'<div class="aside">Nobody approved it within ten minutes. Ask again with the other computer open.</div></div>' +
			again
		);
	}
	return (
		'<div class="field"><span class="rowlabel">This Mac could not join yet</span>' +
		'<div class="aside">' +
		esc(err || "Something went wrong asking to join.") +
		"</div></div>" +
		again
	);
}

let joinPolling = false;
async function pollJoin() {
	if (joinPolling) return;
	joinPolling = true;
	let last = "";
	try {
		while (true) {
			await new Promise((done) => setTimeout(done, 2000));
			let me;
			try {
				me = await api("/account");
			} catch {
				continue;
			}
			const s = me.sign_in && me.sign_in.state;
			if (s === "done") {
				toast("This Mac joined your library. It's coming in now.");
				renderSettingsTab(currentSettingsTab || "sync");
				return;
			}
			if (s !== "join") return;
			const seen = (me.join && me.join.state) + "|" + (me.join && me.join.code);
			if (seen !== last) {
				last = seen;
				renderSettingsTab(currentSettingsTab || "sync");
			}
			if (me.join && me.join.state !== "waiting") return;
		}
	} finally {
		joinPolling = false;
	}
}

async function askToJoinAgain() {
	try {
		await api("/account/join", { method: "POST" });
	} catch (err) {
		toast(String(err.message || err), true);
	}
	await renderSettingsTab(currentSettingsTab || "sync");
	pollJoin();
}

async function stopJoining() {
	await api("/account/join", { method: "DELETE" }).catch(() => null);
	// Signed in but without the key: signing out puts the Mac back where it started.
	await api("/account/sign-out", { method: "POST" }).catch(() => null);
	toast("This Mac stays on its own.");
	renderSettingsTab(currentSettingsTab || "sync");
}

// ---- the account had no library yet: this Mac makes the first key ----------------

function renderAccountNeedsKey() {
	return (
		'<div class="field"><span class="rowlabel">Start your library on Enqueue sync</span>' +
		'<div class="aside">Signed in. This is the first computer on this account, so it makes the ' +
		"library's key now and shows you its recovery phrase once.</div></div>" +
		'<div class="actions"><button class="btn primary" onclick="makeFirstKey()">Make the key</button></div>'
	);
}

async function makeFirstKey() {
	window.syncAfterRecovery = "finish";
	await initKeyringAndShowRecovery();
}

async function finishNewLibrary() {
	try {
		await api("/account/finish", { method: "POST" });
		toast("Signed in. Enqueue sync is on.");
	} catch (err) {
		toast(String(err.message || err), true);
	}
	window.syncSetupStep = null;
	renderSettingsTab(currentSettingsTab || "sync");
}

// ---- a Mac that holds the key: the approve prompt -------------------------------

const approvalSeen = new Set();
let approvalOpen = false;

async function checkApprovals() {
	if (approvalOpen || document.visibilityState !== "visible") return;
	let joins;
	try {
		joins = (await api("/account/joins")).joins || [];
	} catch {
		return; // not signed in, offline, or the relay is down: ask again later
	}
	const next = joins.find((j) => !approvalSeen.has(j.id));
	if (!next) return;
	approvalSeen.add(next.id);
	approvalOpen = true;
	try {
		await promptApproval(next);
	} finally {
		approvalOpen = false;
	}
}

function promptApproval(j) {
	const box = modalShell(
		'<h2 id="approveTitle"></h2>' +
			'<p class="approve-lead"></p>' +
			joinCodeHtml(j.code) +
			'<p class="approve-note">Only approve a computer you are signing in to yourself, ' +
			"right now. It gets your whole library.</p>" +
			'<div class="asked">' +
			'<button class="btn secondary" value="no">Not mine</button>' +
			'<button class="btn primary" value="yes">Approve</button>' +
			"</div>",
		{ labelledBy: "approveTitle", cancelValue: false },
	);
	box.classList.add("approve");
	box.querySelector("h2").textContent = (j.name || "A computer") + " wants to join your library";
	box.querySelector(".approve-lead").textContent =
		"Approve it if " + (j.name || "that computer") + " shows this code:";
	box.querySelector('[value="yes"]').onclick = () => box.finish(true);
	return box.promise.then(async (yes) => {
		const path = "/account/joins/" + encodeURIComponent(j.id) + (yes ? "/approve" : "/deny");
		try {
			await api(path, { method: "POST" });
			toast(yes ? (j.name || "The computer") + " is joining your library." : "Turned down.");
		} catch (err) {
			toast(String(err.message || err), true);
		}
	});
}

function watchApprovals() {
	checkApprovals();
	setInterval(checkApprovals, 10000);
	window.addEventListener("focus", checkApprovals);
	document.addEventListener("visibilitychange", checkApprovals);
}
