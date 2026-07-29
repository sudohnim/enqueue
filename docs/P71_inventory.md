# P7.1 - Visible museum vocabulary inventory

## `curator`

| Line | Context |
| --- | --- |
| 2739 | `<div class="shelf">What the curator made of it</div>` |
| 2765 | `"Too short for the curator to draw anything general out of. Still searchable."` |
| 2769 | `"Nothing here for the curator to read yet. Still searchable."` |
| 2775 | `"The curator has not read this yet. Still searchable."` |
| 3463 | `? 'The curator could not answer.<br><br><span class="gold">' +` |
| 3516 | `(m.role === "user" ? "you" : "curator")` |
| 3519 | `(m.role === "user" ? "you" : "the curator")` |
| 3555 | `'<div class="who">the curator</div>'` |

## `Kept`

| Line | Context |
| --- | --- |
| 2541 | `'<div class="shelf">Kept</div>'` |
| 2543 | `'aria-label="Kept artifacts">'` |
| 2922 | `"Kept exactly as it arrived. Nothing in it reads as text, so there is " +` |
| 4084 | `'<div class="aside">Kept in the macOS Keychain, not in any file here. ' +` |

## `shelf` - CSS class only, not visible copy

## `exhibit`

| Line | Context |
| --- | --- |
| 2501 | `api("/exhibits")` |
| 2517 | `'<div class="shelf">Exhibits</div>'` |
| 3316 | `const d = await api("/exhibits/" + id);` |
| 3317 | `const e = d.exhibit;` |
| 3318 | `scope = { kind: "exhibit", id, label: "this room" };` |
| 3441 | `asked.kind === "artifact" \|\| asked.kind === "exhibit"` |

## `museum` - in comments/id only, not visible copy

## `plaque` - in CSS comments only (old system), not visible copy
