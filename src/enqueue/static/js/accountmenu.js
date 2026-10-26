// The account at the top right of the wall, beside the ?: who is signed in to Enqueue
// sync, the plan and what it has used, the devices, and the way out. Signed out, the
// same place offers the sign-in, which lives in Settings, Sync.
//
// The chip draws at once from the account as last read (`accountMenuMe`) and catches
// up from GET /account, which refreshes the plan from the relay behind it
// (account.refresh_plan_soon). The device list is asked for only when the menu opens.

let accountMenuMe = null;

function homeCornerHtml() {
	return (
		'<div class="homecorner">' +
		'<span id="accountChip" class="account-chip-slot">' +
		accountChipInner(accountMenuMe) +
		"</span>" +
		welcomeTriggerHtml() +
		"</div>"
	);
}

function accountMenuAvatar(me, size) {
	if (me && me.picture)
		return (
			'<img class="acct-face" style="--face:' +
			size +
			'px" src="/account/picture" alt="">'
		);
	const letter = ((me && (me.name || me.email)) || "?").trim().charAt(0).toUpperCase();
	return (
		'<span class="acct-face initial" style="--face:' +
		size +
		'px" aria-hidden="true">' +
		esc(letter) +
		"</span>"
	);
}

function accountChipInner(me) {
	if (!me) return "";
	if (!me.signed_in)
		return (
			'<button type="button" class="acct-chip signed-out" onclick="toggleAccountMenu(this)" ' +
			'aria-haspopup="menu" aria-expanded="false" aria-label="Account" title="Account">' +
			'<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="9" r="3.6"/>' +
			'<path d="M5.5 19.2c1.3-3 3.7-4.4 6.5-4.4s5.2 1.4 6.5 4.4"/></svg></button>'
		);
	const who = me.name || me.email || "Your account";
	return (
		'<button type="button" class="acct-chip" onclick="toggleAccountMenu(this)" ' +
		'aria-haspopup="menu" aria-expanded="false" aria-label="' +
		esc(who) +
		'" title="' +
		esc(who) +
		'">' +
		accountMenuAvatar(me, 32) +
		"</button>"
	);
}

async function paintAccountChip() {
	let me;
	try {
		me = await api("/account");
	} catch {
		return; // the engine is busy or gone: keep what is drawn
	}
	accountMenuMe = me;
	const slot = document.getElementById("accountChip");
	if (slot && !document.querySelector(".acctmenu")) slot.innerHTML = accountChipInner(me);
}

function accountPlanLine(plan) {
	plan = plan || {};
	const pro = plan.tier === "pro";
	const room = plan.storage_bytes ? planBytes(plan.storage_bytes) : "";
	const used = room ? planBytes(plan.used_bytes || 0) + " of " + room + " used" : "";
	return (
		'<div class="acct-plan"><span class="acct-tier' +
		(pro ? " pro" : "") +
		'">' +
		(pro ? "Pro" : "Free") +
		"</span>" +
		(used ? "<span>" + esc(used) + "</span>" : "") +
		"</div>"
	);
}

function closeAccountMenu() {
	const menu = document.querySelector(".acctmenu");
	if (!menu) return;
	menu.remove();
	const chip = document.querySelector(".acct-chip");
	if (chip) {
		chip.setAttribute("aria-expanded", "false");
		chip.focus({ preventScroll: true });
	}
	document.removeEventListener("pointerdown", accountMenuOutside, true);
	document.removeEventListener("keydown", accountMenuKeys, true);
}

function accountMenuOutside(event) {
	if (!event.target.closest(".acctmenu, .acct-chip")) closeAccountMenu();
}

function accountMenuKeys(event) {
	if (event.key === "Escape") {
		event.preventDefault();
		closeAccountMenu();
		return;
	}
	if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
	const items = [...document.querySelectorAll(".acctmenu [role=menuitem]")];
	if (!items.length) return;
	event.preventDefault();
	const at = items.indexOf(document.activeElement);
	const next = event.key === "ArrowDown" ? at + 1 : at - 1;
	items[(next + items.length) % items.length].focus();
}

