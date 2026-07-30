// Enqueue for macOS.
//
// The window is a thin client over the engine, exactly like the browser view is.
// Nothing about the museum lives here: the shell owns the window, the menu bar, and
// the lifetime of the engine process, and nothing else. That is what keeps the
// eventual Rust port of the engine possible without touching this file.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

const ENGINE: &str = "http://127.0.0.1:8787";
const HOST_PORT: &str = "127.0.0.1:8787";

/// What the hotkey is bound to before the engine has been asked. The engine owns the
/// real value, but the overlay has to work on the first launch of the day, when the
/// shortcut is registered while the engine is still coming up.
const DEFAULT_HOTKEY: &str = "Alt+Shift+E";

/// Holds the engine so it can be killed when the app exits. Without this the process
/// outlives the app and the next launch finds the port taken.
struct Engine(Mutex<Option<Child>>);

/// Whether the museum was the frontmost window when the overlay was summoned.
///
/// It decides where focus goes afterwards, and it has to be focus rather than
/// visibility: a museum window sitting open behind someone's editor is still
/// visible, so keying off visibility would raise Enqueue after every capture, which
/// is the exact interruption the overlay exists to avoid.
struct CameFromMuseum(AtomicBool);

fn already_running() -> bool {
    TcpStream::connect_timeout(
        &HOST_PORT.parse().expect("valid host"),
        Duration::from_millis(250),
    )
    .is_ok()
}

fn wait_for_engine(timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if already_running() {
            return true;
        }
        thread::sleep(Duration::from_millis(150));
    }
    false
}

/// One GET against the engine, written by hand rather than pulled in as a dependency.
///
/// The shell talks to exactly one endpoint, on the loopback, with no redirects and no
/// TLS. An HTTP client crate would be several hundred kilobytes of binary to express
/// the eight lines below.
fn engine_get(path: &str) -> Option<String> {
    let mut stream = TcpStream::connect_timeout(
        &HOST_PORT.parse().expect("valid host"),
        Duration::from_millis(500),
    )
    .ok()?;
    stream.set_read_timeout(Some(Duration::from_secs(2))).ok()?;
    write!(
        stream,
        "GET {path} HTTP/1.0\r\nHost: {HOST_PORT}\r\nConnection: close\r\n\r\n"
    )
    .ok()?;

    let mut raw = String::new();
    stream.read_to_string(&mut raw).ok()?;
    raw.split_once("\r\n\r\n").map(|(_, body)| body.to_owned())
}

/// The capture hotkey, which is a stored setting rather than a constant so it can be
/// rebound in the interface. Falls back when the engine is not answering yet: an
/// unregistered hotkey is a feature that silently does not exist.
fn hotkey() -> String {
    engine_get("/settings")
        .and_then(|body| serde_json::from_str::<serde_json::Value>(&body).ok())
        .and_then(|json| {
            json.get("settings")?
                .get("hotkey")?
                .get("value")?
                .as_str()
                .map(str::to_owned)
        })
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| DEFAULT_HOTKEY.into())
}

/// Where the overlay was last left. Kept next to the repo pointer rather than in the
/// engine's database, because it describes this machine's screen and not the
/// collection, and because it has to be readable before the engine is up.
fn position_file() -> Option<PathBuf> {
    std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".enqueue-poc/capture-position"))
}

fn saved_position() -> Option<(i32, i32)> {
    let text = std::fs::read_to_string(position_file()?).ok()?;
    let (x, y) = text.trim().split_once(',')?;
    Some((x.trim().parse().ok()?, y.trim().parse().ok()?))
}

fn remember_position(window: &tauri::WebviewWindow) {
    let Some(path) = position_file() else { return };
    let Ok(at) = window.outer_position() else {
        return;
    };
    if let Some(dir) = path.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    let _ = std::fs::write(path, format!("{},{}", at.x, at.y));
}

