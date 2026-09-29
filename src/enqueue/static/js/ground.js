// ---- the ground drifts with the day ------------------------------------------------
// The lavender canvas shifts slowly through the day: rosier and lighter at dawn, the
// usual lavender by day, warmer at dusk, deep violet-grey at night. It moves a few
// percent an hour, so you never see it change, but opening the app at 7am and at
// midnight feels different. Only the ground ladder moves (--bg and the surfaces
// derived from it); inks, lines and the accent stay put, and every ink still clears
// its contrast floor on the darkest (night) ground.
//
// tokens.css holds the daytime values as the static defaults; this overrides them on
// the root at load and once a minute. Shared by the home page, the capture overlay
// and the phone. On Android the status and navigation bar strips are painted by the
// shell, so the ground is handed to it through the EnqueueAndroid bridge too.
(function () {
	// Keyframes by hour (0-24), interpolated linearly between neighbours.
	const KEYS = [
		[0, "#ddd1ec"], // night: deep violet-grey
		[6, "#f2e9f2"], // dawn: a rosy, lighter lavender
		[11, "#eee8f6"], // day: the tokens.css default
		[18, "#ebe0f0"], // dusk: warmer, a touch of mauve
		[21, "#e4d9f0"], // evening: cooling toward night
		[24, "#ddd1ec"],
	];
	const WHITE = [255, 255, 255];
	const DEEP = [58, 13, 99]; // the violet the recessed well sinks toward

	const rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
	const mix = (a, b, t) => a.map((x, i) => Math.round(x + (b[i] - x) * t));
	const hex = (c) => "#" + c.map((x) => x.toString(16).padStart(2, "0")).join("");

	function groundAt(date) {
		const h = date.getHours() + date.getMinutes() / 60;
		let i = 0;
		while (KEYS[i + 1][0] <= h) i++;
		const [h0, c0] = KEYS[i];
		const [h1, c1] = KEYS[i + 1];
		return mix(rgb(c0), rgb(c1), (h - h0) / (h1 - h0));
	}

	let last = "";
	function apply() {
		const bg = groundAt(new Date());
		const key = hex(bg);
		// The shell strip is re-sent every tick (cheap), in case the bridge was not
		// ready at first paint; the page's own tokens only change when the colour does.
		const bridge = window.EnqueueAndroid;
		if (bridge && typeof bridge.setGround === "function") bridge.setGround(key);
		if (key === last) return;
		last = key;
		const root = document.documentElement.style;
		// The ladder climbs toward white from the ground and the well sinks below it,
		// at the same steps as the tokens.css defaults (#eee8f6 -> #f8f5fb, #fbf9fd,
		// #e3d9ef).
		root.setProperty("--bg", key);
		root.setProperty("--surface", hex(mix(bg, WHITE, 0.6)));
		root.setProperty("--surface-doc", hex(mix(bg, WHITE, 0.78)));
		root.setProperty("--surface-3", hex(mix(bg, DEEP, 0.06)));
	}

	apply();
	setInterval(apply, 60000);
	document.addEventListener("visibilitychange", () => {
		if (!document.hidden) apply();
	});
})();
