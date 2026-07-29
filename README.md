# Enqueue

**Save anything. Sort it out later, or never.**

Enqueue is a place to put things you want to keep: articles, PDFs, screenshots, links, and notes you write yourself. Saving takes one action and asks you nothing — no folder, no tag, no title, no reason. The organising happens afterwards, when you actually need it, and mostly the app does it for you.

It runs entirely on your own Mac. Nothing is uploaded anywhere unless you deliberately turn that on.

---

## The idea in one paragraph

Most tools that hold your stuff make you file it at the moment you save it. That is the worst possible moment, because you do not yet know why the thing matters. So people either stop saving, or they save into a pile they never open again.

Enqueue takes the opposite bet. Saving is free and instant. Later, when a subject is actually on your mind, you ask for it — and the app pulls together everything that speaks to that subject, **including things that never used those words**. An article about hand-built furniture can turn up when you ask about resilience, because the app has worked out what the article is *an example of*, not just what it is *about*.

---

## Getting it running

From a terminal, in the project folder:

```bash
bin/relaunch
```

That starts the engine and opens the window. The first time, or after changing the desktop code:

```bash
bin/relaunch --build
```

The window can take a few seconds the first time. If nothing appears, it may have opened behind whatever you were looking at — check your Dock.

**Two parts, one app.** There is a background "engine" that stores everything, and a window that shows it. `bin/relaunch` starts both together and shuts both down together, so you never have to think about it.

---

## The window

The screen is deliberately bare. There is no toolbar and no menu bar of its own.

### The wall

Everything you have saved, newest first, as a grid of squares. Each square shows the thing itself:

- a **PDF** shows its first page
- an **image** shows the image
- a **note** shows its own opening words
- a **link** shows the site's picture, or its address if there is none

Headings break the wall up by time: **Today**, **Yesterday**, **Earlier this week**, **Last week**, **Earlier this month**, then by month and year. This is how people actually remember saving something — "a couple of weeks ago" — so it is how the wall is arranged.

You can also sort by **last touched** or **by name** using the small controls at the top.

### The pill

The small floating control at the bottom is the only set of buttons in the app. It has three:

| Button | What it does |
|---|---|
| **+** | Save something |
| **magnifying glass** | Search for something you can name |
| **eye** | Ask a question about what you have saved |

When you are *inside* a saved thing, the **+** becomes a **back arrow** and the magnifying glass disappears — searching your whole collection from inside one document is not what you want there. Use **⌘F** to find words inside the thing in front of you.

### The sidebar

On the left: **Everything** (back to the wall), your **Conversations**, and at the bottom **Trash** and **Settings**. On a narrow window the sidebar tucks away, and the leftmost button on the pill brings it back.

---

## Saving things

Press **+** and pick one of four:

| | What happens |
|---|---|
| **Note** | Opens a blank page you type into. It is yours and you can edit it forever. |
| **Upload** | Pick any file. PDFs, images, text files, anything. |
| **Link** | Paste a web address. |
| **Image** | Same as Upload, filtered to pictures. |

Saving never makes you wait. The app confirms with a small **"Saved."** at the bottom, and if something goes wrong it says so and keeps what you typed so you do not lose it.

### Two kinds of thing

This distinction runs through the whole app, so it is worth knowing.

**Notes are yours.** You wrote them, you can rewrite them, and every version you have ever saved is kept. Nothing you write is ever destroyed, even when you delete the words.

**Everything else came from the world.** A PDF, an image, a saved link — kept exactly as it arrived, and not editable. That is the point: the reason to save an article is that it says what it says. To add your own thoughts, there is a **"Your note on this"** box underneath, which *is* yours and editable.

---

## Reading things

**PDFs open in the app.** Pages load as you scroll, and a counter in the corner shows where you are. Press **⌘F** to search the text inside — it reports how many matches there are, jumps between them, and marks the page each one is on. **Enter** for the next, **Shift+Enter** for the previous.

**Text files show their contents.** Anything that is not readable text says so plainly rather than showing an empty box — file name, type, size, and confirmation that it is safely stored.

