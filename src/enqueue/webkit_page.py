"""Open one web page in the Mac's own WebKit, off screen, and hand back its HTML once its
scripts have run: the preview browser (preview._read_browser) on a Mac.

It is Safari's engine, already on every Mac, so it costs the app 29 MB of bindings
(pyobjc) where headless Chromium cost 450. It runs as its own short-lived process
(`python -m enqueue.webkit_page <url>`): WebKit needs the main thread's run loop, which
the engine's main thread does not have to give, and a page that hangs or crashes WebKit
takes only this process with it (`read` kills it at the deadline).

What it will not do, the same lines the plain fetch keeps (preview.py):
- go anywhere that is not the public internet: every navigation, a redirect or a frame
  included, is checked (netguard.is_public), and requests to literal private addresses
  from inside the page are blocked by a content rule;
- pass for something it is not: the user agent is WebKit's own;
- keep anything: cookies and storage live in a data store that dies with the process;
- make a sound or start a download.
It answers one line of JSON on stdout: {"status", "url", "html"} or {"error"}.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

# A page has loaded when WebKit says so; its scripts then get this long to fill it in.
SETTLE_S = 1.5
MAX_CHARS = 2_000_000

# Requests from inside the page to these hosts are blocked outright (a page cannot
# reach the router or this Mac's own services through the preview browser). A name
# that resolves inward is caught for navigations by netguard; for a page's own
# requests only literal addresses can be named here.
_PRIVATE_HOSTS = [
    r"^[a-z]+://localhost[:/]",
    r"^[a-z]+://[^/:]*\.localhost[:/]",
    r"^[a-z]+://[^/:]*\.local[:/]",
    r"^[a-z]+://\[",  # every IPv6 literal
    r"^[a-z]+://0\.0\.0\.0[:/]",
    r"^[a-z]+://127\.[0-9]+\.[0-9]+\.[0-9]+[:/]",
    r"^[a-z]+://10\.[0-9]+\.[0-9]+\.[0-9]+[:/]",
    r"^[a-z]+://192\.168\.[0-9]+\.[0-9]+[:/]",
    r"^[a-z]+://169\.254\.[0-9]+\.[0-9]+[:/]",
    r"^[a-z]+://172\.1[6-9]\.[0-9]+\.[0-9]+[:/]",
    r"^[a-z]+://172\.2[0-9]\.[0-9]+\.[0-9]+[:/]",
    r"^[a-z]+://172\.3[01]\.[0-9]+\.[0-9]+[:/]",
    r"^[a-z]+://100\.6[4-9]\.[0-9]+\.[0-9]+[:/]",
    r"^[a-z]+://100\.[7-9][0-9]\.[0-9]+\.[0-9]+[:/]",
    r"^[a-z]+://100\.1[01][0-9]\.[0-9]+\.[0-9]+[:/]",
    r"^[a-z]+://100\.12[0-7]\.[0-9]+\.[0-9]+[:/]",
]


def rules() -> str:
    """The content rules, one per range: WebKit's url-filter has no alternation."""
    return json.dumps(
        [{"trigger": {"url-filter": f}, "action": {"type": "block"}} for f in _PRIVATE_HOSTS]
    )


def available() -> bool:
    """Whether this machine can run the reader: a Mac with the WebKit bindings."""
    if sys.platform != "darwin":
        return False
    import importlib.util

    return importlib.util.find_spec("WebKit") is not None