function toggleAccountMenu(chip) {
	if (document.querySelector(".acctmenu")) {
		closeAccountMenu();
		return;
	}
	const me = accountMenuMe || {};
	const menu = document.createElement("div");
	menu.className = "acctmenu";
	menu.setAttribute("role", "menu");
	menu.setAttribute("aria-label", "Account");
	if (me.signed_in) {
		const how = PROVIDER_NAMES[me.provider] || "";
		menu.innerHTML =
			'<div class="acct-who">' +
			accountMenuAvatar(me, 44) +
			'<div class="acct-words"><div class="acct-name">' +
			esc(me.name || me.email || "Signed in") +
			"</div>" +
			'<div class="acct-sub">' +
			esc(me.name && me.email ? me.email : how ? "Signed in with " + how : "") +
			"</div></div></div>" +
			accountPlanLine(me.plan) +
			'<button type="button" role="menuitem" class="acct-item" onclick="accountMenuGo(\'sync\')">' +
			'<span>Devices</span><span class="acct-meta" id="acctDevices">...</span></button>' +
			'<button type="button" role="menuitem" class="acct-item" onclick="accountMenuGo()">' +
			"<span>Settings</span></button>" +
			'<div class="acct-rule"></div>' +
			'<button type="button" role="menuitem" class="acct-item" onclick="accountMenuSignOut()">' +
			"<span>Sign out</span></button>";
	} else {
		menu.innerHTML =
			'<div class="acct-pitch"><div class="acct-name">Not signed in</div>' +
			'<div class="acct-sub">Sign in to sync your library with your phone and your other Macs. Only your devices can read it.</div></div>' +
			'<button type="button" role="menuitem" class="acct-item strong" onclick="accountMenuGo(\'sync\')">' +
			"<span>Sign in to Enqueue sync</span></button>" +
			'<button type="button" role="menuitem" class="acct-item" onclick="accountMenuGo()">' +
			"<span>Settings</span></button>";
	}
	document.body.appendChild(menu);
	const box = chip.getBoundingClientRect();
	menu.style.top = Math.round(box.bottom + 8) + "px";
	menu.style.right = Math.round(window.innerWidth - box.right) + "px";
	chip.setAttribute("aria-expanded", "true");
	document.addEventListener("pointerdown", accountMenuOutside, true);
	document.addEventListener("keydown", accountMenuKeys, true);
	const first = menu.querySelector("[role=menuitem]");
	if (first) first.focus({ preventScroll: true });
	if (me.signed_in) accountMenuDevices();
}

async function accountMenuDevices() {
	let line = "";
	try {
		const res = await api("/account/devices");
		const n = (res.devices || []).length;
		line = n === 1 ? "1 device" : n + " devices";
	} catch {
		line = "";
	}
	const at = document.getElementById("acctDevices");
	if (at) at.textContent = line;
	// Asking for the devices also brought the plan up to date.
	try {
		accountMenuMe = await api("/account");
		const plan = document.querySelector(".acctmenu .acct-plan");
		if (plan) plan.outerHTML = accountPlanLine(accountMenuMe.plan);
	} catch {
		// keep the plan as drawn
	}
}

function accountMenuGo(tab) {
	closeAccountMenu();
	if (tab) currentSettingsTab = tab;
	showSettings();
}

async function accountMenuSignOut() {
	closeAccountMenu();
	const yes = await ask(
		"Sign out of Enqueue sync?",
		"This Mac stops syncing. Your library stays here, and your phone keeps what it has.",
		"Sign out",
	);
	if (!yes) return;
	try {
		await api("/account/sign-out", { method: "POST" });
	} catch (err) {
		toast(String(err.message || err), true);
		return;
	}
	toast("Signed out. This Mac no longer syncs.");
	await paintAccountChip();
}