**Links start out as just an address.** Saving a link deliberately does *not* visit the page (see [Privacy](#privacy)). When you want the title, description, and picture, press **Fetch a preview**. The button tells you what it costs: one request to that site.

Some sites refuse. Wikipedia will not serve a program that does not identify itself with a contact address. The app says so, and Settings is where you fix it.

---

## Finding things

Three ways, different on purpose.

### Search — for things you can name

The magnifying glass. Use it when you know roughly what you want: a phrase, a title, a name. Instant, and entirely on your machine.

### Ask — for things you cannot name

The eye. This starts a **conversation** with your collection. Ask in ordinary language, get an answer built from what you actually saved, with the sources listed underneath — click any to open it.

The important part: **if your collection does not hold the answer, it says so.** It will not quietly answer from general knowledge and dress it up as something you saved. When you see sources under an answer, they are real.

Conversations are kept in the sidebar. Click the star to pin one to the top.

**Scope.** Press the eye while looking at one document and the conversation reads only *that document*. The app says so at the top — "reading only …" — with a link to widen it. This is what makes "ask about this PDF" fast.

### Rooms — for a subject you want gathered

As a conversation goes on, the app works out which concepts you are circling and offers them under **"Make a room from:"**. Click one and it gathers everything in your collection belonging to that idea, with a short note on each explaining why it is there.

This is the part that is not just search: things turn up for what they *demonstrate*, not the words they use. Press **Keep this room** to save it.

Rooms are slow — a minute or more — because the app reads each candidate properly rather than matching words.

---

## Deleting things

Nothing in Enqueue expires on its own. Nothing is removed for being old or unread. The only thing that ever leaves is something you delete.

Deleting is two steps:

1. Press the **bin icon** next to a thing's title. It leaves the wall and stops appearing in searches and answers immediately.
2. It waits in **Trash** for **30 days**, showing how long it has left. **Put back** restores it completely.

After that it is destroyed for good. You can change the window in Settings — the minimum is one day, because a delete you cannot undo is not something this app will do in a single click.

**Delete now** in the Trash destroys something immediately. It is the only action in Enqueue that cannot be undone, and the only one that asks you to confirm.

---

## Settings

The gear at the bottom of the sidebar.

**The model.** Which AI answers your questions. Out of the box it is a model running on your own machine, so nothing leaves. You can switch to **OpenRouter**, **OpenAI**, or another compatible service. The screen says plainly which choice sends your text elsewhere and which does not.

An outside service needs an API key, set as an environment variable rather than typed into the app. There is deliberately no box for it: this file sits in plain text on your disk, and a password written in plain text is not a password. Settings tells you whether a key is present.

**Capture hotkey.** Click the box, press the combination you want. Shown the way your keyboard is labelled — ⌥⇧E, not "Alt+Shift+E".

**User agent for link previews.** How the app introduces itself to websites. Some require a contact address before they will answer.

**The trash.** How many days deleted things wait.

**Where everything lives.** The folder on your disk, how much space each part uses, how many things you have. **Rebuild the index** throws away everything the machine worked out and works it out again — useful if search seems wrong. It never touches anything you wrote.

---

## Privacy

Not a feature bolted on; it is why several things work the way they do.

**Everything is on your machine.** The database, your files, and the search index live in a folder in your home directory. The app listens only on your own computer.

**Saving a link does not visit it.** If it did, every site you saved would learn you were interested, whether or not you went back. So a link is stored as text until you press **Fetch a preview**.

**Preview pictures are downloaded, not linked.** When you do fetch one, the picture is copied onto your machine. If the app merely pointed at the original, that site would hear from you *every time* you looked at the card, forever — worse than the one visit it was avoiding.

**Passwords and keys are noticed.** Everything saved is scanned for things that look like credentials. Anything that trips the scan is held back from every AI model, and the app tells you on the item.

**Local only.** A thing marked local-only never goes to an outside service, even when one is configured.

---

## Keyboard

| | |
|---|---|
| **⌥⇧E** | Save from anywhere (configurable; the window it opens is still being built) |
| **⌘F** | Find inside a PDF |
| **Enter / Shift+Enter** | Next / previous match |
| **Esc** | Close whatever just opened |
| **⌘S** | Save a note now (it also saves on its own) |
| **⌘B / ⌘I** | Bold / italic while writing |

While writing a note, markdown shorthand becomes formatting as you type: `# ` for a heading, `- ` for a bullet, `> ` for a quote.

---

## When something looks wrong

**The window did not appear.** It may have opened behind another window — check the Dock. `bin/relaunch` brings it to the front.

**An answer says nothing was found, but you know you saved something.** Check the line under the conversation's title. If it says "reading only …", the conversation is locked to one document — click **ask everything instead**.

**Search is not finding something recent.** Give it a few seconds; things are processed just after saving. If it persists, use **Rebuild the index**.

**A link preview failed.** The reason is under the button. Most often a site refusing a program that has not identified itself — set a user agent with a contact address in Settings.

**A room came back nearly empty.** The screen says whether your collection was thin or the AI failed. With the small local model, the AI failing is common; a better model fixes it.

---

## Honest limitations

Enqueue is early. These are known, not hidden:

- **The built-in AI is weak.** It runs locally and free, and it is not very good — roughly three of four attempts fail their quality checks when building a room. Conversations are fine; rooms are unreliable. Pointing it at a better model fixes this.
- **The global save hotkey is not built yet.** The setting exists; the window it opens does not.
- **The wall shows your most recent 120 things** and does not yet page beyond that.
- **There is no sync.** One machine only, for now.
- **There is no phone app.**
- **Rooms take a minute or more.**

---

## Where your things actually are

Everything lives in `~/.enqueue-poc`:

| | |
|---|---|
| `enqueue.db` | Every note, link, conversation, and version |
| `blobs/` | Your original files, unmodified |
| `qdrant-local/` | The search index (rebuildable; safe to throw away) |
| `settings.json` | Your preferences |

To back Enqueue up, copy that folder. Your original files are in there byte for byte, so they stay readable by other programs even if Enqueue disappears.
