# Enqueue manual

How to use Enqueue, on the Mac and on the phone (Android and iPhone).
The engineering side (the code, how it fits together, every command) is [AGENTS.md](../AGENTS.md).

- [The idea](#the-idea)
- [Getting it running](#getting-it-running)
- [Capturing](#capturing)
- [The library](#the-library)
- [Notes](#notes)
- [Links, PDFs, images and files](#links-pdfs-images-and-files)
- [Finding things](#finding-things)
- [Asking](#asking)
- [Summaries](#summaries)
- [Tags and views](#tags-and-views)
- [Trash](#trash)
- [The vault](#the-vault)
- [The phone](#the-phone)
- [Sync](#sync)
- [Your own relay](#your-own-relay)
- [Backups](#backups)
- [Privacy and encryption](#privacy-and-encryption)
- [Settings reference](#settings-reference)
- [When something goes wrong](#when-something-goes-wrong)

---

## The idea

Save first, organise never.
You capture a thing the moment you meet it, without choosing a folder, a tag, or a title.
Later, when a subject is on your mind, you search or ask, and Enqueue brings back everything that speaks to it, including things that never used your words.

Everything you save is an **artifact**: a note, a link, a PDF, an image, or a file.
The **?** at the top right of the home page (and of the phone's library) opens a seven-card tour of all this, with small demos you can try; nothing typed there is saved.
Your library lives on your Mac, in one folder (`~/Library/Application Support/Enqueue`).

## Getting it running

Enqueue runs from its source for now: there is no app to download yet.
You need a Mac, and the code (`git clone`, then `cd enqueue`).

- **The Mac app.** Run `bin/setup` once (it installs what is missing and changes nothing that is there), then `bin/launch desktop`. The window opens when the engine is ready.
- **An Android phone.** Turn on USB debugging, plug it in, run `bin/setup --android` once, then `bin/launch mobile`. It installs the app and starts it; unplug and it keeps working.
- **An iPhone.** Run `bin/setup --ios` once (it needs Xcode), plug the iPhone in, then `bin/launch ios`. `bin/launch simulator` runs it in the iOS Simulator instead, which has no camera, so linking needs a real phone.
- **A model.** Search and capture work without one. For summaries and answers, run [Ollama](https://ollama.com/) on the Mac, or choose an online one in **Settings > Assistant**.

Then link the phone to the Mac: see [Sync](#sync).

## Capturing

### From anywhere on the Mac

Press **Option+Shift+E**.
A small window appears over whatever you are doing.

- Type a thought and press **Enter**: it is saved as a note.
- Paste a web address: it is saved as a link.
- Paste an address with a few words beside it: a link, with your words as its note.
- Drop a file or an image on it: it is saved as it is.
- **Shift+Enter** adds a new line. **Esc** closes the window and keeps your draft for next time.

The raven flies off with it, the window closes, and you are back where you were.
You can change the shortcut in Settings > Capture.

### Inside the app

- The purple **+** in the bottom pill offers **Note**, **Upload**, **Link** and **Image**.
- Drop files anywhere on the window.

### On the phone

- **+ > Note** opens a page to write on.
- **+ > Link**, **Upload** and **Camera** save a link, a file from the phone, or a photo.
- Long-press the app icon and choose **Quick capture** for a one-thought box that floats over whatever app you are in.

Capturing never waits: the thing is saved at once, and the reading, summarising and indexing happen behind it.

## The library

The home screen is the wall: everything you saved, the most recently touched first.

- **Saved** is what you starred. Star an artifact to keep it at the top.
- **Everything else** is the rest.
- The tabs above the wall regroup it: **Last touch**, **Type**, **Tags**, and **Custom** (your views).
- Click a tile to open it.

The greeting changes through the day, and so does the colour of the page: lavender by day, deeper at night.

## Notes

A note is the one kind of artifact you can keep editing.

- Open a note and type. There is no edit mode and no Save button.
- It saves as you type, a moment after you pause, and "Saved" appears beside the date.
- Every earlier version is kept. Nothing you wrote is destroyed by a later edit.
- The first line is the note's title, unless you give it one of your own by clicking the title.

Markdown works as you type:

| Type | Get |
| --- | --- |
| `- ` or `* ` at the start of a line | a bullet |
| `1. ` | a numbered list |
| `# `, `## `, `### ` | a heading |
| `> ` | a quote |
| three backticks | a code block |
| `**bold**`, `*italic*`, `` `code` `` | bold, italic, code |

In a list:

- **Tab** nests an item under the one above. **Shift+Tab** moves it back out.
- **Enter** on an empty item moves it out one level; at the top level it leaves the list.
- **Cmd+B** and **Cmd+I** make bold and italic. **Cmd+S** saves right now.

Pasting an image into a note puts the image in the note.

On the phone, tap anywhere in a note to write there.
The toolbar above the keyboard makes bullets, numbered lists and headings, and indents.

### Tabs

A note can be split into named tabs, for a note with parts: the steps, the prompt, the candidates.
The last button on the formatting bar adds one; the first press turns what you had into a tab called "Notes" and opens a new one, its name ready to type.
- Click a tab to open it. Double-click it to rename it. Drag it to move it.
- On the open tab, two small buttons appear: make it its own note, and delete (its text stays in the note's drafts).
- Deleting down to one tab makes it a plain note again.
- A search that matches words in a tab opens the note on that tab.

On the phone, tap a tab or swipe the text sideways.
In the writing page, the tool bar adds a tab, and a long press on a tab renames it, makes it its own note or deletes it. Tabs are moved on the Mac.

### Drafts

Enqueue keeps drafts of a note as you write: how it began, one for each five minutes of writing, and the latest.
- **"12 drafts"** under the note opens the list, each with what it changed.
- Choose one to see the note with what was added since in green and what was removed struck in red, or **As it was**.
- **Restore** puts it back. The text it replaces is kept as a draft, so going back loses nothing.
- **Keep drafts of this note**, in the list and in Details, turns drafts off for one note (a scratch pad, a log). Off removes its earlier drafts.
- **Settings > Library > Drafts** decides how many are kept as they age: thinned (everything from today, then one an hour for a week, one a day for 90 days, one a week after), the last 30 days, or none.

On the phone, Details shows the drafts and the switch; the list and the comparison work the same way.

## Links, PDFs, images and files

These are **captures**: kept exactly as they were, never edited.
What you can add to a capture is your own note about it, in the box under it.
Your note is searchable, and it shapes the summary.

- **Links.** Saving a link fetches its page once, to learn its title, picture and text, so you can find it by what it says. Nothing remote is ever loaded afterwards: the picture is stored on your Mac. Click the address to open the page in your browser.
- **A site that refuses.** Some sites turn away anything that is not a browser. The page says so under your note. Turn on **Try harder on sites that block previews** in Settings > Capture and press **Try again** to have a hidden browser open it once.
- **PDFs** open in a reader with find-in-document. Their text is searchable page by page.
- **Images** are described by the vision model, when one is set, so you can find a photo by what is in it.
- **Files** (text, markdown, CSV, JSON, HTML) are read and indexed. Anything else is kept and downloadable.

An artifact flagged **local only** never has its text sent to an outside model, whatever backend is configured, and a local-only link is never fetched.
There is no button for the flag in the app yet; it is set through the engine's API (`PATCH /artifacts/{id}` with `local_only`).

## Finding things

Press **Cmd+K**, or click the search box, and type.

Search looks in three ways at once:

- **Your words.** Exact words, parts of words ("hydro" finds "hydroponics"), small typos, and a phrase in quotes for an exact match.
- **Your meaning.** A paraphrase finds a note that shares none of its words.
- **The idea.** Each artifact carries a model-written summary of what it could be an example of, so "things that gain from stress" can find a note about lifting weights and a PDF about forests.

As you type, the artifacts your words could be naming drop down under the search box, straight away and without running a search.
Press **Enter** on one to open it; the arrow keys move between them, and the last row runs the full search instead.
A small slip in the spelling still finds the name ("mesopotamai"); it is offered in the list, and Enter stays on the full search until you pick it.
When your words clearly name one thing it is already picked, so typing part of a name and pressing Enter opens it.
On the phone the same name matches lead the results as you type.
Typing an artifact's name finds that artifact first, ahead of anything that only resembles it.
Results never wait long on the model: when it is slow, the results it has not checked yet are shown last, under a line that says so, and the same search is exact the next time.

If you never saved anything about a subject, the answer is **nothing found**, not a wall of loosely related things.

### Finding a word inside one artifact

With an artifact open, press **Cmd+F** (Ctrl+F) and type.
Every match on the page is marked, **Enter** goes to the next one and **Shift+Enter** to the one before, and **Esc** closes it.
Text you had selected is searched for straight away.
It works in a note, in your notes on a link or image, in a text file, and across the pages of a PDF.

## Asking

Click the **eye** and ask a question in plain words.

- The answer is written from your own library and names the artifacts it used. Click one to open it.
- If nothing you saved answers the question, it says so rather than guessing.
- A question is a conversation: ask a follow-up and it keeps the thread.
- From an open artifact, the eye asks about that one thing.
- Conversations are kept, and sync to your phone.

The eye is also a little alive.
It follows the pointer, blinks, and approves when something is saved.

## Summaries

Open an artifact and click the **circled i** to open its Details panel: tags, views, the summary, and passages that connect to other artifacts.
The page slides aside so the panel never covers what you are reading.
The **Summary** is a handful of lines the model wrote about what the artifact says and what it is an example of.
These lines are what let search find it by idea.

- Click a line to rewrite it, or **Add a line** to write your own.
- Remove a line you disagree with.
- The round arrow writes the machine's lines again; the lines you wrote or edited are kept.

Short notes, and anything holding what looks like a password or a key, get no summary.
A long summary scrolls inside its own box, so the rest of the panel stays in reach.

## Related

Under an artifact, **Related** lists up to five others, each with the reason it is there.
There are three kinds of link:

- **The same subject.** The reason is the other artifact's own "what it is about" line.
- **The same name.** Both mention the same person, place or thing: "Both mention Yosemite."
- **The same point, from another field.** A book on statecraft beside one on war, because both say incentives predict behaviour better than character. The reason is one plain sentence beginning "Both".

Nothing is invented to fill the list.
A same-point link only appears after the model has read the pair and agreed that they make the same point; a pair it has not judged yet, or said no to, is not shown.
If the model is out of usage or unreachable, the other two kinds still work, and the waiting pairs are judged on their own once it is back.
Each pair is judged once and remembered.
Judging runs quietly in the background, at most 40 notes a day, so it can never use up your model allowance; a whole library is worked through over several days.
An artifact marked local-only is only ever judged by the model on your computer.
Click a related artifact to open it.
Related is shown on the desktop only.

## Tags and views

Tags are optional, and always added after the fact, in the Details panel.

A **view** is a saved way of looking at the library: "everything about the Lisbon trip", "recipes I have actually cooked".
There are two ways to make one.

**Arrange it yourself.** Open the **Custom** tab and click **New view**.

- **Add a header** makes a shelf; click its name to rename it.
- The **Add** tile at the end of a shelf opens your library: tick as many things as you want and add them together.
- Drag a tile to reorder it, or onto another shelf to move it. Drag a header by its grip (the six dots that appear beside it) to reorder the shelves.
- Without a mouse: the arrows button on a tile moves it to another header, Alt+Left/Right moves it along its shelf, and the up and down arrow keys move a focused grip.
- The **x** on a tile takes it out of the view. The bin on a header deletes the shelf. Nothing leaves your library.

Everything saves as you go, nothing here ever calls a model, and the view shows on your phone in the same order.

**Let the assistant gather it.**
Ask the eye to organise something ("gather everything about the Lisbon trip"), and it lays the matching artifacts out in groups; save that as a view.
Saved views live under the **Custom** tab.
An assistant view stays as it was gathered until you click **Rebuild**, which gathers it again from the library as it is now.
Removing a tile from one puts it on a **Removed** shelf at the bottom, where **restore** brings it back.
If you would rather take one over, **Arrange by hand** makes a copy that is yours to rearrange.

Either kind can be renamed or forgotten from the Custom tab, and an artifact's Details panel has **Add to a view**.

## Trash

Deleting is never one keystroke away from gone.

- The bin on an artifact moves it to the trash. It leaves every screen at once.
- It waits there for 30 days (you can change that in Settings > Trash), and can be restored whole.
- After that it is destroyed for good. You can also empty the trash yourself.

## The vault

For the few things you want hidden even from someone holding your unlocked Mac.

- The **lock** on an artifact moves it into the vault. It disappears from the wall, from search, and from answers.
- In the vault it is encrypted with a key made from a 6-digit PIN that only you know. It stays encrypted when it syncs: your other device holds it, and still cannot read it without the PIN.
- The door is deliberately unmarked: **Settings > Activity > Diagnostics**. The first time, you choose the PIN. A wrong PIN looks like a diagnostic that failed.
- The vault locks itself again after a few idle minutes, and whenever you leave it.
- On the phone, the **Open with fingerprint** switch inside the vault lets a fingerprint open it instead of the PIN. The vault offers it once, right after the PIN opens it or locks an item away. With it on, locking an item away asks for your fingerprint; with it off, the PIN. The PIN always still works. Adding a new fingerprint to the phone, or changing the PIN on another device, turns this off until you enter the PIN again.

There is no way to recover a forgotten vault PIN.

## The phone

The phone app (Android and iPhone) is your library in your pocket: read, capture, write, ask.

- **Reading.** Rows open to the note, the image (pinch to zoom), the link's preview, or the PDF.
- **Writing.** Tap a note to write in it. **+ > Note** starts a new one. Both save as you type.
- **Tabs and drafts.** A note's tabs show one at a time; its drafts are in Details. See [Notes](#notes).
- **Asking.** The eye answers from the copy on the phone.
- **Small edits.** Star, delete, restore, and rewrite a summary line. Tagging and views are for the desk.
- **Offline.** Everything is on the phone and saves there first. What you did reaches your Mac when there is a connection again.
- **Fingerprint lock (Android).** The switch in **Settings > Lock** makes Enqueue ask for your fingerprint when it opens, and again after a minute away. Your phone's own screen lock works too. Enqueue offers it once the first time you open the library; turning it off asks you to confirm. Quick capture from the home screen still works without it, since it can only add a thought.

The phone does not write summaries or build the search index itself; those come from the Mac through sync.

## Sync

Sync keeps the Mac and the phone the same, through a small relay server.
The relay only ever stores scrambled data: everything is encrypted on your device before it leaves, with a key the relay never sees.

To link a phone:

1. On the Mac, open **Settings > Sync** and press **Sign in with Google** or **Sign in with Apple**. That turns on Enqueue sync, a relay we run. The first time, the Mac shows a recovery phrase to write down before the sign-in opens in your browser.
2. Press **Show the code**. The Mac shows a QR code.
3. In the phone app, scan it. The phone downloads your library.

Signing in only says who you are. Your library is locked with a key that stays on your devices, so we cannot read what Enqueue sync holds.
Every phone and computer gets a pass of its own, listed under **Devices**: remove one and it stops syncing at once.
To use a relay you run yourself instead, open **Use a relay of your own** on the same screen (see [Your own relay](#your-own-relay)).

There is nothing to type on the phone.
If you lose the phone, remove it under **Devices** and link the new one the same way.
Your model settings travel too, so the phone can answer questions without being set up separately.

## Your own relay

The relay is a small server that passes your library between your devices.
It only ever holds scrambled copies it cannot read, so it can run anywhere: a cheap cloud service, a spare computer, a Raspberry Pi.
Your phone has to reach it from outside your home, so it needs an `https://` address.

- **On a cloud service.** The repo deploys it to Railway with `bin/deploy-relay`. Any host that runs a Python service works: start it with `enq relay --host 0.0.0.0 --port <port> --secret <a long random secret>`, behind something that gives it `https://` (Caddy, nginx, the host's own TLS).
- **On a disk that lasts.** Point `RELAY_DATA_DIR` at storage that survives a restart.
- **For a quick test.** `enq relay` on the Mac, plus a tunnel (`cloudflared tunnel --url http://127.0.0.1:8788`) that prints a public `https://` address. Fine for trying it; not for every day.

The secret is the relay's password: only devices that know it can use the relay.
Settings refuses to show the linking code for a relay on this Mac or your home network, since a phone that leaves the house could not reach it.

## Backups

Keep a copy of the whole library in your cloud drive, in case the Mac is lost.

1. Open **Settings > Library**.
2. Under **Backup**, click **Use Proton Drive** (shown when Proton Drive is installed), or type another folder that a cloud drive syncs.

From then on a backup is made once a day and when you quit, whenever something changed.
The last 7 days are kept, and one a week for the 4 weeks before.
**Back up now** makes one at once.

Every backup is encrypted with your library's own key before it leaves the Mac, so the folder, and whoever runs your cloud drive, holds nothing anyone can read.

**Save your recovery kit.**
Under Backup, **Show recovery kit** shows 56 letters and digits.
Keep them where you keep passwords, then click **I saved it**.
On a new Mac the recovery kit is the only way to open your backups: Enqueue keeps no other copy, and nobody can reset it.

A backup is small, because the search index is left out; it is rebuilt when you restore.

To restore, on a new Mac or after a mistake: quit Enqueue, then run

```bash
enq restore "~/Library/CloudStorage/ProtonDrive-.../"
```

On a new Mac it asks for the recovery kit.
Your current library is set aside, never deleted.
Start Enqueue again and it rebuilds the search index; browsing works meanwhile, and search returns when it is done.

Your model API key is not in the backup (it lives in the Mac's Keychain); enter it again in Settings.

## Privacy and encryption

Nobody but you can read your library: not the relay, not your cloud drive, not us.
There is no password reset either, because nobody else holds a key.

- **On the Mac.** Once you have saved your recovery kit, the library itself is encrypted (the next time Enqueue starts). The original files you saved are protected by your Mac's own disk encryption (FileVault).
- **On the phone.** The library copy, its settings and its cached files are encrypted with a key that never leaves the phone: the Android Keystore, or the iPhone's Keychain (kept on that phone only). Lose the phone and link a new one; the Mac has everything.
- **In backups.** Every file is encrypted before it reaches the folder.
- **Through the relay.** Everything is encrypted on your device first. The relay sees only how many things there are, roughly how big (sizes are rounded up), and when they change.
- **The recovery kit** (**Settings > Library**) is 56 letters and digits. It opens your backups and your library on a new Mac, and brings sync back with them. Keep it where you keep passwords: without it, a lost Mac means a lost library.

### Models

Enqueue needs a language model for three things: summaries, answers, and gathering views.
Search and capture work without one.

- **Ollama** (the default) runs the model on your Mac. Nothing leaves it.
- **OpenRouter** or **OpenCode Go** use a model on someone else's computer. The text of the artifacts involved is sent there. An artifact marked **local only** never is.

Choose in **Settings > Assistant**: where answers come from, and your account key for an online assistant. The model for each job is under **More options**.
The key is stored in the macOS Keychain, never in a file.

If the provider says your usage limit is reached, Enqueue pauses its model calls until the limit resets and then carries on by itself.
Entering a different key lifts the pause at once.

What always stays on the Mac: the library, the search index, and the embeddings that power search by meaning.
What can leave, only if you set it up: text sent to an outside model, encrypted sync through the relay, and the backup in your cloud drive.

## Settings reference

| Tab | What is there |
| --- | --- |
| **Assistant** | Where answers come from, your account key, summaries; under More options the model for each job and retries. |
| **Capture** | The capture shortcut, link previews, search by idea and ranking. |
| **Library** | Backups and the recovery kit, drafts, space used; under More options the library folder, restoring, rebuilding search. |
| **Trash** | How long deleted things wait, what is in the trash, emptying it. |
| **Phone** | Setting up sync, the code to link a phone, adding another computer. |
| **Activity** | What Enqueue has been doing: saves, questions and answers, summaries, syncs, backups. Click a line for the details. |

## When something goes wrong

- **"Summary: generating in the background" never finishes.** The model is unreachable, out of quota, or keeps failing. Open **Settings > Activity** to see why. Summaries that are owed are retried on their own.
- **A link has no preview.** The site refused, or is gone. The line under your note says which. See [Links](#links-pdfs-images-and-files).
- **Search says "building".** The index is being rebuilt, after an update or a restore. It finishes by itself.
- **The phone is behind.** Open the app with a connection; it syncs when it comes to the front. Pull down on the library to sync now.
- **You need the engine's own view.** `enq doctor` prints the index health, how many summaries are current, and whether model calls are paused.