/// Start the Python engine as a child process.
///
/// Development runs it through `uv` from the repository. Once the app is bundled this
/// becomes a sidecar binary shipped inside the .app, which is the packaging task the
/// docs already flag as unresolved.
/// Where the engine lives.
///
/// A bundled .app starts with the working directory at `/`, so deriving the repo from
/// cwd works when run from `desktop/` during development and cannot work once the app
/// is double-clicked. Until the engine ships as a sidecar binary, the bundle is told
/// where to look by a one-line file.
fn engine_repo() -> String {
    if let Ok(from_env) = std::env::var("ENQUEUE_REPO") {
        return from_env;
    }

    if let Some(home) = std::env::var_os("HOME") {
        let pointer = std::path::Path::new(&home).join(".enqueue-poc/repo");
        if let Ok(contents) = std::fs::read_to_string(&pointer) {
            let path = contents.trim();
            if !path.is_empty() {
                return path.to_string();
            }
        }
    }

    std::env::current_dir()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_string_lossy().into_owned()))
        .unwrap_or_else(|| ".".into())
}

fn spawn_engine() -> Option<Child> {
    let repo = engine_repo();
    eprintln!("[shell] starting the engine from {repo}");

    // A double-clicked app inherits the launch daemon's PATH, which has no
    // /opt/homebrew/bin and therefore no `uv`. Finding it here rather than failing
    // with a bare "No such file or directory" is the difference between a fixable
    // problem and a window that never appears.
    let uv = ["/opt/homebrew/bin/uv", "/usr/local/bin/uv"]
        .into_iter()
        .find(|p| std::path::Path::new(p).exists())
        .unwrap_or("uv");

    let mut child = Command::new(uv)
        .args(["run", "enq", "serve"])
        .current_dir(&repo)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .ok()?;

    // Engine output goes to the app's stderr rather than being swallowed, so a
    // failure to start is visible instead of presenting a blank window.
    if let Some(err) = child.stderr.take() {
        thread::spawn(move || {
            for line in BufReader::new(err).lines().map_while(Result::ok) {
                eprintln!("[engine] {line}");
            }
        });
    }

    Some(child)
}

/// The two AppKit calls the overlay cannot be built without.
///
/// Both are process-level. Tauri's window API operates a layer below that, and on
/// macOS a window belonging to a background app can be raised, focused and still sit
/// behind whatever the person is actually looking at.
#[cfg(target_os = "macos")]
mod appkit {
    use std::ffi::{c_char, c_int, c_void};

    // The Objective-C runtime ships as a dylib, not a framework, so it is linked as a
    // plain library.
    #[link(name = "objc")]
    extern "C" {
        fn objc_getClass(name: *const c_char) -> *mut c_void;
        fn objc_msgSend(obj: *mut c_void, sel: *mut c_void, ...) -> *mut c_void;
        fn sel_registerName(name: *const c_char) -> *mut c_void;
    }

    unsafe fn shared_app() -> *mut c_void {
        let class = objc_getClass(b"NSApplication\0".as_ptr() as *const _);
        if class.is_null() {
            return std::ptr::null_mut();
        }
        objc_msgSend(
            class,
            sel_registerName(b"sharedApplication\0".as_ptr() as *const _),
        )
    }

    /// `[NSApp activateIgnoringOtherApps:YES]`, the only reliable way to bring a
    /// background app in front of the current frontmost one.
    pub fn activate() {
        unsafe {
            let app = shared_app();
            if app.is_null() {
                return;
            }
            let sel = sel_registerName(b"activateIgnoringOtherApps:\0".as_ptr() as *const _);
            // YES, passed as c_int to satisfy variadic argument promotion.
            objc_msgSend(app, sel, 1 as c_int);
        }
    }

    /// `[NSApp hide:nil]`, which makes macOS activate whatever was frontmost before
    /// Enqueue was. Hiding the overlay window alone leaves Enqueue frontmost with no
    /// window, so the person ends up in Enqueue rather than back in their editor.
    pub fn hide_app() {
        unsafe {
            let app = shared_app();
            if app.is_null() {
                return;
            }
            let sel = sel_registerName(b"hide:\0".as_ptr() as *const _);
            objc_msgSend(app, sel, std::ptr::null_mut::<c_void>());
        }
    }
}

