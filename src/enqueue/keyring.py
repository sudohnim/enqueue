"""Where secrets actually live: the macOS Keychain.

An earlier version of this product had no field for a key at all, on the grounds that
`settings.json` is plaintext on disk and a password written in plaintext is not a
password. That reasoning was right about the file and wrong about the conclusion: the
answer to "we have nowhere safe to put this" is to find somewhere safe, not to make
the person edit their shell profile.

So the key goes in the macOS Keychain, through `/usr/bin/security`. That is the same
store Safari and Mail use: encrypted at rest, unlocked with the login password, and
readable by nothing else without the user approving it. No new dependency, because it
ships with the operating system.

Two secrets live here: the provider API key (service `enqueue-llm-api-key`) and the
per-library sync secret (service `enqueue-sync-secret`). They are separate entries on
purpose, so forgetting one never takes the other with it.

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

# The provider API key (LLM backends) and the per-library sync secret are two
# different Keychain entries under one account.
SERVICE = "enqueue-llm-api-key"
SYNC_SERVICE = "enqueue-sync-secret"
ACCOUNT = "enqueue"

_SECURITY = "/usr/bin/security"


def available() -> bool:
    """Whether there is a real secret store to write to."""
    return sys.platform == "darwin" and bool(shutil.which(_SECURITY))


def _get(service: str) -> str | None:
    if not available():
        return None
    try:
        done = subprocess.run(
            [_SECURITY, "find-generic-password", "-a", ACCOUNT, "-s", service, "-w"],
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


def _set(service: str, secret: str, noun: str = "key") -> None:
    """Store a secret, replacing whatever was there.

    Written through `security -i`, which reads whole commands from stdin, so the
    secret never appears in this process's argument list. `add-generic-password -w
    <secret>` would put it in `argv`, where any other process on the machine can read
    it out of `ps` for as long as the call runs.
    """
    if not available():
        raise RuntimeError(
            "no keychain on this platform; set ENQ_LLM_API_KEY instead"
            if noun == "key"
            else "no keychain on this platform; the sync secret has nowhere to go"
        )

    secret = secret.strip()
    if not secret:
        raise ValueError(f"an empty {noun} is not a {noun}")
    if "\n" in secret or "\r" in secret:
        # `security -i` is line-oriented, so a newline would end the command early and
        # store a truncated secret.
        raise ValueError(f"a {noun} cannot contain a line break")

    quoted = secret.replace("\\", "\\\\").replace('"', '\\"')
    command = f'add-generic-password -a {ACCOUNT} -s {service} -U -w "{quoted}"\n'

    done = subprocess.run(
        [_SECURITY, "-i"],
        input=command,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or f"the keychain refused to store the {noun}")

    # `security -i` reports per-command failures on stderr while still exiting 0, so
    # the only trustworthy confirmation is reading it back.
    if _get(service) != secret:
        raise RuntimeError(f"the {noun} did not store correctly")


def _clear(service: str) -> bool:
    if not available():
        return False
    done = subprocess.run(
        [_SECURITY, "delete-generic-password", "-a", ACCOUNT, "-s", service],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return done.returncode == 0


def hint(secret: str | None = None) -> str | None:
    """The last four characters, so a person can tell which key is stored.

    Enough to recognise it, useless to anyone who does not already have it.
    """
    secret = secret if secret is not None else get()
    if not secret:
        return None
    return "..." + secret[-4:] if len(secret) > 4 else "..."


# ---- provider API key ----------------------------------------------------


def get() -> str | None:
    return _get(SERVICE)


def set(secret: str) -> None:
    _set(SERVICE, secret)


def clear() -> bool:
    return _clear(SERVICE)


# ---- per-library sync secret ---------------------------------------------


def sync_secret_get() -> str | None:
    return _get(SYNC_SERVICE)


def sync_secret_set(secret: str) -> None:
    _set(SYNC_SERVICE, secret, noun="secret")


def sync_secret_clear() -> bool:
    return _clear(SYNC_SERVICE)


def sync_secret_hint() -> str | None:
    return hint(sync_secret_get())
