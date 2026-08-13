// Enqueue shell entry point, shared by the desktop binary and the mobile library.
//
// On desktop the shell owns the window, the menu bar, and the lifetime of the Python
// engine process. On mobile there is no local engine, so the mobile path is a thin
// webview only; the real capture-and-read mobile surfaces are Phase MOBILE work.

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    #[cfg(desktop)]
    desktop::run();
    #[cfg(mobile)]
    mobile::run();
}

#[cfg(mobile)]
mod mobile {
    /// A blank shell: it builds and launches on the device (MOB.2). It has no local
    /// engine, so the synced library, capture, and read surfaces (MOB.3-MOB.7) are
    /// what make it a real Enqueue.
    pub fn run() {
        tauri::Builder::default()
            .setup(|app| {
                tauri::WebviewWindowBuilder::new(
                    app,
                    "main",
                    tauri::WebviewUrl::App("home.html".into()),
                )
                .title("Enqueue")
                .build()?;
                Ok(())
            })
            .run(tauri::generate_context!())
            .expect("error while running Enqueue on mobile");
    }
}

#[cfg(desktop)]
mod desktop {
    use std::io::{BufRead, BufReader, Read, Write};
    use std::net::TcpStream;
    use std::path::PathBuf;
    use std::process::{Child, Command, Stdio};
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Mutex;
    use std::thread;
    use std::time::{Duration, Instant};

    use tauri::{AppHandle, Emitter, Manager};
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

    /// Whether the home window was the frontmost window when the overlay was summoned.
    ///
    /// It decides where focus goes afterwards, and it has to be focus rather than
    /// visibility: a home window sitting open behind someone's editor is still
    /// visible, so keying off visibility would raise Enqueue after every capture, which
    /// is the exact interruption the overlay exists to avoid.
    struct CameFromHome(AtomicBool);

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
            // A tight poll: a connection refused returns at once, so this only adds a
            // small slice of dead time between the engine binding its port and the window
            // being built. 150ms here was up to a seventh of a second wasted after ready.
            thread::sleep(Duration::from_millis(30));
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

    /// A hotkey rebound in settings takes effect at once, not on the next launch.
    ///
    /// The settings form stages the new accelerator and calls this command. The old
    /// registration is released and the new one put in its place; if the new one fails,
    /// the previous binding is put back so a bad combination never leaves the app
    /// without a hotkey. The page keeps the old value on screen and says why.
    #[tauri::command]
    fn hotkey_changed(app: AppHandle, accelerator: String) -> Result<(), String> {
        let previous = hotkey();
        let shortcut = app.global_shortcut();
        if let Err(err) = shortcut.unregister_all() {
            return Err(format!("could not release the old hotkey: {err}"));
        }
        let register = |binding: &str| {
            shortcut.on_shortcut(binding, |app, _shortcut, event| {
                if event.state() == ShortcutState::Pressed {
                    open_capture(app);
                }
            })
        };
        match register(&accelerator) {
            Ok(_) => Ok(()),
            Err(err) => {
                let _ = register(&previous);
                Err(err.to_string())
            }
        }
    }