/// Summon the overlay above whatever app is frontmost.
///
/// Lives in Rust rather than in the webview so it survives the museum window being
/// closed. A shortcut registered from a page dies with the page, which reads as the
/// hotkey having quietly stopped working until the next relaunch.
fn open_capture(app: &AppHandle) {
    let museum = app.get_webview_window("main");
    let from_museum = museum
        .as_ref()
        .and_then(|w| w.is_focused().ok())
        .unwrap_or(false);
    if let Some(state) = app.try_state::<CameFromMuseum>() {
        state.0.store(from_museum, Ordering::Relaxed);
    }

    // Activating the app raises every window it has, so the museum is put away first.
    // Otherwise a note slid under the door drags the whole room in behind it.
    if let Some(w) = museum {
        let _ = w.hide();
    }

    if let Some(capture) = app.get_webview_window("capture") {
        let _ = capture.show();
        let _ = capture.set_focus();
        #[cfg(target_os = "macos")]
        appkit::activate();
    }
}

/// Put the overlay away and give focus back to where it came from.
#[tauri::command]
fn capture_dismiss(app: AppHandle) {
    if let Some(capture) = app.get_webview_window("capture") {
        remember_position(&capture);
        let _ = capture.hide();
    }

    let from_museum = app
        .try_state::<CameFromMuseum>()
        .map(|state| state.0.load(Ordering::Relaxed))
        .unwrap_or(false);

    if from_museum {
        if let Some(museum) = app.get_webview_window("main") {
            let _ = museum.show();
            let _ = museum.set_focus();
        }
        return;
    }

    #[cfg(target_os = "macos")]
    appkit::hide_app();
}

