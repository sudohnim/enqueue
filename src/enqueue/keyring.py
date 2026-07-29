"""Where the API key actually lives.

An earlier version of this product had no field for a key at all, on the grounds that
`settings.json` is plaintext on disk and a password written in plaintext is not a
password. That reasoning was right about the file and wrong about the conclusion: the
answer to "we have nowhere safe to put this" is to find somewhere safe, not to make
the person edit their shell profile.

So the key goes in the macOS Keychain, through `/usr/bin/security`. That is the same
store Safari and Mail use: encrypted at rest, unlocked with the login password, and
readable by nothing else without the user approving it. No new dependency, because it
ships with the operating system.

**Masking in the interface is not what protects this.** The dots stop someone reading
the key over your shoulder. The Keychain is what stops it being read off the disk.
Those are different problems and only one of them is solved by a password input.

On anything that is not macOS there is no Keychain here, so `available()` is false and
the interface says the key must come from the environment instead. Falling back to
writing it in the settings file would defeat the entire point, quietly, which is worse
than not offering it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

SERVICE = "enqueue-llm-api-key"
ACCOUNT = "enqueue"

_SECURITY = "/usr/bin/security"


def available() -> bool:
    """Whether there is a real secret store to write to."""
    return sys.platform == "darwin" and bool(shutil.which(_SECURITY))


def get() -> str | None:
    if not available():
        return None
    try:
        done = subprocess.run(
            [_SECURITY, "find-generic-password", "-a", ACCOUNT, "-s", SERVICE, "-w"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    key = done.stdout.strip()
    return key or None


def set(key: str) -> None:
    """Store the key, replacing whatever was there.

    Written through `security -i`, which reads whole commands from stdin, so the
    secret never appears in this process's argument list. `add-generic-password -w
    <secret>` would put it in `argv`, where any other process on the machine can read
    it out of `ps` for as long as the call runs.

    A previous attempt passed the key on stdin to `-w` with no argument. That does not
    read stdin: it stored an empty password and reported success, so the interface
    said the key was saved and every model call then failed to authenticate.
    """
    if not available():
        raise RuntimeError("no keychain on this platform; set ENQ_LLM_API_KEY instead")

    key = key.strip()
    if not key:
        raise ValueError("an empty key is not a key")
    if "\n" in key or "\r" in key:
        # `security -i` is line-oriented, so a newline would end the command early and
        # store a truncated key.
        raise ValueError("a key cannot contain a line break")

    quoted = key.replace("\\", "\\\\").replace('"', '\\"')
    command = f'add-generic-password -a {ACCOUNT} -s {SERVICE} -U -w "{quoted}"\n'

    done = subprocess.run(
        [_SECURITY, "-i"],
        input=command,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or "the keychain refused to store the key")

    # `security -i` reports per-command failures on stderr while still exiting 0, so
    # the only trustworthy confirmation is reading it back.
    if get() != key:
        raise RuntimeError("the key did not store correctly")


def clear() -> bool:
    if not available():
        return False
    done = subprocess.run(
        [_SECURITY, "delete-generic-password", "-a", ACCOUNT, "-s", SERVICE],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return done.returncode == 0


def hint(key: str | None = None) -> str | None:
    """The last four characters, so a person can tell which key is stored.

    Enough to recognise it, useless to anyone who does not already have it.
    """
    key = key if key is not None else get()
    if not key:
        return None
    return "..." + key[-4:] if len(key) > 4 else "..."