    /// Where the overlay was last left. Kept next to the repo pointer rather than in the
    /// engine's database, because it describes this machine's screen and not the
    /// collection, and because it has to be readable before the engine is up.
    fn position_file() -> Option<PathBuf> {
        std::env::var_os("HOME")
            .map(|home| PathBuf::from(home).join(".enqueue-poc/capture-position"))
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

    /// Start the Python engine as a child process. Development runs it through `uv` from
    /// the repository; a bundled app will ship it as a sidecar binary later.
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
            let class = unsafe { objc_getClass(b"NSApplication\0".as_ptr() as *const _) };
            if class.is_null() {
                return std::ptr::null_mut();
            }
            unsafe {
                objc_msgSend(
                    class,
                    sel_registerName(b"sharedApplication\0".as_ptr() as *const _),
                )
            }
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
    fn open_capture(app: &AppHandle) {
        let home = app.get_webview_window("main");
        let from_home = home
            .as_ref()
            .and_then(|w| w.is_focused().ok())
            .unwrap_or(false);
        if let Some(state) = app.try_state::<CameFromHome>() {
            state.0.store(from_home, Ordering::Relaxed);
        }

        // Activating the app raises every window it has, so the home window is put away first.
        if let Some(w) = home {
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

        let from_home = app
            .try_state::<CameFromHome>()
            .map(|state| state.0.load(Ordering::Relaxed))
            .unwrap_or(false);

        if from_home {
            if let Some(home) = app.get_webview_window("main") {
                let _ = home.show();
                let _ = home.set_focus();
            }
            return;
        }

        #[cfg(target_os = "macos")]
        appkit::hide_app();
    }

    /// A capture completed successfully: put the overlay away (same as dismiss) and
    /// tell the main window to play the full-screen flight (CAP.3). The overlay used
    /// to fly its own tiny bird in the 600x264 window; now the raven flies across the
    /// whole main window instead.
    #[tauri::command]
    fn capture_done(app: AppHandle) {
        capture_dismiss(app.clone());
        let _ = app.emit("capture-flight", ());
    }

    /// Reposition the overlay by its title bar. Called on mousedown from the page.
    #[tauri::command]
    fn capture_drag(app: AppHandle) -> Result<(), String> {
        if let Some(capture) = app.get_webview_window("capture") {
            capture.start_dragging().map_err(|e| e.to_string())?;
        }
        Ok(())
    }

    /// Move the main window by its header strip. Called on mousedown from the page.
    #[tauri::command]
    fn window_drag(app: AppHandle) -> Result<(), String> {
        if let Some(main) = app.get_webview_window("main") {
            main.start_dragging().map_err(|e| e.to_string())?;
        }
        Ok(())
    }

    /// Hand a saved address to the system browser. The scheme is checked here rather than
    /// in the page: these URLs come out of the collection, and `open` will launch a
    /// handler for any scheme registered on the machine, so restrict to http and https.
    #[tauri::command]
    fn open_external(url: String) -> Result<(), String> {
        let lowered = url.to_ascii_lowercase();
        if !(lowered.starts_with("http://") || lowered.starts_with("https://")) {
            return Err("only http and https addresses can be opened".into());
        }
        std::process::Command::new("/usr/bin/open")
            .arg("--")
            .arg(&url)
            .spawn()
            .map(|_| ())
            .map_err(|e| e.to_string())
    }

    pub fn run() {
        // Spawn the engine but do NOT wait for it here, so Tauri's own init overlaps the
        // engine boot; the wait moves into setup, right before the one window that needs
        // the engine's URL.
        let child = if already_running() {
            eprintln!("[shell] engine already listening on {HOST_PORT}, attaching");
            None
        } else {
            spawn_engine()
        };
        let spawned_here = child.is_some();

        tauri::Builder::default()
            .manage(Engine(Mutex::new(child)))
            .manage(CameFromHome(AtomicBool::new(false)))
            .plugin(tauri_plugin_global_shortcut::Builder::new().build())
            .invoke_handler(tauri::generate_handler![
                capture_dismiss,
                capture_done,
                capture_drag,
                hotkey_changed,
                open_external,
                window_drag
            ])
            .setup(move |app| {
                // The webview loads the engine's URL, so it cannot be built until the
                // engine answers. By now Tauri has initialised concurrently with the
                // boot, so this waits only for whatever time the engine still needs.
                if spawned_here && !wait_for_engine(Duration::from_secs(30)) {
                    eprintln!("[shell] engine did not come up within 30s");
                }

                let window = tauri::WebviewWindowBuilder::new(
                    app,
                    "main",
                    tauri::WebviewUrl::External(ENGINE.parse().expect("valid engine url")),
                )
                .title("Enqueue")
                .inner_size(1080.0, 780.0)
                .min_inner_size(560.0, 480.0)
                .title_bar_style(tauri::TitleBarStyle::Overlay)
                .hidden_title(true)
                .disable_drag_drop_handler()
                .build()?;

                #[cfg(target_os = "macos")]
                app.set_activation_policy(tauri::ActivationPolicy::Regular);

                let _ = window.show();
                let _ = window.set_focus();

                let capture = tauri::WebviewWindowBuilder::new(
                    app,
                    "capture",
                    tauri::WebviewUrl::External(
                        format!("{ENGINE}/capture").parse().expect("valid engine url"),
                    ),
                )
                .title("")
                // A contained capture card: a prominent input box with a Keep button
                // under it (the dequeue capture format).
                .inner_size(600.0, 264.0)
                .resizable(false)
                .decorations(false)
                .transparent(true)
                .shadow(false)
                .always_on_top(true)
                .skip_taskbar(true)
                .visible(false)
                .center()
                .disable_drag_drop_handler()
                .build()?;

                if let Some((x, y)) = saved_position() {
                    let _ = capture.set_position(tauri::PhysicalPosition::new(x, y));
                }

                let binding = hotkey();
                let shortcut = app.global_shortcut();
                if let Err(err) = shortcut.on_shortcut(binding.as_str(), |app, _shortcut, event| {
                    if event.state() == ShortcutState::Pressed {
                        open_capture(app);
                    }
                }) {
                    eprintln!("[shell] could not bind {binding}: {err}");
                }

                Ok(())
            })
            .on_window_event(|window, event| {
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
                tauri::RunEvent::Reopen { .. } => {
                    if let Some(window) = app.get_webview_window("main") {
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                }
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
}