/// Reposition the overlay by its title bar. Called on mousedown from the page: the
/// Rust side is more reliable than the JS drag API on a transparent, undecorated
/// window.
#[tauri::command]
fn capture_drag(app: AppHandle) -> Result<(), String> {
    if let Some(capture) = app.get_webview_window("capture") {
        capture.start_dragging().map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Move the main window by its header strip. Called on mousedown from the page.
///
/// `-webkit-app-region: drag` is a Chromium feature and does nothing in this WKWebView,
/// which is why the CSS drag region never moved the window. `start_dragging()` is the
/// one path that works here, the same one the capture overlay already uses.
#[tauri::command]
fn window_drag(app: AppHandle) -> Result<(), String> {
    if let Some(main) = app.get_webview_window("main") {
        main.start_dragging().map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Hand a saved address to the system browser.
///
/// `target="_blank"` does nothing in a WKWebView: there are no tabs, so clicking a
/// link on an artifact silently did nothing at all. The page has to ask the OS.
///
/// The scheme is checked here rather than in the page. These URLs come out of the
/// collection, which means they came from somewhere else originally, and `open` will
/// launch a handler for any scheme registered on the machine. Restricting to http and
/// https keeps a saved string from reaching anything but a browser.
#[tauri::command]
fn open_external(url: String) -> Result<(), String> {
    let lowered = url.to_ascii_lowercase();
    if !(lowered.starts_with("http://") || lowered.starts_with("https://")) {
        return Err("only http and https addresses can be opened".into());
    }
    // A leading "-" would be read as a flag by `open`. `--` ends option parsing, and
    // the url is its own argv entry, so there is no shell to inject into either.
    std::process::Command::new("/usr/bin/open")
        .arg("--")
        .arg(&url)
        .spawn()
        .map(|_| ())
        .map_err(|e| e.to_string())
}

fn main() {
    let child = if already_running() {
        eprintln!("[shell] engine already listening on {HOST_PORT}, attaching");
        None
    } else {
        let spawned = spawn_engine();
        if spawned.is_some() && !wait_for_engine(Duration::from_secs(30)) {
            eprintln!("[shell] engine did not come up within 30s");
        }
        spawned
    };

    tauri::Builder::default()
        .manage(Engine(Mutex::new(child)))
        .manage(CameFromMuseum(AtomicBool::new(false)))
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .invoke_handler(tauri::generate_handler![capture_dismiss, capture_drag, open_external, window_drag])
        .setup(|app| {
            let window = tauri::WebviewWindowBuilder::new(
                app,
                "main",
                tauri::WebviewUrl::External(ENGINE.parse().expect("valid engine url")),
            )
            .title("Enqueue")
            .inner_size(1080.0, 780.0)
            .min_inner_size(560.0, 480.0)
            // The museum has no chrome of its own, so the traffic lights float over
            // the content instead of sitting in a bar that would be a wall.
            .title_bar_style(tauri::TitleBarStyle::Overlay)
            .hidden_title(true)
            .build()?;

            // Raising the window is not the same as activating the application. A
            // process launched from a shell is not the frontmost app, so the window
            // is ordered correctly within a layer that is still behind whatever the
            // person was already looking at. It reads exactly like a launch that
            // silently failed, which is what it was reported as.
            #[cfg(target_os = "macos")]
            let _ = app.set_activation_policy(tauri::ActivationPolicy::Regular);

            let _ = window.show();
            let _ = window.set_focus();

            // The overlay is built once and then only ever shown and hidden. Building
            // it on each hotkey press would put a webview boot between the key and
            // the caret, which is most of the two seconds the whole thing is meant to
            // take.
            let capture = tauri::WebviewWindowBuilder::new(
                app,
                "capture",
                tauri::WebviewUrl::External(
                    format!("{ENGINE}/capture").parse().expect("valid engine url"),
                ),
            )
            .title("")
            // Three lines of room and no more. A taller box would be a room you
            // entered rather than a note pushed under the door.
            .inner_size(580.0, 132.0)
            .resizable(false)
            .decorations(false)
            .transparent(true)
            .shadow(false)
            .always_on_top(true)
            .skip_taskbar(true)
            .visible(false)
            .center()
            // Tauri swallows HTML5 drag-drop for its own file-drop event by default,
            // so the page would never see a drop. The page wants the real Files.
            .disable_drag_drop_handler()
            .build()?;

            if let Some((x, y)) = saved_position() {
                // Physical, not logical: outer_position reports device pixels, and
                // round-tripping through the logical builder position would walk the
                // window across the screen on a retina display.
                let _ = capture.set_position(tauri::PhysicalPosition::new(x, y));
            }

            let binding = hotkey();
            let shortcut = app.global_shortcut();
            if let Err(err) = shortcut.on_shortcut(binding.as_str(), |app, _shortcut, event| {
                // Pressed only. Without the guard the overlay opens on the press and
                // again on the release.
                if event.state() == ShortcutState::Pressed {
                    open_capture(app);
                }
            }) {
                eprintln!("[shell] could not bind {binding}: {err}");
            }

            Ok(())
        })
        .on_window_event(|window, event| {
            // Closing the museum hides it rather than tearing it down: the process has
            // to stay alive for the hotkey to keep working, and on macOS closing a
            // window has never meant quitting anyway.
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to start Enqueue")
        .run(|app, event| match event {
            // Closing the museum only hid it, so the dock icon is the way back. Without
            // this the app would be running with no way to reach it but the hotkey.
            tauri::RunEvent::Reopen { .. } => {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
            // The engine used to be killed when the museum window was destroyed. It no
            // longer is destroyed, so the kill moves to the one event that still means
            // the app is going away.
            tauri::RunEvent::Exit => {
                if let Some(engine) = app.try_state::<Engine>() {
                    if let Ok(mut guard) = engine.0.lock() {
                        if let Some(child) = guard.as_mut() {
                            let _ = child.kill();
                        }
                    }
                }
            }
            _ => {}
        });
}