def read(url: str, timeout_s: float) -> tuple[int, str]:
    """Return (status, html) for the page, or raise RuntimeError with the reason."""
    try:
        done = subprocess.run(
            [sys.executable, "-m", "enqueue.webkit_page", url, str(timeout_s)],
            capture_output=True,
            text=True,
            timeout=timeout_s + 10,
            env=os.environ | {"PYTHONDONTWRITEBYTECODE": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("the page did not finish opening") from exc
    try:
        answer = json.loads(done.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError) as exc:
        raise RuntimeError("the browser stopped before the page opened") from exc
    if answer.get("error"):
        raise RuntimeError(answer["error"])
    return int(answer.get("status") or 0), str(answer.get("html") or "")


def _main(url: str, timeout_s: float) -> dict:  # pragma: no cover - needs a Mac's WebKit
    import objc
    from AppKit import NSApplication, NSApplicationActivationPolicyProhibited
    from Foundation import NSURL, NSDate, NSMakeRect, NSObject, NSRunLoop, NSURLRequest
    from WebKit import (
        WKContentRuleListStore,
        WKWebView,
        WKWebViewConfiguration,
        WKWebsiteDataStore,
    )

    from .netguard import is_public

    state: dict = {"status": 0}

    class Delegate(NSObject):
        def webView_decidePolicyForNavigationAction_decisionHandler_(self, wv, action, handler):
            target = action.request().URL()
            scheme = str(target.scheme() or "").lower() if target else ""
            if scheme in ("about", "data", "blob"):
                handler(1)
                return
            host = str(target.host() or "") if target else ""
            if scheme not in ("http", "https") or not host or not is_public(host, None):
                if action.targetFrame() is None or action.targetFrame().isMainFrame():
                    state["error"] = "the page led somewhere that is not a public address"
                handler(0)
                return
            handler(1)

        def webView_decidePolicyForNavigationResponse_decisionHandler_(self, wv, resp, handler):
            if resp.isForMainFrame():
                r = resp.response()
                if hasattr(r, "statusCode"):
                    state["status"] = int(r.statusCode())
                state["url"] = str(r.URL().absoluteString())
                if not resp.canShowMIMEType():
                    state["error"] = "not a web page"
                    handler(0)
                    return
            handler(1)

        def webView_didFinishNavigation_(self, wv, nav):
            state["loaded"] = time.monotonic()

        def webView_didFailNavigation_withError_(self, wv, nav, err):
            state.setdefault("error", str(err.localizedDescription()))

        def webView_didFailProvisionalNavigation_withError_(self, wv, nav, err):
            state.setdefault("error", str(err.localizedDescription()))

        def webViewWebContentProcessDidTerminate_(self, wv):
            state.setdefault("error", "the page crashed the browser")

    def spin(seconds: float) -> None:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(seconds))

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyProhibited)  # no Dock icon

    conf = WKWebViewConfiguration.alloc().init()
    conf.setWebsiteDataStore_(WKWebsiteDataStore.nonPersistentDataStore())
    conf.setMediaTypesRequiringUserActionForPlayback_(0xFFFFFFFF)  # nothing plays

    compiled: dict = {}

    def on_compiled(rule_list, error):
        compiled["list"], compiled["error"] = rule_list, error

    # Compiled into a folder that goes with this process, not WebKit's default store
    # under ~/Library.
    scratch = tempfile.mkdtemp(prefix="enqueue-webkit-")
    store = WKContentRuleListStore.storeWithURL_(NSURL.fileURLWithPath_(scratch))
    store.compileContentRuleListForIdentifier_encodedContentRuleList_completionHandler_(
        "enqueue-private", rules(), on_compiled
    )
    deadline = time.monotonic() + 5
    while "list" not in compiled and time.monotonic() < deadline:
        spin(0.05)
    shutil.rmtree(scratch, ignore_errors=True)
    if not compiled.get("list"):
        return {"error": f"the browser could not be set up ({compiled.get('error')})"}
    conf.userContentController().addContentRuleList_(compiled["list"])

    view = WKWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, 1280, 900), conf)
    delegate = Delegate.alloc().init()
    view.setNavigationDelegate_(delegate)
    view.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(url)))

    deadline = time.monotonic() + timeout_s
    answer: dict = {}
    while time.monotonic() < deadline and not answer:
        spin(0.1)
        if state.get("error"):
            return {"error": state["error"]}
        if state.get("loaded") and time.monotonic() - state["loaded"] >= SETTLE_S:

            def got(result, error):
                answer["html"] = result if isinstance(result, str) else ""

            view.evaluateJavaScript_completionHandler_("document.documentElement.outerHTML", got)
            state["loaded"] = float("inf")  # ask once
    if "html" not in answer:
        return {"error": "the page did not finish opening"}
    objc.recycleAutoreleasePool()
    return {
        "status": state["status"],
        "url": state.get("url") or url,
        "html": answer["html"][:MAX_CHARS],
    }


if __name__ == "__main__":  # pragma: no cover - run by read() in its own process
    target, limit = sys.argv[1], float(sys.argv[2])
    if urlsplit(target).scheme not in ("http", "https"):
        out = {"error": "only web pages open in the preview browser"}
    else:
        try:
            out = _main(target, limit)
        except Exception as exc:  # noqa: BLE001 - one line back to the engine, always
            out = {"error": f"the browser failed ({type(exc).__name__})"}
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()
    os._exit(0)
