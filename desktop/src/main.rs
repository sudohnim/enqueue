// Enqueue for macOS.
//
// The window is a thin client over the engine, exactly like the browser view is.
// Nothing about the museum lives here: the shell owns the window, the menu bar, and
// the lifetime of the engine process, and nothing else. That is what keeps the
// eventual Rust port of the engine possible without touching this file.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader};
use std::net::TcpStream;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::Manager;

const ENGINE: &str = "http://127.0.0.1:8787";
const HOST_PORT: &str = "127.0.0.1:8787";

/// Holds the engine so it can be killed when the window closes. Without this the
/// process outlives the app and the next launch finds the port taken.
struct Engine(Mutex<Option<Child>>);

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

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(engine) = window.app_handle().try_state::<Engine>() {
                    if let Ok(mut guard) = engine.0.lock() {
                        if let Some(child) = guard.as_mut() {
                            let _ = child.kill();
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("failed to start Enqueue");
}
