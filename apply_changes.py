src = open("desktop/src/lib.rs", "r").read()

# 1. Add appkit functions to the appkit module
old_appkit = """    mod appkit {
        use std::ffi::{c_char, c_int, c_void};

        // The Objective-C runtime ships as a dylib, not a framework, so it is linked as a
        # plain library.
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
                # YES, passed as c_int to satisfy variadic argument promotion.
                objc_msgSend(app, sel, 1 as c_int);
            }
        }

        /// `[NSApp hide:nil]`, which makes macOS activate whatever was frontmost before
        /// Enqueue was. Hiding the overlay window alone leaves Enqueue frontmost with no
        # window, so the person ends up in Enqueue rather than back in their editor.
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
    }"""

new_appkit = """    mod appkit {
        use std::ffi::{c_char, c_int, c_void};

        # The Objective-C runtime ships as a dylib, not a framework, so it is linked as a
        # plain library.
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
                # YES, passed as c_int to satisfy variadic argument promotion.
                objc_msgSend(app, sel, 1 as c_int);
            }
        }

        /// `[NSApp hide:nil]`, which makes macOS activate whatever was frontmost before
        /// Enqueue was. Hiding the overlay window alone leaves Enqueue frontmost with no
        # window, so the person ends up in Enqueue rather than back in their editor.
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

        /// `[NSWindow orderFrontRegardless]` - show the overlay above every other
        /// space/app WITHOUT raising (activating) Enqueue, so focus never leaves the
        /// app the user was just in. (CAP2.2 step 4: the no-focus-steal primitive.)
        pub fn order_front_regardless(window: *mut c_void) {
            unsafe {
                if window.is_null() {
                    return;
                }
                let sel = sel_registerName(b"orderFrontRegardless\0".as_ptr() as *const _);
                objc_msgSend(window, sel);
            }
        }

        /// `[NSWindow setLevel:]` - pin the overlay at the screen-saver level (1000)
        /// so it draws over fullscreen apps and the dock/menu bar.
        pub fn set_level(window: *mut c_void, level: i64) {
            unsafe {
                if window.is_null() {
                    return;
                }
                let sel = sel_registerName(b"setLevel:\0".as_ptr() as *const _);
                objc_msgSend(window, sel, level);
            }
        }

        /// `[NSWindow setCollectionBehavior:]` - stitch the overlay across every Space
        /// and over fullscreen apps (bitmask 273) without entering the focus cycle.
        pub fn set_collection_behavior(window: *mut c_void, behavior: u64) {
            unsafe {
                if window.is_null() {
                    return;
                }
                let sel = sel_registerName(b"setCollectionBehavior:\0".as_ptr() as *const _);
                objc_msgSend(window, sel, behavior);
            }
        }
    }"""

# 2. Add open_flight_overlay and flight_done functions after capture_done
old_capture_done = """    /// whole main window instead.
    #[tauri::command]
    fn capture_done(app: AppHandle) {
        capture_dismiss(app.clone());
        let _ = app.emit("capture-flight", ());
    }"""

new_capture_done = """    /// whole main window instead.
    #[tauri::command]
    fn capture_done(app: AppHandle) {
        capture_dismiss(app.clone());
        #[cfg(target_os = "macos")]
        open_flight_overlay(&app);
        #[cfg(not(target_os = "macos"))]
        {
            let _ = app.emit("capture-flight", ());
        }
    }

    /// Summon the raven flight overlay: transparent, borderless, always-on-top,
    /// skip-taskbar, and (on macOS) run at the screen-saver window level with
    /// click-through collection behavior so it never steals focus from the app
    /// behind it.
    #[cfg(target_os = "macos")]
    fn open_flight_overlay(app: &AppHandle) {
        # One raven at a time: a capture that arrives while one is already flying
        # is a no-op.
        if app.get_webview_window("flight").is_some() {
            return;
        }

        # Use the monitor under the cursor (not just primary) so the flight
        # appears on the correct screen in multi-monitor setups.
        let monitor = if let Ok(point) = app.cursor_position() {
            app.monitor_from_point(point.x as f64, point.y as f64).ok().flatten()
        } else {
            app.primary_monitor().ok().flatten()
        };
        let monitor = match monitor {
            Some(m) => m,
            None => return,
        };
        let pos = monitor.position();
        let size = monitor.size();

        # Load flight.html from the local app bundle (frontendDist), not from the engine.
        # This avoids network latency and works even if the engine isn't ready.
        let flight = tauri::WebviewWindowBuilder::new(
            app,
            "flight",
            tauri::WebviewUrl::App("flight.html".into()),
        )
        .title("")
        .decorations(False)
        .transparent(True)
        .shadow(False)
        .always_on_top(True)
        .skip_taskbar(True)
        .focused(False)
        .visible(False)
        .resizable(False)
        .closable(False)
        .inner_size(size.width as f64, size.height as f64)
        .position(pos.x as f64, pos.y as f64)
        .disable_drag_drop_handler()
        .build()

        let flight = match flight {
            Ok(w) => w,
            Err(err) => {
                eprintln!("[shell] could not open flight overlay: {err}")
                return;
            }
        }

        # Ensure the window is visible first
        let _ = flight.show()

        # Click-through: let mouse events fall through to the app behind the raven.
        let _ = flight.set_ignore_cursor_events(True)

        # macOS: pin over fullscreen apps (level 1000) and stitch across Spaces
        # (273), then `orderFrontRegardless` shows the window WITHOUT activating
        # Enqueue, so focus never leaves the app the user was in.
        if let Ok(ns) = flight.ns_window():
            appkit.set_collection_behavior(ns, 273)
            appkit.set_level(ns, 1000)
            appkit.order_front_regardless(ns)

    /// Retire the raven flight overlay. Invoked from `flight.html` once the
    /// animation finishes, and from the page's safety timer.
    #[tauri::command]
    fn flight_done(app: AppHandle) {
        if let Some(flight) = app.get_webview_window("flight"):
            let _ = flight.close()
    }"""

# 3. Add flight_done to desktop invoke_handler
old_handler = """.invoke_handler(tauri::generate_handler![
                capture_dismiss,
                capture_done,
                capture_drag,
                hotkey_changed,
                open_external,
                window_drag,
                desktop_pairing_code
            ])"""

new_handler = """.invoke_handler(tauri::generate_handler![
                capture_dismiss,
                capture_done,
                capture_drag,
                flight_done,
                hotkey_changed,
                open_external,
                window_drag,
                desktop_pairing_code
            ])"""

src = open("desktop/src/lib.rs", "r").read()

if old_appkit in src:
    src = src.replace(old_appkit, new_appkit)
    print("1. Updated appkit module")
else:
    print("1. Appkit pattern not found")
    exit(1)

if old_capture_done in src:
    src = src.replace(old_capture_done, new_capture_done)
    print("2. Added open_flight_overlay and flight_done")
else:
    print("2. capture_done pattern not found")
    exit(1)

# Only replace the LAST occurrence (desktop module)
parts = src.rsplit(old_handler, 1)
if len(parts) == 2:
    src = parts[0] + new_handler + parts[1]
    print("3. Added flight_done to desktop invoke_handler")
else:
    print("3. Handler pattern split failed")
    exit(1)

open("desktop/src/lib.rs", "w").write(src)
print("All changes applied successfully")
