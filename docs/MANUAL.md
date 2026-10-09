# Enqueue manual

How to use Enqueue, on the Mac and on the phone.
To install it or build it from source, see [DEVELOPING.md](DEVELOPING.md).

- [The idea](#the-idea)
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
- [Backups](#backups)
- [Models and privacy](#models-and-privacy)
- [Settings reference](#settings-reference)
- [When something goes wrong](#when-something-goes-wrong)

---

## The idea

Save first, organise never.
You capture a thing the moment you meet it, without choosing a folder, a tag, or a title.
Later, when a subject is on your mind, you search or ask, and Enqueue brings back everything that speaks to it, including things that never used your words.

Everything you save is an **artifact**: a note, a link, a PDF, an image, or a file.
Your library lives on your Mac, in one folder (`~/.enqueue-poc`).

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
You can change the shortcut in Settings > Features.

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

## Links, PDFs, images and files

These are **captures**: kept exactly as they were, never edited.
What you can add to a capture is your own note about it, in the box under it.
Your note is searchable, and it shapes the summary.

- **Links.** Saving a link fetches its page once, to learn its title, picture and text, so you can find it by what it says. Nothing remote is ever loaded afterwards: the picture is stored on your Mac. Click the address to open the page in your browser.
- **A site that refuses.** Some sites turn away anything that is not a browser. The page says so under your note. Turn on **Open refused links in a browser** in Settings > Features and press **Try again** to have a hidden browser open it once.
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

If you never saved anything about a subject, the answer is **nothing found**, not a wall of loosely related things.

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

Open an artifact and click **«** to open its drawer.
The **Summary** is a handful of lines the model wrote about what the artifact says and what it is an example of.
These lines are what let search find it by idea.

- Click a line to rewrite it, or **Add a line** to write your own.
- Remove a line you disagree with.
- The round arrow writes the machine's lines again; the lines you wrote or edited are kept.

Short notes, and anything holding what looks like a password or a key, get no summary.

## Tags and views

Tags are optional, and always added after the fact, in the drawer.

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

Either kind can be renamed or forgotten from the Custom tab, and an artifact's drawer has **add to a view**.

## Trash

Deleting is never one keystroke away from gone.

- The bin on an artifact moves it to the trash. It leaves every screen at once.
- It waits there for 30 days (you can change that in Settings > Trash), and can be restored whole.
- After that it is destroyed for good. You can also empty the trash yourself.

## The vault

For the few things you want hidden even from someone holding your unlocked Mac.

- The **lock** on an artifact moves it into the vault. It disappears from the wall, from search, and from answers.
- In the vault it is encrypted with a key made from a 6-digit PIN that only you know. It stays encrypted when it syncs: your other device holds it, and still cannot read it without the PIN.
- The door is deliberately unmarked: **Settings > Events > Diagnostics**. The first time, you choose the PIN. A wrong PIN looks like a diagnostic that failed.
- The vault locks itself again after a few idle minutes, and whenever you leave it.
- On the phone, the **Open with fingerprint** switch inside the vault lets a fingerprint open it instead of the PIN. The vault offers it once, right after the PIN opens it or locks an item away. With it on, locking an item away asks for your fingerprint; with it off, the PIN. The PIN always still works. Adding a new fingerprint to the phone, or changing the PIN on another device, turns this off until you enter the PIN again.

There is no way to recover a forgotten vault PIN.

## The phone

The Android app is your library in your pocket: read, capture, write, ask.

- **Reading.** Rows open to the note, the image (pinch to zoom), the link's preview, or the PDF.
- **Writing.** Tap a note to write in it. **+ > Note** starts a new one. Both save as you type.
- **Asking.** The eye answers from the copy on the phone.
- **Small edits.** Star, delete, restore, and rewrite a summary line. Tagging and views are for the desk.
- **Offline.** Everything is on the phone and saves there first. What you did reaches your Mac when there is a connection again.
- **Fingerprint lock.** The switch in **Settings > Lock** makes Enqueue ask for your fingerprint when it opens, and again after a minute away. Your phone's own screen lock works too. Enqueue offers it once the first time you open the library; turning it off asks you to confirm. Quick capture from the home screen still works without it, since it can only add a thought.

The phone does not write summaries or build the search index itself; those come from the Mac through sync.

## Sync

Sync keeps the Mac and the phone the same, through a small relay server.
The relay only ever stores scrambled data: everything is encrypted on your device before it leaves, with a key the relay never sees.

To link a phone:

1. On the Mac, open **Settings > Sync** and set it up. You are shown a **recovery phrase**: write it down. It is the only way back in if you lose every device.
2. The Mac shows a QR code.
3. In the phone app, scan it. The phone downloads your library.

There is no password to remember, and nothing to type on the phone.
If you lose the phone, link the new one the same way.
Your model settings travel too, so the phone can answer questions without being set up separately.

## Backups

Keep a copy of the whole library in your cloud drive, in case the Mac is lost.

1. Open **Settings > Storage**.
2. Under **Backup**, click **Use Proton Drive** (shown when Proton Drive is installed), or type another folder that a cloud drive syncs.

From then on a backup is made once a day and when you quit, whenever something changed.
In Proton Drive it is encrypted end to end.
The last 7 days are kept, and one a week for the 4 weeks before.
**Back up now** makes one at once.

A backup is small, because the search index is left out; it is rebuilt when you restore.

To restore, on a new Mac or after a mistake: quit Enqueue, then run

```bash
enq restore "~/Library/CloudStorage/ProtonDrive-.../"
```

Your current library is set aside, never deleted.
Start Enqueue again and it rebuilds the search index; browsing works meanwhile, and search returns when it is done.

Your model API key is not in the backup (it lives in the Mac's Keychain); enter it again in Settings.

## Models and privacy

Enqueue needs a language model for three things: summaries, answers, and gathering views.
Search and capture work without one.

- **Ollama** (the default) runs the model on your Mac. Nothing leaves it.
- **OpenRouter** or **OpenCode Go** use a model on someone else's computer. The text of the artifacts involved is sent there. An artifact marked **local only** never is.

Choose in **Settings > AI**: the backend, the model for answers, optionally a second model for summaries, and your API key.
The key is stored in the macOS Keychain, never in a file.

If the provider says your usage limit is reached, Enqueue pauses its model calls until the limit resets and then carries on by itself.
Entering a different key lifts the pause at once.

What always stays on the Mac: the library, the search index, and the embeddings that power search by meaning.
What can leave, only if you set it up: text sent to an outside model, encrypted sync through the relay, and the backup in your cloud drive.

## Settings reference

| Tab | What is there |
| --- | --- |
| **AI** | Backend, models, API key, extra headers, retries. |
| **Features** | The capture shortcut, link previews (automatic, and the browser fallback), search options. |
| **Storage** | Where the library lives, the backup folder, usage, rebuilding the index. |
| **Trash** | How long deleted things wait, what is in the trash, emptying it. |
| **Sync** | Setting up sync, the QR code to link a phone, the recovery phrase. |
| **Events** | A log of what the app did: captures, questions and their answers, summaries, syncs, backups. Click a row for its full record. |

## When something goes wrong

- **"Summary: generating in the background" never finishes.** The model is unreachable, out of quota, or keeps failing. Open **Settings > Events** to see why. Summaries that are owed are retried on their own.
- **A link has no preview.** The site refused, or is gone. The line under your note says which. See [Links](#links-pdfs-images-and-files).
- **Search says "building".** The index is being rebuilt, after an update or a restore. It finishes by itself.
- **The phone is behind.** Open the app with a connection; it syncs when it comes to the front. Pull down on the library to sync now.
- **You need the engine's own view.** `enq doctor` prints the index health, how many summaries are current, and whether model calls are paused.
