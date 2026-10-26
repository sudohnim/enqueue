// The guides behind the ? marks in Settings, and the eye's answers about settings.
//
// One file for every app, the way tour.js and details.js are: the words exist once, so
// the desktop and the phone cannot drift apart. A guide is plain data. Nothing in here
// touches the page, the engine or a model:
//
//   Guides.get(id)             one guide
//   Guides.all(platform)       the guides this app shows
//   Guides.stand(id, setup)    where THIS installation stands on it (from GET /setup)
//   Guides.match(text, opts)   guides ranked against what was typed, in the page
//   Guides.text(guide)         a guide as plain text, for the one model call
//
// A guide's shape: what it is, whether you need it, the steps, what else to know, and
// the guides it goes with. Keep each to what a person needs at the moment they are
// looking at the setting. `words` are the ways people ask for it; they only feed the
// matcher and are never shown.
//
// The vault has no guide, on purpose: its door is unmarked, and a help page anyone
// holding the device can open must not mark it.
const Guides = (() => {
  const LIST = [
    {
      id: "answers",
      tab: "ai",
      title: "Where answers come from",
      voice: "Someone has to do the reading.",
      what:
        "The model that reads what you save and answers when you ask. It can run on this Mac, or be a service you hold a key for.",
      need:
        "Saving and searching by your own words work with no model at all. Summaries, finding things by what they mean, and asking questions need one.",
      steps: [
        "Choose a service under Answers come from.",
        "For an online assistant, paste its key into Your account key.",
        "Pick a model under Models, then press Save.",
      ],
      know: [
        "On this Mac means Ollama: nothing you save leaves the machine, and it needs Ollama running.",
        "With a service, the text it reads is sent to that service. Anything you marked local only never is.",
      ],
      also: ["models", "api-key", "concepts"],
      words:
        "model ai backend provider service ollama openrouter opencode connect connection llm privacy private leave machine local remote cloud who reads sent where",
    },
    {
      id: "models",
      tab: "ai",
      title: "The four models",
      voice: "Four jobs. One bird can do them all.",
      what:
        "Four jobs, each of which can use its own model, under More options on the Assistant tab: chatting answers your questions, summaries are written when you save, search settles close calls, and pictures are described so they can be found.",
      need:
        "Only the model for chatting has to be set. Leave summaries and search empty and they use the same one.",
      steps: [
        "Set Chat to the model you want answers from.",
        "Optional: a stronger model for summaries makes search better, at the cost of a slower save.",
        "Optional: a fast, cheap model for Search. It runs on every search.",
        "Images needs a model that can see, such as llava on Ollama.",
      ],
      know: [
        "Changing the model for summaries makes the ones you have count as old. They are rewritten in the background, a few at a time.",
      ],
      also: ["answers", "concepts"],
      words:
        "model models chat ingestion ingest search images vision llava summarize summary which model faster cheaper stronger describe pictures photos role",
    },
    {
      id: "api-key",
      tab: "ai",
      title: "Your account key (API key)",
      voice: "A key I keep, and never read aloud.",
      what:
        "The password a model service gives you so it knows the calls are yours. Enqueue keeps it in the macOS Keychain, not in any file.",
      need: "Only when answers come from a service. A model on this Mac needs no key.",
      steps: [
        "Get a key from the service you chose (on their site, often under API keys).",
        "Paste it into Your account key and press Save beside it.",
        "Forget removes it from the Keychain.",
      ],
      know: [
        "Once sync is set up, the key travels to your phone encrypted, so the phone can ask questions too.",
        "It is never shown again after you save it, only its last few characters.",
      ],
      also: ["answers", "relay"],
      words:
        "api key apikey token password credential keychain secret paste save forget remove where stored safe unauthorized 401",
    },
    {
      id: "concepts",
      tab: "ai",
      title: "Summaries and concepts",
      voice: "What a thing is an example of.",
      what:
        "When you save something, the model writes a few lines about what it is and what it could be an example of. Search uses those lines to find a note by its meaning, not only its words.",
      need:
        "They are written for you. Summarize again is for after you switch to a better assistant and want everything read again.",
      steps: [
        "Summarize again reads every item again with the current model for summaries.",
        "It runs in the background, one item at a time. Keep using the app.",
        "Progress shows under Activity.",
      ],
      know: [
        "A note you are still writing is read once you have left it alone for five minutes.",
        "You can edit any line, or switch the summary off for one note, in that note's Details.",
        "It costs one model call per item, so a large library on a paid service is not free.",
      ],
      also: ["models", "index", "activity"],
      words:
        "concepts facets summary summaries rebuild regenerate stale old waiting meaning semantic reread re-read analyze lines",
    },
    {
      id: "hotkey",
      tab: "features",
      title: "The capture hotkey",
      voice: "Call, and I come.",
      what:
        "A key combination that opens a small capture box over whatever app you are in, so a thought is saved without leaving what you were doing.",
      need: "Optional. The plus in the pill does the same from inside Enqueue.",
      steps: [
        "Click the key shown under Capture hotkey.",
        "Press the combination you want. Use at least one of Command, Option or Control.",
        "Press Save.",
      ],
      know: [
        "In the box, Return saves, Shift Return makes a new line, Escape puts it away and keeps your words.",
        "If nothing happens, another app may already own that combination. Pick a different one.",
      ],
      also: [],
      words:
        "hotkey shortcut keyboard key combination capture quick overlay global popup summon not working",
    },
    {
      id: "link-previews",
      tab: "features",
      title: "Link previews",
      voice: "I go and look, once.",
      what:
        "When you save a link, Enqueue can fetch the page once to learn its title, its picture and its text, so the link is searchable and reads like a card instead of an address.",
      need: "On by default. Off, a saved link stays a bare address until you ask for it.",
      steps: [
        "Resolve links when you save them: one request per link, at the moment you save.",
        "Try harder on sites that block previews: on by default. A site that turns a plain request away is opened once more in Safari's engine, out of sight, with no cookies kept. A few seconds, only for those sites.",
      ],
      know: [
        "Nothing is fetched for a link you marked local only.",
        "The picture is copied onto this Mac. Nothing on the page is loaded again later.",
        "Some sites refuse everything. Those links stay without a preview.",
      ],
      also: [],
      words:
        "link links preview previews fetch resolve url website page title picture image browser safari webkit medium refused user agent article",
    },
    {
      id: "search-options",
      tab: "features",
      title: "Search options",
      voice: "Fast, or thorough. You choose.",
      what:
        "Two ways to let the model help a search. Rewrite searches as ideas restates what you typed as a few general claims, which finds notes that mean it without saying it. Let the model order results has it read the top results and put the best first.",
      need:
        "Both are off by default, because search is instant without them. Each adds one model call to a search.",
      steps: ["Turn either on, then press Save.", "Try a search you know the answer to, with and without."],
      know: [
        "Asking a question with the eye always rewrites it as ideas, whatever this is set to.",
        "Typing a note's name opens it at once and costs no search at all.",
      ],
      also: ["models"],
      words:
        "search rewrite ideas lift rank rerank order results slow faster better relevance find meaning",
    },
    {
      id: "backups",
      tab: "storage",
      title: "Backups",
      voice: "A second copy, somewhere else.",
      what:
        "A copy of your whole library, made once a day and each time you quit, into a folder you choose. Seven daily copies and four weekly ones are kept.",
      need:
        "Yes, unless you are happy to lose everything with this Mac. Your library lives in one folder on this machine and nowhere else.",
      steps: [
        "Under Backup, press Choose a folder and pick one your cloud drive keeps: iCloud Drive, Dropbox, a USB disk all work. Use Proton Drive appears when Enqueue finds it.",
        "The first copy is made at once.",
        "After that it happens by itself. Back up now, beside the time of the last copy, makes one whenever you like.",
        "Press Show recovery kit and keep the 56 letters and digits where you keep passwords, then press I saved it.",
      ],
      know: [
        "Every copy is encrypted with your library's key before it leaves this Mac, so the folder, and whoever runs your cloud drive, holds nothing readable.",
        "The recovery kit is the only way to open your backups on a new Mac. Enqueue keeps no other copy and cannot reset it.",
        "Your phone is not a backup. It holds a copy for reading, and only once sync is set up.",
        "The search index is left out of the copy and rebuilt after a restore, which takes a while.",
        "Your account key is never in a backup. It stays in the Keychain.",
      ],
      also: ["relay", "index", "trash"],
      words:
        "backup backups back up copy proton drive folder restore lose lost everything mac dies broken stolen new mac safe recover icloud dropbox recovery kit key encrypted encryption locked code",
    },
    {
      id: "drafts",
      tab: "storage",
      title: "Drafts",
      voice: "Every version, still here.",
      what:
        "Earlier versions of each note, kept as you write: one for each few minutes of writing, and how the note began. A note's drafts open from the line under it, where any one can be compared with now or put back.",
      need:
        "Nothing to set. This chooses how many are kept as they age; one note can also be switched off in its Details.",
      steps: [
        "Choose how many are kept, then press Save.",
        "Apply now removes what the choice no longer keeps at once; otherwise it happens in tonight's pass.",
        "Under a note, press its drafts to see them, compare one with now, or restore it.",
      ],
      know: [
        "Restoring a draft keeps the text it replaced as a draft, so going back never loses anything.",
        "The thinned history keeps every draft from the last day, one an hour for a week, one a day for three months, and one a week after that.",
        "Drafts travel to your phone with the note. Fewer drafts mean smaller syncs.",
      ],
      also: ["backups", "trash"],
      words:
        "drafts draft versions version history undo earlier previous restore go back older revert compare changes thin keep",
    },
    {
      id: "index",
      tab: "storage",
      title: "The search index",
      voice: "My memory of where things are.",
      what:
        "What search reads instead of your notes themselves. It is built from your library and holds nothing that cannot be made again.",
      need:
        "It keeps itself up to date. Rebuild the index is for when search looks wrong: missing things you know are there.",
      steps: [
        "Press Rebuild the index.",
        "Browsing keeps working while it runs. Search waits until it is done.",
      ],
      know: [
        "Rebuilding the index does not call a model and does not change your notes.",
        "To have everything read again, that is Summarize again, on the Assistant tab.",
      ],
      also: ["concepts", "backups"],
      words:
        "index rebuild reindex search broken missing not finding embeddings vectors storage space size derived",
    },
    {
      id: "trash",
      tab: "trash",
      title: "The trash",
      voice: "Nothing leaves in one step.",
      what:
        "Deleting moves a thing to the trash, where it waits a number of days before it is gone for good. Until then you can put it back.",
      need: "It is always on. The only choice is how long things wait.",
      steps: [
        "Set Days a deleted thing waits before it goes, then press Save.",
        "Restore puts a thing back where it was.",
        "Removing a thing from the trash, or Empty trash, cannot be undone.",
      ],
      know: ["A deleted thing leaves search and your phone at once, and comes back when restored."],
      also: ["backups"],
      words:
        "trash delete deleted remove restore undo recover bin purge empty days retention gone accident",
    },
    {
      id: "relay",
      tab: "sync",
      title: "The relay",
      voice: "A mailbox that cannot read the mail.",
      what:
        "A small server that holds your library in encrypted form so your phone can fetch it. It stores bytes it has no key for. Your Mac and your phone hold the key; the relay never does.",
      need: "Only for the phone app, or a second computer. With no relay, nothing about this Mac changes.",
      steps: [
        "Press Sign in with Google or Sign in with Apple, and finish signing in in your browser. That turns on Enqueue sync, a relay we run.",
        "If this Mac has no library key yet, you are shown a recovery phrase first. Write it down before going on.",
        "To run your own relay instead, open Use a relay of your own, paste its address, press Continue, then enter its password. Put it somewhere your phone can reach from anywhere: a relay on this Mac only works at home.",
      ],
      know: [
        "Signing in only says who you are. Your library stays locked with a key that lives on your devices, so we cannot read what Enqueue sync holds.",
        "Each phone and computer on Enqueue sync gets its own pass, listed under Devices; remove one and it stops syncing at once.",
        "Your summaries, your account key and your notes all cross it encrypted. Saved views and conversations stay on the device they were made on.",
      ],
      also: ["recovery-phrase", "sync-secret", "link-phone"],
      words:
        "relay sync enqueue sync sign in signin google apple account server host hosted url phone mobile android iphone ios devices encrypted end to end e2e railway set up setup share another device what is",
    },
    {
      id: "recovery-phrase",
      tab: "sync",
      title: "The recovery phrase",
      voice: "The one thing I cannot remember for you.",
      what:
        "A set of words that can rebuild the key your library is encrypted with. It is shown once, when sync is set up.",
      need:
        "You need it if this Mac is lost or replaced, or to bring a second computer into the same library. Day to day you never type it.",
      steps: [
        "Write it down on paper, or save it in a password manager.",
        "Tick the box to say you have it, then continue.",
      ],
      know: [
        "Nobody can recover it for you. Without it and without this Mac, what is on the relay cannot be read.",
        "Your phone never asks for it. A lost phone is simply linked again from the Mac.",
      ],
      also: ["relay", "join-library", "reset-sync"],
      words:
        "recovery phrase words seed key lost forgot forgotten new mac replaced restore unlock locked dek password",
    },
    {
      id: "sync-secret",
      tab: "sync",
      title: "The sync secret",
      voice: "The knock the door listens for.",
      what:
        "A password for the relay itself. It only decides who may store and fetch on that relay. It does not encrypt anything; the key from the recovery phrase does that.",
      need: "Only with a relay of your own; Enqueue sync needs none. Whoever runs the relay chose it when starting it.",
      steps: [
        "Enter the secret the relay was started with.",
        "Press Finish setup. It is kept in the macOS Keychain.",
      ],
      know: [
        "Every device on the library uses the same one. The phone receives it when you link it.",
        "With Enqueue sync there is no shared password: each device gets a pass of its own.",
      ],
      also: ["relay", "link-phone"],
      words: "sync secret relay password bearer token authenticate unauthorized 401 403",
    },
    {
      id: "link-phone",
      tab: "sync",
      title: "Linking a phone",
      voice: "Show it to the camera. That is all.",
      what:
        "Your phone joins your library by scanning a code on this screen. The code carries the relay's address and the key, so nothing is typed and there is no password.",
      need: "Once per phone. Sync has to be set up first, on a relay the phone can reach away from home.",
      steps: [
        "Under Link a device, press Show linking QR.",
        "On the phone, open Enqueue and press Scan the code.",
        "Point the camera at the code. The library starts arriving.",
        "Press Hide QR when it is done.",
      ],
      know: [
        "The code is a key. Do not photograph it or show it on a shared screen.",
        "It cannot be copied or pasted, on purpose. It only travels by camera.",
        "The phone reads, captures, edits notes and asks questions. Tags and views are arranged on the Mac.",
      ],
      also: ["relay", "pair-computer"],
      words:
        "link phone device mobile android iphone ios qr code scan camera pair connect add app",
    },
    {
      id: "pair-computer",
      tab: "sync",
      title: "Pairing a computer",
      voice: "Room for a second desk.",
      what:
        "Adds another computer to the same library with a one-time code, so both read and write the same notes.",
      need: "Only if you use Enqueue on more than one computer.",
      steps: [
        "Here, press Create pairing code. A code and a phrase appear.",
        "On the other computer, open Settings, Sync, and press Join.",
        "Enter this relay's address, the code and the phrase there, and press Pair this device.",
      ],
      know: [
        "The code works once and expires after ten minutes.",
        "When both computers change the same note, the later change wins.",
      ],
      also: ["join-library", "recovery-phrase"],
      words: "pair computer second mac laptop desktop another machine pairing code two computers",
    },
    {
      id: "join-library",
      tab: "sync",
      title: "Joining an existing library",
      voice: "Same shelves, another door.",
      what:
        "For a computer that should share a library already set up somewhere else. It takes the existing key instead of making a new one, so both computers can read the same notes.",
      need:
        "Only on a second computer. On your first, use Set up sync instead; joining there has nothing to join.",
      steps: [
        "Press Join existing library.",
        "Quickest: enter the Relay URL with a pairing code and phrase made on the first computer.",
        "Without the first computer at hand: enter the Relay URL, the sync secret and the recovery phrase instead.",
      ],
      know: ["Setting up sync fresh on a second computer makes a second, separate library. Join instead."],
      also: ["pair-computer", "recovery-phrase", "relay"],
      words: "join existing library second computer another mac same library import key",
    },
    {
      id: "reset-sync",
      tab: "sync",
      title: "Resetting sync",
      voice: "Think twice. I will wait.",
      what:
        "Disconnects this Mac from the relay and throws away its sync key. Your library on this Mac is not touched.",
      need:
        "Rarely: when moving to a different relay, or starting sync over. It is not a fix for a slow or failed sync.",
      steps: ["Press Reset sync and confirm.", "Set sync up again, and link each phone again."],
      know: [
        "What is on the old relay can no longer be read by anything, unless you still have its recovery phrase.",
        "Every phone has to be linked again afterwards.",
      ],
      also: ["relay", "recovery-phrase", "link-phone"],
      words: "reset sync disconnect start over unlink remove relay change relay wipe",
    },
    {
      id: "activity",
      tab: "events",
      title: "Activity",
      voice: "Everything I did, in order.",
      what:
        "A log of what Enqueue did: what was saved, what the model read and wrote, questions asked and answered, backups and syncs. It stays on this Mac.",
      need: "Only when you wonder why something happened, or whether it did.",
      steps: ["Click a row to see its full record.", "It updates by itself while it is open."],
      know: [
        "It also says what was sent to a model service and how much, never the text itself.",
        "A failed answer or summary shows here with its reason.",
      ],
      also: ["concepts", "backups"],
      words:
        "activity events log history what happened why failed error sent model usage calls diagnostics",
    },
    // ---- the phone's own settings --------------------------------------------
    {
      id: "phone-sync",
      on: ["phone"],
      tab: "phone",
      title: "Sync on this phone",
      voice: "I carry it over when I can.",
      what:
        "This phone holds a copy of your library and keeps it current through the relay. What you save or change here goes back to your Mac the same way.",
      need:
        "It runs by itself while Enqueue is open. Sync Now is for when you do not want to wait.",
      steps: [
        "Sync Now fetches anything new and sends anything waiting.",
        "Re-link with QR is for a new relay, or after sync was reset on the Mac: scan the code under Settings, Sync, on the Mac.",
      ],
      know: [
        "With no connection everything still works. Your changes wait on the phone and go out when it is back.",
        "Summaries are written on the Mac. A note saved here gets its summary once the Mac has seen it.",
      ],
      also: ["phone-ai", "phone-trash"],
      words:
        "sync syncing now relink re-link qr scan offline not updating missing notes relay stuck connection wifi",
    },
    {
      id: "app-lock",
      on: ["phone"],
      tab: "phone",
      title: "The fingerprint lock",
      voice: "A door, not a safe.",
      what:
        "Enqueue asks for your fingerprint, or your phone's screen lock, when it opens and again after a minute away.",
      need:
        "Up to you. It keeps someone holding your unlocked phone out of your notes. It does not encrypt what is stored on the phone.",
      steps: [
        "Your phone needs a screen lock first.",
        "Flip the switch and confirm with your finger.",
      ],
      know: [
        "If the sensor fails you, the phone's own PIN or pattern opens it.",
        "Quick capture from the home screen still works while locked. It can only add a thought, never show one.",
      ],
      also: ["phone-sync"],
      words: "lock fingerprint biometric pin privacy secure open unlock face screen lock protect",
    },
    {
      id: "phone-ai",
      on: ["phone"],
      tab: "phone",
      title: "AI on this phone",
      voice: "Same bird, borrowed keys.",
      what:
        "The phone answers questions with the same model service your Mac uses. The service, the model and the key are set on the Mac and arrive here encrypted.",
      need: "Nothing to set here. Change it on the Mac and it follows.",
      steps: [
        "On the Mac: Settings, AI.",
        "Choose the service and model, save the key. The phone picks it up at its next sync.",
      ],
      know: [
        "A model that runs on the Mac itself cannot answer for the phone. Asking here needs a service.",
        "The phone finds notes for an answer by their words. Finding by meaning happens on the Mac.",
      ],
      also: ["phone-sync"],
      words:
        "ai model key api answers ask eye not answering managed desktop backend service change",
    },
    {
      id: "phone-trash",
      on: ["phone"],
      tab: "phone",
      title: "The trash",
      voice: "Nothing leaves in one step.",
      what:
        "Deleting moves a thing here, where it waits before it is gone for good. Until then you can put it back.",
      need: "It is always on. How long things wait is set on the Mac.",
      steps: ["Restore puts a thing back.", "Empty trash removes everything in it, for good."],
      know: ["A thing deleted here leaves your Mac too, and comes back on both when restored."],
      also: ["phone-sync"],
      words: "trash delete deleted restore undo recover empty gone accident bin",
    },
    {
      id: "phone-activity",
      on: ["phone"],
      tab: "phone",
      title: "Activity",
      voice: "Everything I did, in order.",
      what:
        "A log of what Enqueue did on this phone: what was saved, questions asked and answered, and each sync. It stays on the phone.",
      need: "Only when you wonder why something happened, or whether it did.",
      steps: ["Tap a row for its full record.", "Refresh reads it again."],
      know: ["A question that failed shows here with the reason the service gave."],
      also: ["phone-sync", "phone-ai"],
      words: "activity events log history failed error why happened record",
    },
  ];

  // A guide belongs to the desktop unless it says otherwise: its steps name what is
  // on that app's screen.
  for (const g of LIST) if (!g.on) g.on = ["desktop"];

  const BY_ID = Object.fromEntries(LIST.map((g) => [g.id, g]));

  function get(id) {
    return BY_ID[id] || null;
  }

  function all(platform) {
    return LIST.filter((g) => !platform || g.on.includes(platform));
  }

  // Which "left to set up" step speaks for a guide.
  const STEP_OF = {
    answers: "model",
    "api-key": "model",
    backups: "backup",
    relay: "phone",
    "link-phone": "phone",
    "sync-secret": "phone",
    "phone-sync": "phone-sync",
    "app-lock": "app-lock",
  };

  // Where this installation stands on a guide: the alerts about it first (something
  // needs a look), then its step. Null when there is nothing to say.
  function stand(id, setup) {
    if (!setup) return null;
    const alert = (setup.alerts || []).find((a) => a.guide === id);
    if (alert) return { level: alert.level, text: alert.text };
    const step = (setup.steps || []).find((s) => s.id === STEP_OF[id]);
    if (!step) return null;
    if (step.state === "done") return { level: "done", text: step.detail || "Set up" };
    return { level: step.state, text: step.detail || "Not set up yet" };
  }

  // ---- matching, in the page ----------------------------------------------
  // Words that say nothing about which guide is wanted.
  const FILLER = new Set(
    (
      "a an the i my me we you your is are was be do does did can could should would will how what " +
      "why when where which who to of in on at for with from by it its this that these those and or " +
      "but if so not no any some about into up out as have has had need get got use using make want " +
      "there here just really please tell explain mean means work works enqueue app setting settings"
    ).split(" "),
  );

  function words(text) {
    return String(text || "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, " ")
      .split(" ")
      .filter((w) => w.length > 1 && !FILLER.has(w));
  }

  // A typed word matches a guide word when they are the same, or one begins the
  // other ("backup" and "backups", "rel" while "relay" is being typed).
  function hit(typed, word) {
    if (typed === word) return 1;
    if (typed.length >= 3 && word.startsWith(typed)) return 0.8;
    if (word.length >= 4 && typed.startsWith(word)) return 0.7;
    return 0;
  }

  const BAGS = LIST.map((g) => ({
    guide: g,
    title: words(g.title),
    asks: words(g.words),
    body: words([g.what, g.need, g.steps.join(" "), g.know.join(" ")].join(" ")),
  }));

  function best(typed, bag) {
    let top = 0;
    for (const w of bag) {
      const h = hit(typed, w);
      if (h > top) top = h;
      if (top === 1) break;
    }
    return top;
  }

  // A match this strong, for each word typed, is the guide that was asked for: the eye
  // opens it without asking a model. Anything weaker is offered, not assumed. 3.2 is a
  // typed word that begins a word of the title ("backup" for Backups); a word found
  // only among the ways people ask scores 3 and is not enough by itself.
  const STRONG = 3.2;

  // Guides ranked against what was typed. `tab` gives the guides of the tab on screen
  // a small edge, which settles a tie in favour of where the person is looking.
  function match(text, opts) {
    const typed = words(text);
    if (!typed.length) return [];
    const o = opts || {};
    const out = [];
    for (const b of BAGS) {
      const g = b.guide;
      if (o.platform && !g.on.includes(o.platform)) continue;
      let score = 0;
      let matched = 0;
      for (const t of typed) {
        const s = Math.max(best(t, b.title) * 4, best(t, b.asks) * 3, best(t, b.body) * 1);
        if (s > 0) matched++;
        score += s;
      }
      if (!matched) continue;
      // Every typed word found somewhere in the guide counts for more than a few
      // of them found strongly.
      score *= 0.6 + 0.4 * (matched / typed.length);
      if (o.tab && g.tab === o.tab) score += 0.5;
      out.push({ guide: g, score, per: score / typed.length });
    }
    out.sort((a, b) => b.score - a.score);
    return out;
  }

  // Whether the first match is clearly the one: strong, and well ahead of the next.
  function sure(matches) {
    if (!matches.length || matches[0].per < STRONG) return false;
    return matches.length === 1 || matches[0].score >= matches[1].score * 1.25;
  }

  function text(g) {
    return [
      g.what,
      "Do you need it: " + g.need,
      "Steps: " + g.steps.map((s, i) => i + 1 + ". " + s).join(" "),
      "Good to know: " + g.know.join(" "),
    ].join("\n");
  }

  function escHtml(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  }

  // A guide's body, as the markup both apps put inside the plate (css/guide.css).
  // `where` is Guides.stand(...) or null.
  function html(g, where) {
    const sec = (label, inner) =>
      '<div class="dsec"><div class="dsec-head"><span class="dsec-label">' +
      label +
      "</span></div>" +
      inner +
      "</div>";
    const also = g.also.map(get).filter(Boolean);
    return (
      sec("What it is", '<p class="gtext">' + escHtml(g.what) + "</p>") +
      sec(
        "Do you need it",
        '<p class="gtext">' +
          escHtml(g.need) +
          "</p>" +
          (where
            ? '<p class="gstand" data-level="' + escHtml(where.level) + '">' + escHtml(where.text) + "</p>"
            : ""),
      ) +
      sec("How", '<ol class="gsteps">' + g.steps.map((s) => "<li>" + escHtml(s) + "</li>").join("") + "</ol>") +
      sec(
        "Good to know",
        '<ul class="gknow">' + g.know.map((s) => "<li>" + escHtml(s) + "</li>").join("") + "</ul>",
      ) +
      (also.length
        ? sec(
            "Goes with",
            '<div class="galso">' +
              also
                .map(
                  (o) =>
                    '<button type="button" class="gchip" data-guide="' +
                    escHtml(o.id) +
                    '">' +
                    escHtml(o.title) +
                    "</button>",
                )
                .join("") +
              "</div>",
          )
        : "")
    );
  }

  // The ? itself, drawn once for both apps.
  const MARK =
    '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/>' +
    '<path d="M9.4 9.5a2.7 2.7 0 1 1 4 2.3c-.9.5-1.4 1-1.4 2"/><path d="M12 17v.2"/></svg>';

  function mark(id, open) {
    const g = get(id);
    if (!g) return "";
    return (
      '<button type="button" class="gmark" data-guide="' +
      escHtml(id) +
      '" aria-expanded="' +
      String(!!open) +
      '" aria-label="About ' +
      escHtml(g.title.replace(/^The /, "the ")) +
      '" title="What is this?">' +
      MARK +
      "</button>"
    );
  }

  return { get, all, stand, match, sure, text, html, mark, STRONG, LIST };
})();

if (typeof module !== "undefined") module.exports = Guides;
