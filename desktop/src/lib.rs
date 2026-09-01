// Enqueue shell entry point, shared by the desktop binary and the mobile library.
//
// On desktop the shell owns the window, the menu bar, and the lifetime of the Python
// engine process. On mobile there is no local engine, so the mobile path is a thin
// webview only; the real capture-and-read mobile surfaces are Phase MOBILE work.

// The mobile sync client (MOB.3): pull + decrypt + local SQLite read copy. Reuses the
// desktop crypto and snapshot/LWW model, reimplemented in Rust.
mod sync;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    #[cfg(desktop)]
    desktop::run();
    #[cfg(mobile)]
    mobile::run();
}

#[cfg(mobile)]
// Global storage for JavaVM captured during JNI_OnLoad (runs on Android UI thread)
#[cfg(target_os = "android")]
static ANDROID_JAVA_VM: std::sync::OnceLock<std::sync::Arc<jni::JavaVM>> = std::sync::OnceLock::new();

#[cfg(target_os = "android")]
static MAIN_ACTIVITY_CLASS: std::sync::OnceLock<jni::objects::GlobalRef> = std::sync::OnceLock::new();

#[cfg(target_os = "android")]
#[no_mangle]
pub extern "system" fn JNI_OnLoad(vm: *mut jni::sys::JavaVM, _reserved: *mut std::ffi::c_void) -> jni::sys::jint {
    use jni::JavaVM;
    let vm = unsafe { JavaVM::from_raw(vm as *mut _) }.expect("Failed to create JavaVM from raw pointer");
    let mut env = vm.get_env().expect("Failed to get JNIEnv");
    
    // Store the MainActivity class as a global reference
    let main_activity_class = env.find_class("com/sudohnim/enqueue/MainActivity")
        .expect("Failed to find MainActivity class");
    let global_ref = env.new_global_ref(main_activity_class)
        .expect("Failed to create global ref for MainActivity");
    MAIN_ACTIVITY_CLASS.set(global_ref).ok();
    
    ANDROID_JAVA_VM.set(std::sync::Arc::new(vm)).ok();
    jni::sys::JNI_VERSION_1_6 as jni::sys::jint
}

#[cfg(target_os = "android")]
pub(crate) fn get_android_vm() -> Result<std::sync::Arc<jni::JavaVM>, String> {
    ANDROID_JAVA_VM.get()
        .cloned()
        .ok_or_else(|| "JavaVM not initialized - JNI_OnLoad may not have run".into())
}

#[cfg(target_os = "android")]
pub(crate) fn get_main_activity_class() -> Result<jni::objects::GlobalRef, String> {
    MAIN_ACTIVITY_CLASS.get()
        .cloned()
        .ok_or_else(|| "MainActivity class not initialized - JNI_OnLoad may not have run".into())
}

#[cfg(mobile)]
mod mobile {
    use base64::engine::general_purpose;
    use base64::Engine;
    use rusqlite::{Connection, OptionalExtension};
    use serde_json::Value;
    use sha2::Digest;
    use tauri::{AppHandle, Emitter, Manager};
    #[allow(unused_imports)]
    #[cfg(mobile)]
    use tauri_plugin_dialog::DialogExt;
    // JNI for foreground service (QR.5b) - only on Android
    #[cfg(target_os = "android")]
    use jni::JNIEnv;
    #[cfg(target_os = "android")]
    use jni::objects::{JClass, JObject};
    #[cfg(target_os = "android")]
    use ndk_context::android_context;

    /// Start the Android foreground sync service via JNI.
    #[cfg(mobile)]
    fn jni_start_sync_foreground_service() -> Result<(), String> {
        let ctx = android_context();
        let vm = unsafe { jni::JavaVM::from_raw(ctx.vm().cast()) }
            .map_err(|e| format!("Failed to get JavaVM: {}", e))?;
        let mut env = vm.attach_current_thread()
            .map_err(|e| format!("Failed to attach thread: {}", e))?;
        let class = env.find_class("com/sudohnim/enqueue/SyncForegroundService")
            .map_err(|e| format!("Failed to find SyncForegroundService class: {}", e))?;
        // Create JObject from the raw context pointer
        let context_obj = unsafe { jni::objects::JObject::from_raw(ctx.context().cast()) };
        env.call_static_method(
            class,
            "startSync",
            "(Landroid/content/Context;)V",
            &[jni::objects::JValue::Object(&context_obj)],
        ).map_err(|e| format!("Failed to call startSync: {}", e))?;
        Ok(())
    }

    /// Stop the Android foreground sync service via JNI.
    #[cfg(mobile)]
    fn jni_stop_sync_foreground_service() -> Result<(), String> {
        let ctx = android_context();
        let vm = unsafe { jni::JavaVM::from_raw(ctx.vm().cast()) }
            .map_err(|e| format!("Failed to get JavaVM: {}", e))?;
        let mut env = vm.attach_current_thread()
            .map_err(|e| format!("Failed to attach thread: {}", e))?;
        let class = env.find_class("com/sudohnim/enqueue/SyncForegroundService")
            .map_err(|e| format!("Failed to find SyncForegroundService class: {}", e))?;
        let context_obj = unsafe { jni::objects::JObject::from_raw(ctx.context().cast()) };
        env.call_static_method(
            class,
            "stopSync",
            "(Landroid/content/Context;)V",
            &[jni::objects::JValue::Object(&context_obj)],
        ).map_err(|e| format!("Failed to call stopSync: {}", e))?;
        Ok(())
    }

    /// Start the Android foreground sync service (QR.5b).
    #[cfg(mobile)]
    #[tauri::command]
    fn start_sync_foreground_service() -> Result<String, String> {
        jni_start_sync_foreground_service()?;
        Ok("foreground_service_started".to_string())
    }

    /// Stop the Android foreground sync service (QR.5b).
    #[cfg(mobile)]
    #[tauri::command]
    fn stop_sync_foreground_service() -> Result<String, String> {
        jni_stop_sync_foreground_service()?;
        Ok("foreground_service_stopped".to_string())
    }

    /// Open (and initialize) the local SQLite read copy.
    fn open_lib(app: &AppHandle) -> Result<Connection, String> {
        let dir = app.path().app_data_dir().map_err(|e| e.to_string())?;
        std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
        let conn = Connection::open(dir.join("library.db")).map_err(|e| e.to_string())?;
        crate::sync::init_schema(&conn).map_err(|e| e.to_string())?;
        Ok(conn)
    }

    /// Persist a value in the app's private (OS-sandboxed) data dir, so a relaunch
    /// syncs without re-entering the config (MOB.3b). NOTE: the Android Keystore was the
    /// intended backend, but Tauri v2 exposes no public API to reach the JNI context from
    /// an app command (`run_on_android_context` and `ndk-context` are both crate-internal),
    /// so the secret + DEK rest in a file that only this app's Linux UID can read.
    fn secure_store_set(app: &AppHandle, key: &str, value: &str) -> Result<(), String> {
        let dir = app.path().app_data_dir().map_err(|e| e.to_string())?;
        std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
        std::fs::write(dir.join(key), value).map_err(|e| e.to_string())
    }

    fn secure_store_get(app: &AppHandle, key: &str) -> Result<Option<String>, String> {
        let dir = app.path().app_data_dir().map_err(|e| e.to_string())?;
        match std::fs::read_to_string(dir.join(key)) {
            Ok(s) => Ok(Some(s)),
            Err(_) => Ok(None),
        }
    }

    /// Persist the sync config + the unlocked DEK in the secure store (MOB.3b), so a
    /// relaunch syncs without re-entering the phrase.
    fn save_config(
        app: &AppHandle,
        relay_url: &str,
        secret: &str,
        keyring_json: &str,
        dek: &[u8; 32],
        llm_backend: Option<&str>,
        llm_model: Option<&str>,
        llm_api_key: Option<&str>,
        llm_url: Option<&str>,
        auto_preview: Option<bool>,
        trash_days: Option<&str>,
    ) -> Result<(), String> {
        let mut blob = serde_json::json!({
            "relay_url": relay_url,
            "secret": secret,
            "keyring_json": keyring_json,
            "dek": hex::encode(dek),
        });
        if let Some(v) = llm_backend { blob["llm_backend"] = serde_json::json!(v); }
        if let Some(v) = llm_model { blob["llm_model"] = serde_json::json!(v); }
        if let Some(v) = llm_api_key { blob["llm_api_key"] = serde_json::json!(v); }
        if let Some(v) = llm_url { blob["llm_url"] = serde_json::json!(v); }
        if let Some(v) = auto_preview { blob["auto_preview"] = serde_json::json!(v); }
        if let Some(v) = trash_days { blob["trash_days"] = serde_json::json!(v); }
        secure_store_set(app, "sync_config", &blob.to_string())
    }

    fn load_config(app: &AppHandle) -> Result<Option<Value>, String> {
        match secure_store_get(app, "sync_config")? {
            Some(s) => serde_json::from_str(&s)
                .map(Some)
                .map_err(|e| format!("saved config: {e}")),
            None => Ok(None),
        }
    }

    fn dek_from_hex(s: &str) -> Option<[u8; 32]> {
        let bytes = hex::decode(s).ok()?;
        let mut out = [0u8; 32];
        if bytes.len() == 32 {
            out.copy_from_slice(&bytes);
            Some(out)
        } else {
            None
        }
    }

    /// One sync in flight at a time. The SSE listener and the on-load / resume /
    /// Sync Now paths all funnel through this so a burst of events collapses to a
    /// single pull instead of stacking overlapping DB writers.
    static SYNC_RUNNING: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

    /// Run one sync from the persisted config, emitting sync-started/done/error to
    /// the webview (same events the UI already listens for). Non-blocking: it spawns
    /// its own thread and returns immediately, and it no-ops if a sync is already
    /// running. Used by the live SSE listener; the UI's Sync Now path keeps its own
    /// spawn in `mobile_sync`.
    fn run_sync_once(app: &AppHandle) {
        use std::sync::atomic::Ordering;
        if SYNC_RUNNING.swap(true, Ordering::SeqCst) {
            return; // a sync is already in flight; it will pull the latest
        }
        let app = app.clone();
        std::thread::spawn(move || {
            let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                let saved = load_config(&app).ok().flatten().unwrap_or(Value::Null);
                let relay_url = saved.get("relay_url").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let secret = saved.get("secret").and_then(|v| v.as_str()).unwrap_or("").to_string();
                if relay_url.is_empty() || secret.is_empty() {
                    return;
                }
                let conn = match open_lib(&app) {
                    Ok(c) => c,
                    Err(_) => return,
                };
                let _ = app.emit("sync-started", serde_json::json!({}));
                let dek = saved
                    .get("dek")
                    .and_then(|v| v.as_str())
                    .and_then(|s| hex::decode(s).ok())
                    .and_then(|b| b.try_into().ok());
                let outcome = crate::sync::sync_library(&relay_url, &secret, dek.as_ref(), &conn);
                let ids = crate::sync::list_artifact_ids(&conn).unwrap_or_default();
                let err = outcome.error.as_deref().unwrap_or("");
                let _ = app.emit(
                    if err.is_empty() { "sync-done" } else { "sync-error" },
                    serde_json::json!({
                        "status": outcome.status,
                        "pulled": outcome.pulled,
                        "error": outcome.error,
                        "artifact_ids": ids,
                    }),
                );
            }));
            SYNC_RUNNING.store(false, Ordering::SeqCst);
        });
    }

    /// Live sync (MOBLIVE): subscribe to the relay's SSE change feed and pull on
    /// every event, so an already-open app updates without a foreground/resume.
    /// Mirrors the desktop worker. Reconnects on drop; idles cheaply between.
    fn spawn_sse_listener(app: AppHandle) {
        use std::io::BufRead;
        std::thread::spawn(move || loop {
            let saved = load_config(&app).ok().flatten().unwrap_or(Value::Null);
            let relay = saved.get("relay_url").and_then(|v| v.as_str()).unwrap_or("").to_string();
            let secret = saved.get("secret").and_then(|v| v.as_str()).unwrap_or("").to_string();
            if relay.is_empty() || secret.is_empty() {
                std::thread::sleep(std::time::Duration::from_secs(5));
                continue;
            }
            let url = format!(
                "{}/sync/events?token={}",
                relay.trim_end_matches('/'),
                secret
            );
            // A read timeout longer than the relay's 15s heartbeat: a live stream
            // never trips it, a dead one breaks within the window and reconnects.
            let agent = ureq::AgentBuilder::new()
                .timeout_read(std::time::Duration::from_secs(45))
                .build();
            if let Ok(resp) = agent.get(&url).call() {
                let reader = std::io::BufReader::new(resp.into_reader());
                for line in reader.lines() {
                    match line {
                        // A data line means something changed on the relay; heartbeats
                        // (": ping") and blank lines are ignored.
                        Ok(l) if l.starts_with("data:") => run_sync_once(&app),
                        Ok(_) => {}
                        Err(_) => break, // stream dropped; fall through to reconnect
                    }
                }
            }
            std::thread::sleep(std::time::Duration::from_secs(5));
        });
    }

    /// Pull the encrypted library into the local SQLite read copy (MOB.3). A non-empty
    /// config unlocks the DEK from the imported keyring + phrase, then persists the
    /// secret + DEK (MOB.3b). An empty config falls back to the persisted one, so a
    /// relaunch syncs without re-entering anything.
    #[tauri::command]
    fn mobile_sync(app: AppHandle, config: String) -> Result<String, String> {
        let cfg: Value = serde_json::from_str(&config).unwrap_or(Value::Null);
        // The UI calls this with config "{}" and relies on the persisted config
        // (mobile.html sends no args on the on-load and Sync Now paths). Fall back to
        // the saved config for relay_url and the secret so those paths are not treated
        // as "not configured". The saved config stores the secret under `secret`.
        let saved = load_config(&app).ok().flatten().unwrap_or(Value::Null);
        let pick = |k: &str| cfg.get(k).and_then(|v| v.as_str())
            .or_else(|| saved.get(k).and_then(|v| v.as_str()))
            .unwrap_or("").to_string();
        let relay_url = pick("relay_url");
        let sync_secret = {
            let s = pick("sync_secret");
            if s.is_empty() { saved.get("secret").and_then(|v| v.as_str()).unwrap_or("").to_string() } else { s }
        };
        let keyring_json = pick("keyring_json");
        let recovery_phrase = pick("recovery_phrase");

        // Validate config exists
        if relay_url.is_empty() || sync_secret.is_empty() {
            return Err("sync not configured".into());
        }

        // Open the library connection
        let conn = open_lib(&app)?;

        // Spawn sync_library on a background thread so the UI doesn't freeze (QR.5a).
        // The thread will emit events (sync-started, sync-progress, sync-done, sync-error)
        // that mobile.html listens for, instead of awaiting the command result.
        // Copy the needed values into the closure so cfg is not captured.
        let relay_url_owned = relay_url.clone();
        let sync_secret_owned = sync_secret.clone();
        let _keyring_json_owned = keyring_json.clone();
        let _recovery_phrase_owned = recovery_phrase.clone();
        let app_handle = app.clone();
        let conn_clone = conn;

        std::thread::spawn(move || {
            // Use a panic catch to ensure we always emit a completion event
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                // Emit sync-started event
                let _ = app_handle.emit("sync-started", serde_json::json!({}));

                // Load the saved config to get the DEK (hex-encoded in config)
                let dek = load_config(&app_handle)
                    .ok()
                    .flatten()
                    .and_then(|cfg| cfg.get("dek").and_then(|v| v.as_str()).map(|s| s.to_string()))
                    .and_then(|s| hex::decode(&s).ok())
                    .and_then(|bytes| bytes.try_into().ok());

                // Run sync_library in the background with the DEK loaded from config
                let outcome = crate::sync::sync_library(&relay_url_owned, &sync_secret_owned,
                    dek.as_ref(),
                    &conn_clone);
                let ids = crate::sync::list_artifact_ids(&conn_clone).unwrap_or_default();

                // Emit the result event
                let err_str = outcome.error.as_deref().unwrap_or("");
                let _ = app_handle.emit(
                    if err_str.is_empty() { "sync-done" } else { "sync-error" },
                    serde_json::json!({
                        "status": outcome.status,
                        "pulled": outcome.pulled,
                        "error": outcome.error,
                        "artifact_ids": ids,
                    }),
                );
            }));
            
            // If the thread panicked, emit sync-error
            if result.is_err() {
                let _ = app_handle.emit(
                    "sync-error",
                    serde_json::json!({
                        "status": "error",
                        "pulled": 0,
                        "error": Some("sync thread panicked".to_string()),
                        "artifact_ids": Vec::<String>::new(),
                    }),
                );
            }
        });

        // Return immediately; the UI will listen for sync events
        Ok(serde_json::json!({ "started": true }).to_string())
    }

    /// Whether a sync config (secret + DEK) has been persisted, so the UI can decide
    /// between the setup surface and the library (MOB.3b).
    #[tauri::command]
    fn mobile_status(app: AppHandle) -> Result<String, String> {
        let configured = load_config(&app)?.is_some();
        Ok(serde_json::json!({ "configured": configured }).to_string())
    }

    /// The synced library rows for the Library surface (MOB.4).
    #[tauri::command]
    fn mobile_list(app: AppHandle) -> Result<String, String> {
        let conn = open_lib(&app)?;
        let arts = crate::sync::list_artifacts(&conn).map_err(|e| e.to_string())?;
        Ok(serde_json::json!(arts).to_string())
    }

    /// The saved views (custom pivots) synced from the desktop, as
    /// `{"views":[{name, ids}]}`. Empty until the desktop has pushed lib/pivots.enc.
    #[tauri::command]
    fn mobile_pivots(app: AppHandle) -> Result<String, String> {
        let conn = open_lib(&app)?;
        let json: Option<String> = conn
            .query_row("SELECT value FROM sync_meta WHERE key='pivots'", [], |r| r.get(0))
            .ok();
        Ok(json.unwrap_or_else(|| "{\"views\":[]}".to_string()))
    }

    /// One artifact plus its annotations for the Reader surface (MOB.5).
    #[tauri::command]
    fn mobile_get(app: AppHandle, id: String) -> Result<String, String> {
        let conn = open_lib(&app)?;
        let art = crate::sync::get_artifact(&conn, &id).map_err(|e| e.to_string())?;
        Ok(art.to_string())
    }

    /// Keyword search over the synced library (MOB.6).
    #[tauri::command]
    fn mobile_search(app: AppHandle, query: String) -> Result<String, String> {
        let conn = open_lib(&app)?;
        let arts = crate::sync::search_artifacts(&conn, &query).map_err(|e| e.to_string())?;
        Ok(serde_json::json!(arts).to_string())
    }

    fn now_iso() -> String {
        chrono::Utc::now()
            .format("%Y-%m-%dT%H:%M:%S%.6f+00:00")
            .to_string()
    }

    fn looks_like_link(text: &str) -> bool {
        let t = text.trim();
        if t.is_empty() || t.contains(char::is_whitespace) {
            return false;
        }
        t.starts_with("http://")
            || t.starts_with("https://")
            || t.starts_with("www.")
            || (t.contains('.') && !t.ends_with('.'))
    }

    /// Create a note or link locally, then push its snapshot (MOB.7). A bare URL becomes
    /// a link, a URL plus words a link with a note, plain text a note - the desktop
    /// overlay's four-outcomes logic minus the image path (which needs the blob push).
    #[tauri::command]
    fn mobile_capture(app: AppHandle, text: String) -> Result<String, String> {
        let trimmed = text.trim().to_string();
        if trimmed.is_empty() {
            return Err("empty capture".into());
        }

        let conn = open_lib(&app)?;
        let id = uuid::Uuid::new_v4().to_string();
        let now = now_iso();

        // Split a URL from surrounding words, like the desktop's splitLink.
        let words: Vec<&str> = trimmed.split_whitespace().collect();
        let url_at = words.iter().position(|w| looks_like_link(w));
        let (kind, source_url, body, annotation) = match url_at {
            Some(at) => {
                let url = words[at].to_string();
                let inside = at != 0 && at != words.len() - 1;
                let note = if inside {
                    trimmed.clone()
                } else {
                    words
                        .iter()
                        .enumerate()
                        .filter(|(i, _)| *i != at)
                        .map(|(_, w)| *w)
                        .collect::<Vec<_>>()
                        .join(" ")
                };
                ("link", Some(url), None, (!note.trim().is_empty()).then_some(note))
            }
            None => ("note", None, Some(trimmed.clone()), None),
        };

        let title = if kind == "link" {
            source_url.clone().unwrap_or_else(|| "link".into())
        } else {
            body.clone().unwrap_or_default()
        };
        let title = crate::sync::title_hint(&title);

        conn.execute(
            "INSERT INTO artifacts (id,kind,title,body,source_url,content_hash,mime,filename,
             created_at,updated_at,local_only,status,pinned,deleted_at,pages,title_explicit,_device_id)
             VALUES (?1,?2,?3,?4,?5,?6,NULL,NULL,?7,?7,0,'ok',0,NULL,NULL,0,NULL)",
            rusqlite::params![id, kind, title, body, source_url, uuid::Uuid::new_v4().to_string(), now],
        )
        .map_err(|e| e.to_string())?;

        // Queue to the outbox so a failed inline push (e.g. offline) is retried by
        // mobile_outbox_push on the next sync. Text notes previously skipped this,
        // so a note captured offline never synced up after reconnecting.
        conn.execute(
            "INSERT INTO capture_outbox (id,kind,title,body,source_url,content_hash,mime,filename,
             created_at,updated_at,local_only,status,pinned,deleted_at,pages,title_explicit,_device_id)
             VALUES (?1,?2,?3,?4,?5,?6,NULL,NULL,?7,?7,0,'pending',0,NULL,NULL,0,NULL)",
            rusqlite::params![id, kind, title, body, source_url, uuid::Uuid::new_v4().to_string(), now],
        )
        .map_err(|e| e.to_string())?;

        if let Some(note) = annotation {
            conn.execute(
                "INSERT INTO annotations (id,artifact_id,supersedes_id,text,created_at)
                 VALUES (?1,?2,NULL,?3,?4)",
                rusqlite::params![uuid::Uuid::new_v4().to_string(), id, note, now],
            )
            .map_err(|e| e.to_string())?;
        }

        // Push the snapshot when sync is configured + unlocked.
        if let Some(cfg) = load_config(&app)? {
            if let Some(dek) = cfg.get("dek").and_then(Value::as_str).and_then(dek_from_hex) {
                if let Some(snapshot) = crate::sync::build_snapshot(&conn, &id)? {
                    let mut snapshot = snapshot;
                    snapshot["artifact"]["_device_id"] = serde_json::Value::String(
                        crate::sync::device_id(&app.path().app_data_dir().map_err(|e| e.to_string())?),
                    );
                    let relay_url = cfg.get("relay_url").and_then(Value::as_str).unwrap_or("");
                    let secret = cfg.get("secret").and_then(Value::as_str).unwrap_or("");
                    let _ = crate::sync::push_snapshot(relay_url, secret, &dek, &snapshot["artifact"]["_device_id"].as_str().unwrap_or(""), &snapshot);
                }
            }
        }

        let art = crate::sync::get_artifact(&conn, &id).map_err(|e| e.to_string())?;
        Ok(art.to_string())
    }

    /// Fetch (or load the cached) file blob for an image/PDF/file artifact or a
    /// link preview image, returning `{mime, base64}` for the reader and thumbnails
    /// (MOB.5). Accepts either an artifact id (UUID) or a content hash (64 hex chars).
    /// Optional `mime` parameter can be provided when fetching by content hash.
    #[tauri::command]
    fn mobile_blob(app: AppHandle, id: String, mime: Option<String>) -> Result<String, String> {
        use base64::Engine as _;
        
        // Check if id is a content hash (64 hex chars) or an artifact id (UUID)
        let is_content_hash = id.len() == 64 && id.chars().all(|c| c.is_ascii_hexdigit());
        
        let (content_hash, resolved_mime) = if is_content_hash {
            // Direct content hash - use provided mime or default
            (id, mime.unwrap_or_else(|| "image/png".to_string()))
        } else {
            let conn = open_lib(&app)?;
            let art = crate::sync::get_artifact(&conn, &id).map_err(|e| e.to_string())?;
            let content_hash = art["artifact"]["content_hash"]
                .as_str()
                .unwrap_or("")
                .to_string();
            let artifact_mime = art["artifact"]["mime"].as_str().unwrap_or("").to_string();
            if content_hash.is_empty() {
                return Err("no blob".into());
            }
            (content_hash, artifact_mime)
        };

        let dir = app
            .path()
            .app_data_dir()
            .map_err(|e| e.to_string())?
            .join("blobs");
        std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
        let cache_path = dir.join(&content_hash);

        let bytes = if cache_path.exists() {
            std::fs::read(&cache_path).map_err(|e| e.to_string())?
        } else {
            let cfg = load_config(&app)?.ok_or("not configured")?;
            let dek = cfg
                .get("dek")
                .and_then(Value::as_str)
                .and_then(dek_from_hex)
                .ok_or("locked")?;
            let relay_url = cfg.get("relay_url").and_then(Value::as_str).unwrap_or("");
            let secret = cfg.get("secret").and_then(Value::as_str).unwrap_or("");
            let bytes = crate::sync::fetch_blob(relay_url, secret, &dek, &content_hash)?;
            let _ = std::fs::write(&cache_path, &bytes);
            bytes
        };

        let b64 = general_purpose::STANDARD.encode(&bytes);
        Ok(serde_json::json!({ "mime": resolved_mime, "base64": b64 }).to_string())
    }

    /// Initialize the outbox schema for pending captures (MOB.7).
    fn init_outbox_schema(conn: &Connection) -> Result<(), String> {
        conn.execute_batch(
            r#"
            CREATE TABLE IF NOT EXISTS capture_outbox (
              id            TEXT PRIMARY KEY,
              kind          TEXT NOT NULL,
              title         TEXT NOT NULL,
              body          TEXT,
              source_url    TEXT,
              content_hash  TEXT,
              mime          TEXT,
              filename      TEXT,
              created_at    TEXT NOT NULL,
              updated_at    TEXT NOT NULL,
              local_only    INTEGER NOT NULL DEFAULT 0,
              status        TEXT NOT NULL DEFAULT 'pending',
              pinned        INTEGER NOT NULL DEFAULT 0,
              deleted_at    TEXT,
              pages         INTEGER,
              title_explicit INTEGER NOT NULL DEFAULT 0,
              _device_id    TEXT
            );

            CREATE TABLE IF NOT EXISTS mutation_outbox (
              id            TEXT PRIMARY KEY,
              artifact_id   TEXT NOT NULL,
              mutation_type TEXT NOT NULL,  -- 'delete' | 'restore'
              created_at    TEXT NOT NULL,
              synced        INTEGER NOT NULL DEFAULT 0
            );
            "#,
        )
        .map_err(|e| e.to_string())?;
        Ok(())
    }

    /// Capture an image from the photo picker (MOB.7).
    #[tauri::command]
    async fn mobile_capture_image(app: AppHandle) -> Result<String, String> {
        use tauri_plugin_dialog::DialogExt;
        
        let conn = open_lib(&app)?;
        let id = uuid::Uuid::new_v4().to_string();
        let now = now_iso();
        
        // Open photo picker
        let file_path = app
            .dialog()
            .file()
            .add_filter("Images", &["png", "jpg", "jpeg", "gif", "webp", "heic"])
            .blocking_pick_file()
            .ok_or("cancelled")?;
        
        let path = match file_path {
            tauri_plugin_dialog::FilePath::Path(p) => p,
            tauri_plugin_dialog::FilePath::Url(_) => return Err("unsupported file path type".into()),
        };
        
        // Read and hash the image
        let bytes = std::fs::read(&path).map_err(|e| format!("read image: {e}"))?;
        let mut hasher = sha2::Sha256::new();
        hasher.update(&bytes);
        let content_hash = hex::encode(hasher.finalize());
        
        // Determine MIME type
        let mime = match path.extension().and_then(|s| s.to_str()).unwrap_or("").to_lowercase().as_str() {
            "jpg" | "jpeg" => "image/jpeg",
            "png" => "image/png",
            "gif" => "image/gif",
            "webp" => "image/webp",
            "heic" => "image/heic",
            _ => "application/octet-stream",
        };
        
        let filename = path.file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("image")
            .to_string();
        
        let title = filename.clone();
        
        // Store blob locally
        let dir = app
            .path()
            .app_data_dir()
            .map_err(|e| e.to_string())?
            .join("blobs");
        std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
        let cache_path = dir.join(&content_hash);
        std::fs::write(&cache_path, &bytes).map_err(|e| e.to_string())?;
        
        // Insert into artifacts as pending
        conn.execute(
            "INSERT INTO artifacts (id,kind,title,body,source_url,content_hash,mime,filename,\n             created_at,updated_at,local_only,status,pinned,deleted_at,pages,title_explicit,_device_id)\n             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?9,0,'pending',0,NULL,NULL,0,NULL)",
            rusqlite::params![
                id,
                "image",
                title,
                None::<String>,
                None::<String>,
                content_hash,
                mime,
                filename,
                now,
            ],
        )
        .map_err(|e| e.to_string())?;
        
        // Add to outbox for sync
        conn.execute(
            "INSERT INTO capture_outbox (id,kind,title,body,source_url,content_hash,mime,filename,\n             created_at,updated_at,local_only,status,pinned,deleted_at,pages,title_explicit,_device_id)\n             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?9,0,'pending',0,NULL,NULL,0,NULL)",
            rusqlite::params![
                id,
                "image",
                title,
                None::<String>,
                None::<String>,
                content_hash,
                mime,
                filename,
                now,
            ],
        )
        .map_err(|e| e.to_string())?;
        
        // Try to push immediately if sync configured
        if let Some(cfg) = load_config(&app)? {
            if let Some(dek) = cfg.get("dek").and_then(Value::as_str).and_then(dek_from_hex) {
                if let Some(snapshot) = crate::sync::build_snapshot(&conn, &id)? {
                    let mut snapshot = snapshot;
                    snapshot["artifact"]["_device_id"] = serde_json::Value::String(
                        crate::sync::device_id(&app.path().app_data_dir().map_err(|e| e.to_string())?),
                    );
                    let relay_url = cfg.get("relay_url").and_then(Value::as_str).unwrap_or("");
                    let secret = cfg.get("secret").and_then(Value::as_str).unwrap_or("");
                    // The push result is authoritative (DEAD.7): if push_snapshot returned
                    // Ok the object is on the relay, so mark it synced and drop the outbox
                    // row - no extra GET to read the object back.
                    // Mark synced only when BOTH the snapshot and the blob are on the
                    // relay - an image is not really synced until its bytes are up, and
                    // flipping status to 'ok' early left blob-less images that render as
                    // text_only on the desktop. On any failure the row stays 'pending'
                    // with its outbox entry, so mobile_outbox_push retries it later.
                    if crate::sync::push_snapshot(relay_url, secret, &dek, snapshot["artifact"]["_device_id"].as_str().unwrap_or(""), &snapshot).is_ok()
                        && push_capture_blob(&app, &conn, &id, relay_url, secret, &dek).unwrap_or(false)
                    {
                        let _ = conn.execute("UPDATE artifacts SET status = 'ok' WHERE id = ?1", [&id]);
                        let _ = conn.execute("DELETE FROM capture_outbox WHERE id = ?1", [&id]);
                    }
                }
            }
        }
        
        let art = crate::sync::get_artifact(&conn, &id).map_err(|e| e.to_string())?;
        Ok(art.to_string())
    }


    /// Pick an image from the gallery and return {base64, mime} (MOB2.6). Does NOT
    /// create an artifact - just returns the image data for crop/rotate.
    ///
    /// On Android the system photo picker returns a content:// URI, which the tauri
    /// dialog surfaces as `FilePath::Url` and which `std::fs::read` cannot open - so
    /// the pick is done in Kotlin (MainActivity.pickImage) and the bytes are read via
    /// the ContentResolver, exactly like the camera path. The desktop build keeps the
    /// plain file dialog.
    #[cfg(target_os = "android")]
    #[tauri::command]
    async fn mobile_pick_image(_app: AppHandle) -> Result<String, String> {
        use std::sync::mpsc;

        let (tx, rx) = mpsc::channel();

        std::thread::spawn(move || -> Result<(), String> {
            let result: Result<String, String> = (|| {
                let vm_arc = crate::get_android_vm()?;
                let mut env = vm_arc
                    .attach_current_thread()
                    .map_err(|e| format!("Failed to attach thread: {}", e))?;

                let main_activity_class_global = crate::get_main_activity_class()?;
                let main_activity_class = unsafe {
                    jni::objects::JClass::from(jni::objects::JObject::from_raw(
                        main_activity_class_global.as_obj().as_raw(),
                    ))
                };

                let activity = env
                    .call_static_method::<_, &str, &str>(
                        &main_activity_class,
                        "getCurrentActivity",
                        "()Lcom/sudohnim/enqueue/MainActivity;",
                        &[],
                    )
                    .map_err(|e| format!("Failed to call getCurrentActivity: {:?}", e))?
                    .l()
                    .map_err(|e| format!("Failed to get activity: {:?}", e))?;

                let future = env
                    .call_method(
                        &activity,
                        "pickImage",
                        "()Ljava/util/concurrent/CompletableFuture;",
                        &[],
                    )
                    .map_err(|e| format!("Failed to call pickImage: {:?}", e))?
                    .l()
                    .map_err(|e| format!("Failed to get future: {:?}", e))?;

                let future_obj = unsafe { jni::objects::JObject::from_raw(future.as_raw()) };
                let result_obj = env
                    .call_method(&future_obj, "get", "()Ljava/lang/Object;", &[])
                    .map_err(|e| format!("Failed to call get: {:?}", e))?
                    .l()
                    .map_err(|e| format!("Failed to get result: {:?}", e));

                let result_obj = result_obj.map_err(|e| format!("Failed to get result object: {}", e))?;
                let result_str = if result_obj.is_null() {
                    return Err("Image pick cancelled or failed".into());
                } else {
                    let string_class = env
                        .find_class("java/lang/String")
                        .map_err(|e| format!("Failed to find String class: {}", e))?;
                    if env.is_instance_of(&result_obj, &string_class).unwrap_or(false) {
                        let jstring = jni::objects::JString::from(result_obj);
                        let java_str = env
                            .get_string(&jstring)
                            .map_err(|e| format!("Failed to get string: {}", e))?;
                        java_str.into()
                    } else {
                        return Err("Unexpected result type from picker".into());
                    }
                };

                Ok(result_str)
            })();

            tx.send(result).map_err(|e| format!("Failed to send result: {}", e))?;
            Ok(())
        });

        rx.recv().map_err(|e| format!("Channel error: {}", e))?
    }

    #[cfg(not(target_os = "android"))]
    #[tauri::command]
    async fn mobile_pick_image(app: AppHandle) -> Result<String, String> {
        use tauri_plugin_dialog::DialogExt;

        let file_path = app
            .dialog()
            .file()
            .add_filter("Images", &["png", "jpg", "jpeg", "gif", "webp", "heic"])
            .blocking_pick_file()
            .ok_or("cancelled")?;

        let path = match file_path {
            tauri_plugin_dialog::FilePath::Path(p) => p,
            tauri_plugin_dialog::FilePath::Url(_) => return Err("unsupported file path type".into()),
        };

        let bytes = std::fs::read(&path).map_err(|e| format!("read image: {e}"))?;
        let mime = match path.extension().and_then(|s| s.to_str()).unwrap_or("").to_lowercase().as_str() {
            "jpg" | "jpeg" => "image/jpeg",
            "png" => "image/png",
            "gif" => "image/gif",
            "webp" => "image/webp",
            "heic" => "image/heic",
            _ => "application/octet-stream",
        };

        let base64 = general_purpose::STANDARD.encode(&bytes);
        Ok(serde_json::json!({ "base64": base64, "mime": mime }).to_string())
    }

    /// Capture an image using the device camera (MOBFIX.3).
    /// Uses Android's ACTION_IMAGE_CAPTURE intent via MainActivity.
    #[cfg(target_os = "android")]
    #[tauri::command]
    async fn mobile_capture_camera(_app: AppHandle) -> Result<String, String> {
        use std::sync::mpsc;
        use jni::objects::{JClass, JString, JValue};
        
        let (tx, rx) = mpsc::channel();
        
        // Run JNI code on a background thread
        std::thread::spawn(move || -> Result<(), String> {
            use jni::objects::{JClass, JString, JValue};
            use jni::JNIEnv;
            
            let result: Result<String, String> = (|| {
                let vm_arc = crate::get_android_vm()?;
                let mut env = vm_arc.attach_current_thread()
                    .map_err(|e| format!("Failed to attach thread: {}", e))?;
                
                // Get the MainActivity class from global reference (stored in JNI_OnLoad)
                let main_activity_class_global = crate::get_main_activity_class()?;
                // Clone the JObject from the GlobalRef (JObject implements Clone)
                let main_activity_class = unsafe {
                    jni::objects::JClass::from(jni::objects::JObject::from_raw(main_activity_class_global.as_obj().as_raw()))
                };
                
                // Call static MainActivity.getCurrentActivity() to get the activity instance
                let activity = env.call_static_method::<_, &str, &str>(
                    &main_activity_class,
                    "getCurrentActivity",
                    "()Lcom/sudohnim/enqueue/MainActivity;",
                    &[]
                ).map_err(|e| format!("Failed to call getCurrentActivity: {:?}", e))?.l().map_err(|e| format!("Failed to get activity: {:?}", e))?;
                
                // Call instance method captureImage() on the activity
                let future = env.call_method(
                    &activity,
                    "captureImage",
                    "()Ljava/util/concurrent/CompletableFuture;",
                    &[]
                ).map_err(|e| format!("Failed to call captureImage: {:?}", e))?.l().map_err(|e| format!("Failed to get future: {:?}", e))?;
                
                // Wait for the future to complete (blocking - in production use a timeout)
                let future_obj = unsafe { jni::objects::JObject::from_raw(future.as_raw()) };
                let result_obj = env.call_method(
                    &future_obj,
                    "get",
                    "()Ljava/lang/Object;",
                    &[]
                ).map_err(|e| format!("Failed to call get: {:?}", e))?.l().map_err(|e| format!("Failed to get result: {:?}", e));
                
                // Convert result to string
                let result_obj = result_obj.map_err(|e| format!("Failed to get result object: {}", e))?;
                let result_str = if result_obj.is_null() {
                    return Err("Camera capture cancelled or failed".into());
                } else {
                    let string_class = env.find_class("java/lang/String")
                        .map_err(|e| format!("Failed to find String class: {}", e))?;
                    if env.is_instance_of(&result_obj, &string_class).unwrap_or(false) {
                        let jstring = jni::objects::JString::from(result_obj);
                        let java_str = env.get_string(&jstring)
                            .map_err(|e| format!("Failed to get string: {}", e))?;
                        java_str.into()
                    } else {
                        return Err("Unexpected result type from camera".into());
                    }
                };
                
                Ok(result_str)
            })();
            
            tx.send(result).map_err(|e| format!("Failed to send result: {}", e))?;
            Ok(())
        });
        
        // Wait for the result from the background thread
        rx.recv().map_err(|e| format!("Channel error: {}", e))?
    }
    #[cfg(not(target_os = "android"))]
    #[tauri::command]
    async fn mobile_capture_camera(_app: AppHandle) -> Result<String, String> {
        Err("Camera capture only available on Android".into())
    }

    /// Save a cropped/rotated image as an artifact (MOB2.6).
    #[tauri::command]
    fn mobile_save_cropped_image(app: AppHandle, base64: String, mime: String) -> Result<String, String> {
        use base64::Engine as _;
        
        let conn = open_lib(&app)?;
        let id = uuid::Uuid::new_v4().to_string();
        let now = now_iso();
        
        let bytes = base64::engine::general_purpose::STANDARD.decode(&base64)
            .map_err(|e| format!("base64 decode: {e}"))?;
        
        let mut hasher = sha2::Sha256::new();
        hasher.update(&bytes);
        let content_hash = hex::encode(hasher.finalize());
        
        let filename = format!("image.{}", match mime.as_str() {
            "image/jpeg" => "jpg",
            "image/png" => "png",
            "image/gif" => "gif",
            "image/webp" => "webp",
            "image/heic" => "heic",
            _ => "img",
        });
        
        let title = filename.clone();
        
        // Store blob locally
        let dir = app
            .path()
            .app_data_dir()
            .map_err(|e| e.to_string())?
            .join("blobs");
        std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
        let cache_path = dir.join(&content_hash);
        std::fs::write(&cache_path, &bytes).map_err(|e| e.to_string())?;
        
        // Insert into artifacts as pending
        conn.execute(
            "INSERT INTO artifacts (id,kind,title,body,source_url,content_hash,mime,filename,\n             created_at,updated_at,local_only,status,pinned,deleted_at,pages,title_explicit,_device_id)\n             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?9,0,'pending',0,NULL,NULL,0,NULL)",
            rusqlite::params![
                id,
                "image",
                title,
                None::<String>,
                None::<String>,
                content_hash,
                mime,
                filename,
                now,
            ],
        )
        .map_err(|e| e.to_string())?;
        
        // Add to outbox for sync
        conn.execute(
            "INSERT INTO capture_outbox (id,kind,title,body,source_url,content_hash,mime,filename,\n             created_at,updated_at,local_only,status,pinned,deleted_at,pages,title_explicit,_device_id)\n             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?9,0,'pending',0,NULL,NULL,0,NULL)",
            rusqlite::params![
                id,
                "image",
                title,
                None::<String>,
                None::<String>,
                content_hash,
                mime,
                filename,
                now,
            ],
        )
        .map_err(|e| e.to_string())?;
        
        // Try to push immediately if sync configured
        if let Some(cfg) = load_config(&app)? {
            if let Some(dek) = cfg.get("dek").and_then(Value::as_str).and_then(dek_from_hex) {
                if let Some(snapshot) = crate::sync::build_snapshot(&conn, &id)? {
                    let mut snapshot = snapshot;
                    snapshot["artifact"]["_device_id"] = serde_json::Value::String(
                        crate::sync::device_id(&app.path().app_data_dir().map_err(|e| e.to_string())?),
                    );
                    let relay_url = cfg.get("relay_url").and_then(Value::as_str).unwrap_or("");
                    let secret = cfg.get("secret").and_then(Value::as_str).unwrap_or("");
                    // The push result is authoritative (DEAD.7): no GET-back needed.
                    // Mark synced only when BOTH the snapshot and the blob are on the
                    // relay - an image is not really synced until its bytes are up, and
                    // flipping status to 'ok' early left blob-less images that render as
                    // text_only on the desktop. On any failure the row stays 'pending'
                    // with its outbox entry, so mobile_outbox_push retries it later.
                    if crate::sync::push_snapshot(relay_url, secret, &dek, snapshot["artifact"]["_device_id"].as_str().unwrap_or(""), &snapshot).is_ok()
                        && push_capture_blob(&app, &conn, &id, relay_url, secret, &dek).unwrap_or(false)
                    {
                        let _ = conn.execute("UPDATE artifacts SET status = 'ok' WHERE id = ?1", [&id]);
                        let _ = conn.execute("DELETE FROM capture_outbox WHERE id = ?1", [&id]);
                    }
                }
            }
        }
        
        let art = crate::sync::get_artifact(&conn, &id).map_err(|e| e.to_string())?;
        Ok(art.to_string())
    }



    /// The LLM config synced from the desktop (MOB2.9), cached in sync_meta by the
    /// pull loop. This is the source of truth for mobile chat: the desktop pushes its
    /// effective backend / model / url / api_key (E2E-encrypted), so the phone runs
    /// chat with the same provider without anyone re-entering it here. Returns None
    /// when nothing has synced yet, and the caller falls back to the local config.
    fn synced_settings(conn: &Connection) -> Option<Value> {
        conn.query_row(
            "SELECT value FROM sync_meta WHERE key = 'settings'",
            [],
            |row| row.get::<_, String>(0),
        )
        .ok()
        .and_then(|s| serde_json::from_str::<Value>(&s).ok())
    }

/// Mobile chat: keyword search + LLM answer (MOB2.7).
    #[tauri::command]
    fn mobile_chat(app: AppHandle, query: String, _history: String) -> Result<String, String> {
        let conn = open_lib(&app)?;

        // 1. Keyword search over local copy (MOB.6)
        let arts = crate::sync::search_artifacts(&conn, &query).map_err(|e| e.to_string())?;
        if arts.is_empty() {
            return Ok(serde_json::json!({
                "answer": "I couldn't find anything relevant in your notes.",
                "citations": Vec::<String>::new(),
                "error": null
            }).to_string());
        }
        
        // 2. Build passages from matched artifacts (newest first, cap tokens)
        let mut passages = Vec::new();
        let mut total_chars = 0;
        const MAX_CHARS: usize = 8000;
        
        for art in arts {
            let body = art["body"].as_str().unwrap_or("");
            if body.is_empty() { continue; }
            let passage = format!("Source [{}]: {}", art["id"].as_str().unwrap_or(""), body);
            if total_chars + passage.len() > MAX_CHARS { break; }
            total_chars += passage.len();
            passages.push(passage);
        }
        
        if passages.is_empty() {
            return Ok(serde_json::json!({
                "answer": "I couldn't find anything relevant in your notes.",
                "citations": Vec::<String>::new(),
                "error": null
            }).to_string());
        }
        
        // 3. Load config for LLM backend and API key. The desktop-synced settings
        //    (MOB2.9) win over the phone-local config when present, so mobile chat
        //    uses whatever provider the desktop is configured with - key included.
        let cfg = load_config(&app)?.ok_or("not configured")?;
        let _dek = cfg.get("dek").and_then(Value::as_str).and_then(dek_from_hex).ok_or("locked")?;
        let synced = synced_settings(&conn);
        // Prefer synced[field], fall back to the local config, then the default.
        let pick = |field: &str, default: &str| -> String {
            synced
                .as_ref()
                .and_then(|s| s.get(field))
                .and_then(Value::as_str)
                .filter(|v| !v.is_empty())
                .or_else(|| cfg.get(field).and_then(Value::as_str))
                .unwrap_or(default)
                .to_string()
        };
        let backend = pick("llm_backend", "ollama");
        let model = pick("llm_model", "llama3.1:8b");
        let llm_url = pick("llm_url", "");
        let api_key = pick("llm_api_key", "");
        // call_llm_mobile reads a url only for the ollama/custom backends.
        let custom_url = if backend == "custom" || backend == "ollama" { llm_url.as_str() } else { "" };
        let backend = backend.as_str();
        let model = model.as_str();
        let api_key = api_key.as_str();
        
        // 4. Build prompt
        let context = passages.join("\n\n---\n\n");
        let prompt = format!(
            "Answer the question using ONLY the provided context. Cite sources by their [id] in square brackets.\n\nContext:\n{}\n\nQuestion: {}\n\nAnswer:",
            context, query
        );
        
        // 5. Call LLM - for mobile we need to call provider directly
        let answer = call_llm_mobile(&backend, &model, &custom_url, &api_key, &prompt)
            .map_err(|e| e.to_string())?;
        
        // 6. Extract citations from answer
        let cited_ids = extract_citations(&answer);
        
        Ok(serde_json::json!({
            "answer": answer,
            "citations": cited_ids,
            "error": null
        }).to_string())
    }
    
    fn call_llm_mobile(backend: &str, model: &str, custom_url: &str, api_key: &str, prompt: &str) -> Result<String, String> {
        // Use ureq to call the provider directly
        let body = serde_json::json!({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": false
        });
        
        let (url, auth_header) = match backend {
            "ollama" => {
                let url = if custom_url.is_empty() { "http://127.0.0.1:11434/api/chat" } else { custom_url };
                (url.to_string(), None)
            }
            "openrouter" => ("https://openrouter.ai/api/v1/chat/completions".to_string(), Some(format!("Bearer {}", api_key))),
            "opencode-go" => ("https://opencode.ai/zen/go/v1/chat/completions".to_string(), Some(format!("Bearer {}", api_key))),
            "custom" => (custom_url.to_string(), if api_key.is_empty() { None } else { Some(format!("Bearer {}", api_key)) }),
            _ => return Err(format!("unknown backend: {}", backend))
        };
        
        let mut req = ureq::post(&url)
            .set("Content-Type", "application/json");
        if let Some(auth) = auth_header {
            req = req.set("Authorization", &auth);
        }
        
        let body_str = body.to_string();
        let resp = req.send_string(&body_str).map_err(|e| format!("HTTP error: {}", e))?;
        
        let status = resp.status();
        if !(200..300).contains(&status) {
            let err_text = resp.into_string().unwrap_or_default();
            return Err(format!("LLM error {}: {}", status, err_text));
        }
        
        let json: serde_json::Value = resp.into_json().map_err(|e| format!("JSON parse: {}", e))?;
        
        // Extract answer from various response formats
        let answer = json["choices"][0]["message"]["content"]
            .as_str()
            .or_else(|| json["message"]["content"].as_str())
            .or_else(|| json["response"].as_str())
            .unwrap_or("No response from model")
            .to_string();
        
        Ok(answer)
    }
    
    fn extract_citations(text: &str) -> Vec<String> {
        let re = regex::Regex::new(r"\[([a-f0-9-]{36})\]").unwrap();
        re.captures_iter(text)
            .map(|cap| cap[1].to_string())
            .collect()
    }

    
/// Get mobile settings (MOB2.8).
    #[tauri::command]
    fn mobile_settings_get(app: AppHandle) -> Result<String, String> {
        let cfg = load_config(&app)?.unwrap_or_default();
        // Reflect the desktop-synced config (MOB2.9) when it has arrived, so the
        // Settings screen shows what chat will actually use; fall back to local.
        let synced = open_lib(&app).ok().and_then(|c| synced_settings(&c));
        let get = |field: &str, default: &str| -> String {
            synced
                .as_ref()
                .and_then(|s| s.get(field))
                .and_then(Value::as_str)
                .filter(|v| !v.is_empty())
                .or_else(|| cfg.get(field).and_then(Value::as_str))
                .unwrap_or(default)
                .to_string()
        };
        // The key is a secret: report only whether one is set, never the value.
        let has_key = !get("llm_api_key", "").is_empty();
        let managed = synced.is_some();
        Ok(serde_json::json!({
            "llm_backend": get("llm_backend", "ollama"),
            "llm_model": get("llm_model", "llama3.1:8b"),
            "llm_api_key_present": has_key,
            "llm_url": get("llm_url", ""),
            "auto_preview": cfg.get("auto_preview").and_then(Value::as_bool).unwrap_or(true),
            "trash_days": get("trash_days", "30"),
            "last_synced": cfg.get("last_synced").and_then(Value::as_str),
            // When settings are desktop-managed the phone shows them read-only.
            "managed_by_desktop": managed,
            "outbox_count": 0,
        }).to_string())
    }

    /// Set mobile settings (MOB2.8).
    #[tauri::command]
    fn mobile_settings_set(app: AppHandle, settings: String) -> Result<String, String> {
        let new_settings: Value = serde_json::from_str(&settings).map_err(|e| e.to_string())?;
        let mut cfg = load_config(&app)?.unwrap_or_else(|| serde_json::json!({}));
        
        if let Some(v) = new_settings.get("llm_backend") { cfg["llm_backend"] = v.clone(); }
        if let Some(v) = new_settings.get("llm_model") { cfg["llm_model"] = v.clone(); }
        if let Some(v) = new_settings.get("llm_api_key") { cfg["llm_api_key"] = v.clone(); }
        if let Some(v) = new_settings.get("llm_url") { cfg["llm_url"] = v.clone(); }
        if let Some(v) = new_settings.get("auto_preview") { cfg["auto_preview"] = v.clone(); }
        if let Some(v) = new_settings.get("trash_days") { cfg["trash_days"] = v.clone(); }
        
        save_config(
            &app,
            cfg.get("relay_url").and_then(Value::as_str).unwrap_or(""),
            cfg.get("secret").and_then(Value::as_str).unwrap_or(""),
            cfg.get("keyring_json").and_then(Value::as_str).unwrap_or(""),
            &cfg.get("dek").and_then(Value::as_str).and_then(dek_from_hex).unwrap_or([0u8; 32]),
            cfg.get("llm_backend").and_then(Value::as_str),
            cfg.get("llm_model").and_then(Value::as_str),
            cfg.get("llm_api_key").and_then(Value::as_str),
            cfg.get("llm_url").and_then(Value::as_str),
            cfg.get("auto_preview").and_then(Value::as_bool),
            cfg.get("trash_days").and_then(Value::as_str),
        )?;
        Ok("ok".to_string())
    }

    /// Clear blob cache (MOB2.8).
    #[tauri::command]
    fn mobile_clear_blob_cache(app: AppHandle) -> Result<String, String> {
        let dir = app.path().app_data_dir().map_err(|e| e.to_string())?.join("blobs");
        if dir.exists() {
            std::fs::remove_dir_all(&dir).map_err(|e| e.to_string())?;
            std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
        }
        Ok("ok".to_string())
    }


    /// Push any queued offline captures and mutations to the relay (MOB.7 + CRUDSYNC.2).
    #[tauri::command]
    fn mobile_outbox_push(app: AppHandle) -> Result<String, String> {
        let conn = open_lib(&app)?;
        let cfg = load_config(&app)?.ok_or("not configured")?;
        let dek = cfg
            .get("dek")
            .and_then(Value::as_str)
            .and_then(dek_from_hex)
            .ok_or("locked")?;
        let relay_url = cfg.get("relay_url").and_then(Value::as_str).unwrap_or("");
        let secret = cfg.get("secret").and_then(Value::as_str).unwrap_or("");
        let device_id = crate::sync::device_id(&app.path().app_data_dir().map_err(|e| e.to_string())?);
        
        // 1. Push capture_outbox (pending captures)
        let mut stmt = conn
            .prepare("SELECT id FROM capture_outbox ORDER BY created_at")
            .map_err(|e| e.to_string())?;
        let capture_ids: Vec<String> = stmt
            .query_map([], |r| r.get(0))
            .map_err(|e| e.to_string())?
            .filter_map(Result::ok)
            .collect();
        
        let mut pushed = 0;
        let mut push_pending = |id: &str| -> bool {
            let snapshot = match crate::sync::build_snapshot(&conn, id) {
                Ok(Some(s)) => s,
                _ => return false,
            };
            let mut snapshot = snapshot;
            snapshot["artifact"]["_device_id"] = serde_json::Value::String(device_id.clone());
            // Snapshot AND blob must both land before we call it synced (an image with
            // no blob renders as text_only on the desktop). On failure the row stays
            // 'pending' and is retried on the next sync.
            if crate::sync::push_snapshot(&relay_url, &secret, &dek, &device_id, &snapshot).is_ok()
                && push_capture_blob(&app, &conn, id, &relay_url, &secret, &dek).unwrap_or(false)
            {
                let _ = conn.execute("UPDATE artifacts SET status = 'ok' WHERE id = ?1", [id]);
                let _ = conn.execute("DELETE FROM capture_outbox WHERE id = ?1", [id]);
                true
            } else {
                false
            }
        };

        for id in capture_ids {
            if push_pending(&id) {
                pushed += 1;
            }
        }

        // Backstop: any artifact still 'pending' with no outbox row (an earlier build
        // could clear the outbox entry without a successful push, orphaning the row so
        // it never retried). status='pending' in `artifacts` is the real "needs push"
        // signal; drive off it directly. Push is idempotent (relay upserts), so
        // re-pushing costs nothing.
        let orphan_ids: Vec<String> = {
            let mut stmt = conn
                .prepare("SELECT id FROM artifacts WHERE status = 'pending' AND deleted_at IS NULL AND local_only = 0")
                .map_err(|e| e.to_string())?;
            let ids = stmt
                .query_map([], |r| r.get::<_, String>(0))
                .map_err(|e| e.to_string())?
                .filter_map(Result::ok)
                .collect();
            ids
        };
        for id in orphan_ids {
            if push_pending(&id) {
                pushed += 1;
            }
        }

        // 2. Push mutation_outbox (delete/restore mutations)
        let mut stmt = conn
            .prepare("SELECT id, artifact_id, mutation_type FROM mutation_outbox WHERE synced = 0 ORDER BY created_at")
            .map_err(|e| e.to_string())?;
        let mutations: Vec<(String, String, String)> = stmt
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
            .map_err(|e| e.to_string())?
            .filter_map(Result::ok)
            .collect();
        
        for (mutation_id, artifact_id, mutation_type) in mutations {
            if let Some(snapshot) = crate::sync::build_snapshot(&conn, &artifact_id).map_err(|e| e.to_string())? {
                let mut snapshot = snapshot;
                snapshot["artifact"]["_device_id"] = serde_json::Value::String(device_id.clone());
                
                // For restore, we need to clear deleted_at; for delete, we need to set it
                if mutation_type == "restore" {
                    // The local restore already cleared deleted_at, just push
                } else if mutation_type == "delete" {
                    // The local delete already set deleted_at, just push
                }
                
                let result = crate::sync::push_snapshot(&relay_url, &secret, &dek, &device_id, &snapshot);
                if result.is_ok() {
                    let _ = conn.execute("DELETE FROM mutation_outbox WHERE id = ?1", [&mutation_id]);
                    pushed += 1;
                }
            }
        }
        
        Ok(serde_json::json!({ "pushed": pushed }).to_string())
    }

    /// List pending outbox items (MOB.7).
    #[tauri::command]
    fn mobile_outbox_list(app: AppHandle) -> Result<String, String> {
        let conn = open_lib(&app)?;
        let mut stmt = conn
            .prepare("SELECT id FROM capture_outbox ORDER BY created_at")
            .map_err(|e| e.to_string())?;
        let ids: Vec<String> = stmt
            .query_map([], |r| r.get(0))
            .map_err(|e| e.to_string())?
            .filter_map(Result::ok)
            .collect();
        Ok(serde_json::json!({ "pending": ids }).to_string())
    }

    /// Delete an artifact on mobile (CRUDSYNC.2).
    /// Marks deleted_at locally and enqueues a 'delete' mutation for sync.
    #[cfg(mobile)]
    #[tauri::command]
    fn mobile_delete(app: AppHandle, artifact_id: String) -> Result<String, String> {
        let now = now_iso();
        let conn = open_lib(&app)?;

        // Mark as deleted locally AND bump updated_at - the delete snapshot must be
        // newer than the desktop's copy or LWW rejects it and the deletion never lands
        // on the desktop (the bug: deleted on the phone, still present on the desktop).
        let deleted = {
            let mut stmt = conn
                .prepare("UPDATE artifacts SET deleted_at = ?1, updated_at = ?1 WHERE id = ?2 AND deleted_at IS NULL")
                .map_err(|e| e.to_string())?;
            stmt.execute(rusqlite::params![&now, &artifact_id]).map_err(|e| e.to_string())?
        };
        if deleted == 0 {
            return Err("artifact not found or already deleted".into());
        }

        // Enqueue mutation for sync
        let mutation_id = uuid::Uuid::new_v4().to_string();
        let now_iso = now_iso();
        conn.execute(
            "INSERT INTO mutation_outbox (id, artifact_id, mutation_type, created_at, synced)
             VALUES (?, ?, 'delete', ?, 0)",
            [&mutation_id, &artifact_id, &now_iso],
        ).map_err(|e| e.to_string())?;

        Ok(serde_json::json!({ "deleted": true, "id": artifact_id }).to_string())
    }

    /// Link device by scanning a linking QR code (QR.4b).
    /// The config contains {{relay_url, sync_secret, dek}} decoded from the desktop linking QR.
    /// Persists the relay URL, sync secret, and DEK (hex-encoded) via save_config so
    /// load_config can find them, and sync can start.
    #[cfg(mobile)]
    #[tauri::command]
    fn mobile_link_qr(app: AppHandle, config: String) -> Result<String, String> {
        let cfg: serde_json::Value = serde_json::from_str(&config).map_err(|e| e.to_string())?;
        let relay_url = cfg.get("relay_url").and_then(|v| v.as_str()).ok_or("missing relay_url")?.to_string();
        let sync_secret = cfg.get("sync_secret").and_then(|v| v.as_str()).ok_or("missing sync_secret")?.to_string();
        let dek_b64 = cfg.get("dek").and_then(|v| v.as_str()).ok_or("missing dek")?.to_string();
        
        // Decode the DEK from base64; the sync path expects hex-encoded DEK in config
        let dek_bytes = base64::engine::general_purpose::STANDARD.decode(dek_b64.as_bytes()).map_err(|e| e.to_string())?;
        // Must be exactly 32 bytes (DEK_LEN). Erroring here is deliberate: a silent
        // fallback to an all-zero key links "successfully" but then fails every decrypt,
        // so the phone pulls objects yet stores zero artifacts.
        let dek_array: [u8; 32] = dek_bytes.try_into()
            .map_err(|v: Vec<u8>| format!("DEK must be 32 bytes, got {}", v.len()))?;
        let keyring_json_or_empty = String::new();
        
        // Persist relay_url, sync_secret, and DEK (hex) via save_config so
        // load_config can find them and sync can start.
        save_config(&app, &relay_url, &sync_secret, &keyring_json_or_empty, &dek_array, None, None, None, None, None, None)?;
        
        // For now, return success; sync is driven by the events system (QR.5a)
        Ok("linked".to_string())
    }

    /// Bump updated_at and queue the artifact for push, so a mobile edit / tag /
    /// pin / annotation propagates to the desktop. mobile_outbox_push sends the
    /// artifact's CURRENT snapshot on the next sync (the mutation_type is only a
    /// label; the whole snapshot is what travels). Without this the sync fns
    /// mutated only the local read-copy and the change never left the phone.
    /// Push a captured artifact's file blob to the relay if it has one.
    ///
    /// Returns Ok(true) when nothing needed uploading (a note/link, or no cached
    /// blob) OR the upload succeeded, and Ok(false) only when the artifact has a
    /// local blob that failed to upload - the caller keeps its outbox row so the
    /// next `mobile_outbox_push` retries. A picture only reaches other devices once
    /// its blob is on the relay; snapshot-only propagation is why images used to
    /// stay stuck on the phone that took them while notes and links synced fine.
    fn push_capture_blob(
        app: &AppHandle,
        conn: &Connection,
        id: &str,
        relay_url: &str,
        secret: &str,
        dek: &[u8; 32],
    ) -> Result<bool, String> {
        let row: Option<(String, Option<String>)> = conn
            .query_row(
                "SELECT kind, content_hash FROM artifacts WHERE id = ?1",
                [id],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()
            .map_err(|e| e.to_string())?;
        let Some((kind, Some(content_hash))) = row else {
            return Ok(true);
        };
        if !matches!(kind.as_str(), "image" | "pdf" | "file") || content_hash.is_empty() {
            return Ok(true);
        }
        let cache_path = app
            .path()
            .app_data_dir()
            .map_err(|e| e.to_string())?
            .join("blobs")
            .join(&content_hash);
        let bytes = match std::fs::read(&cache_path) {
            Ok(b) => b,
            // No local blob (e.g. a pulled-only artifact): nothing for this device
            // to upload, so do not block the outbox on it.
            Err(_) => return Ok(true),
        };
        Ok(crate::sync::push_blob(relay_url, secret, dek, &content_hash, &bytes).is_ok())
    }

    fn queue_mutation_push(conn: &Connection, artifact_id: &str, kind: &str) -> Result<(), String> {
        let now = now_iso();
        conn.execute(
            "UPDATE artifacts SET updated_at = ?1 WHERE id = ?2",
            rusqlite::params![now, artifact_id],
        )
        .map_err(|e| e.to_string())?;
        conn.execute(
            "INSERT INTO mutation_outbox (id, artifact_id, mutation_type, created_at, synced)\
             VALUES (?1, ?2, ?3, ?4, 0)",
            rusqlite::params![uuid::Uuid::new_v4().to_string(), artifact_id, kind, now],
        )
        .map_err(|e| e.to_string())?;
        Ok(())
    }

    /// Update a note's body (MOB2.4).
    #[tauri::command]
    fn mobile_update_note(app: AppHandle, id: String, body: String, title: Option<String>) -> Result<String, String> {
        let conn = open_lib(&app)?;
        let art = crate::sync::update_note_body(&conn, &id, &body, title.as_deref()).map_err(|e| e.to_string())?;
        queue_mutation_push(&conn, &id, "update")?;
        Ok(art.to_string())
    }

    /// Add an annotation to an artifact (MOB2.4).
    #[tauri::command]
    fn mobile_add_annotation(app: AppHandle, id: String, text: String) -> Result<String, String> {
        let conn = open_lib(&app)?;
        let art = crate::sync::add_annotation(&conn, &id, &text).map_err(|e| e.to_string())?;
        queue_mutation_push(&conn, &id, "annotate")?;
        Ok(art.to_string())
    }

    /// Remove an annotation (MOB2.4).
    #[tauri::command]
    fn mobile_remove_annotation(app: AppHandle, id: String, annotation_id: String) -> Result<String, String> {
        let conn = open_lib(&app)?;
        let art = crate::sync::remove_annotation(&conn, &id, &annotation_id).map_err(|e| e.to_string())?;
        queue_mutation_push(&conn, &id, "annotate")?;
        Ok(art.to_string())
    }

    /// The artifact's tags, from its tags_json column (mobile has no tags table).
    fn read_tags_json(conn: &Connection, id: &str) -> Result<Vec<String>, String> {
        let raw: Option<String> = conn
            .query_row("SELECT tags_json FROM artifacts WHERE id = ?1", [id], |r| r.get(0))
            .optional()
            .map_err(|e| e.to_string())?
            .flatten();
        Ok(raw
            .and_then(|s| serde_json::from_str::<Vec<String>>(&s).ok())
            .unwrap_or_default())
    }

    fn write_tags_json(conn: &Connection, id: &str, tags: &[String]) -> Result<(), String> {
        let json = serde_json::to_string(tags).map_err(|e| e.to_string())?;
        conn.execute(
            "UPDATE artifacts SET tags_json = ?1 WHERE id = ?2",
            rusqlite::params![json, id],
        )
        .map_err(|e| e.to_string())?;
        Ok(())
    }

    /// Add a tag on the phone (TAGSYNC). Tags live in tags_json here, NOT a tags table -
    /// the old `crate::sync::add_tag` targeted that missing table and always threw. On a
    /// real change we bump updated_at + queue the push, and build_snapshot now carries
    /// tags, so the new tag reaches the desktop.
    #[tauri::command]
    fn mobile_add_tag(app: AppHandle, id: String, tag: String) -> Result<String, String> {
        let conn = open_lib(&app)?;
        let tag = tag.trim().to_string();
        if tag.is_empty() {
            return Err("a tag cannot be empty".into());
        }
        let mut tags = read_tags_json(&conn, &id)?;
        if !tags.iter().any(|t| t.eq_ignore_ascii_case(&tag)) {
            tags.push(tag);
            write_tags_json(&conn, &id, &tags)?;
            queue_mutation_push(&conn, &id, "tag")?;
        }
        Ok(serde_json::to_string(&tags).map_err(|e| e.to_string())?)
    }

    /// Remove a tag on the phone (TAGSYNC). Mirrors mobile_add_tag over tags_json.
    #[tauri::command]
    fn mobile_remove_tag(app: AppHandle, id: String, tag: String) -> Result<String, String> {
        let conn = open_lib(&app)?;
        let mut tags = read_tags_json(&conn, &id)?;
        let before = tags.len();
        tags.retain(|t| !t.eq_ignore_ascii_case(&tag));
        if tags.len() != before {
            write_tags_json(&conn, &id, &tags)?;
            queue_mutation_push(&conn, &id, "tag")?;
        }
        Ok(serde_json::to_string(&tags).map_err(|e| e.to_string())?)
    }

    /// Toggle pin status (MOB2.4).
    #[tauri::command]
    fn mobile_toggle_pin(app: AppHandle, id: String) -> Result<String, String> {
        let conn = open_lib(&app)?;
        let art = crate::sync::toggle_pin(&conn, &id).map_err(|e| e.to_string())?;
        queue_mutation_push(&conn, &id, "pin")?;
        Ok(art.to_string())
    }

    /// Get tags for an artifact, from tags_json (TAGSYNC - the old `get_tags` queried a
    /// tags table the mobile DB does not have and threw "no such table: tags").
    #[tauri::command]
    fn mobile_get_tags(app: AppHandle, id: String) -> Result<String, String> {
        let conn = open_lib(&app)?;
        let tags = read_tags_json(&conn, &id)?;
        Ok(serde_json::to_string(&tags).map_err(|e| e.to_string())?)
    }

    /// List trashed artifacts (MOB2.4).
    #[tauri::command]
    fn mobile_list_trashed(app: AppHandle) -> Result<String, String> {
        let conn = open_lib(&app)?;
        let arts = crate::sync::list_trashed(&conn).map_err(|e| e.to_string())?;
        Ok(serde_json::json!(arts).to_string())
    }

    /// Restore a trashed artifact (MOB2.4).
    #[tauri::command]
    fn mobile_restore_trashed(app: AppHandle, id: String) -> Result<String, String> {
        // Reuse toggle_trash - if it's trashed, this restores it (clears deleted_at).
        let conn = open_lib(&app)?;
        let art = crate::sync::toggle_trash(&conn, &id).map_err(|e| e.to_string())?;
        // Push the restore so the desktop un-trashes it too - build_snapshot carries
        // deleted_at, and queue_mutation_push bumps updated_at so LWW accepts it.
        queue_mutation_push(&conn, &id, "restore")?;
        Ok(art.to_string())
    }

    /// Empty the trash: permanently remove every trashed artifact from the LOCAL library
    /// (the phone's copy) plus its child rows. This is a local purge - the items stay
    /// trashed on the desktop until its own retention window purges them; a normal
    /// cursor-based pull will not resurrect them (their relay object is already past the
    /// pull cursor). Returns how many were purged.
    #[tauri::command]
    fn mobile_empty_trash(app: AppHandle) -> Result<String, String> {
        let conn = open_lib(&app)?;
        // Only items still in trash and not already a tombstone.
        let mut stmt = conn
            .prepare("SELECT id FROM artifacts WHERE deleted_at IS NOT NULL AND purged_at IS NULL")
            .map_err(|e| e.to_string())?;
        let ids: Vec<String> = stmt
            .query_map([], |r| r.get(0))
            .map_err(|e| e.to_string())?
            .filter_map(Result::ok)
            .collect();
        drop(stmt);
        let now = now_iso();
        for id in &ids {
            // Drop the child rows locally.
            for table in ["annotations", "page_text", "artifact_versions"] {
                let _ = conn
                    .execute(&format!("DELETE FROM {table} WHERE artifact_id = ?1"), [id]);
            }
            // Tombstone the artifact instead of hard-deleting it: keep the row with
            // purged_at set and its body stripped, so build_snapshot carries the purge to
            // the desktop (which strips its own copy). queue_mutation_push bumps
            // updated_at so LWW accepts it. content_hash is left intact - it is NOT NULL
            // on the desktop schema, so a snapshot that nulled it would crash the
            // desktop's apply on that constraint; the row is hidden everywhere anyway.
            conn.execute(
                "UPDATE artifacts SET purged_at = ?1, updated_at = ?1, body = NULL,\
                 tags_json = NULL WHERE id = ?2",
                rusqlite::params![now, id],
            )
            .map_err(|e| e.to_string())?;
            queue_mutation_push(&conn, id, "purge")?;
        }
        Ok(serde_json::json!({ "purged": ids.len() }).to_string())
    }

    /// The mobile shell: it builds and launches on the device (MOB.2). The synced
    /// library (MOB.3), setup surface (MOB.3b), and read surfaces (MOB.4-MOB.7) are what
    /// make it a real Enqueue.
    pub fn run() {
        tauri::Builder::default()
            .plugin(tauri_plugin_dialog::init())
            .plugin(tauri_plugin_opener::init())
            .plugin(tauri_plugin_clipboard_manager::init())
            .plugin(tauri_plugin_barcode_scanner::init())
            .invoke_handler(tauri::generate_handler![
                mobile_sync,
                mobile_link_qr,
                mobile_status,
                mobile_list,
                mobile_pivots,
                mobile_get,
                mobile_search,
                mobile_capture,
                mobile_blob,
                mobile_capture_image,
                mobile_outbox_push,
                mobile_outbox_list,
                mobile_pick_image,
                mobile_save_cropped_image,
                mobile_capture_camera,
                mobile_chat,
                mobile_settings_get,
                mobile_settings_set,
                mobile_clear_blob_cache,
                mobile_update_note,
                mobile_add_annotation,
                mobile_remove_annotation,
                mobile_add_tag,
                mobile_remove_tag,
                mobile_toggle_pin,
                mobile_get_tags,
                mobile_list_trashed,
                mobile_restore_trashed,
                mobile_empty_trash,
                mobile_delete,
                start_sync_foreground_service,
                stop_sync_foreground_service,
            ])
            .setup(|app| {
                tauri::WebviewWindowBuilder::new(
                    app,
                    "main",
                    tauri::WebviewUrl::App("mobile.html".into()),
                )
                .title("Enqueue")
                // QR.4a: the barcode-scanner plugin renders the camera BEHIND the
                // WebView; the WebView surface must be transparent for it to show. The
                // page stays opaque normally (body background: var(--bg)) and goes
                // transparent only under the `.scanning` class, so this is invisible
                // except during a scan.
                .transparent(true)
                .build()?;
                // Initialize outbox schema
                let conn = open_lib(app.handle())?;
                init_outbox_schema(&conn).map_err(|e| e.to_string())?;
                // MOBLIVE: start the live SSE sync listener so the library stays
                // current while the app is open, not only on launch/resume.
                spawn_sse_listener(app.handle().clone());
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

    use base64::Engine as Base64Engine;
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

    /// Generate a linking QR code for mobile setup (QR.3).
    /// Returns ONLY the rendered SVG - the payload is encoded in the QR, never as text.
    /// The QR encodes the pinned wire format: {"v":1,"relay_url","relay_secret","dek"}
    #[tauri::command]
    fn desktop_link_code() -> Result<String, String> {
        let (relay_url, secret, dek_b64) = load_link_credentials()?;
        build_link_qr(&relay_url, &secret, &dek_b64)
    }

    /// Load relay URL, sync secret, and DEK from their configured sources.
    /// Returns (relay_url, sync_secret, dek_b64).
    fn load_link_credentials() -> Result<(String, String, String), String> {
        let settings = engine_get("/settings")
            .and_then(|body| serde_json::from_str::<serde_json::Value>(&body).ok())
            .ok_or("could not fetch settings")?;
        let relay_url = settings
            .get("sync")
            .and_then(|s| s.get("relay_url"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        let secret = if cfg!(target_os = "macos") {
            std::process::Command::new("/usr/bin/security")
                .args(["find-generic-password", "-a", "enqueue", "-s", "enqueue-sync-secret", "-w"])
                .output()
                .ok()
                .and_then(|out| String::from_utf8(out.stdout).ok())
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .unwrap_or_default()
        } else {
            String::new()
        };

        let dek_b64 = if cfg!(target_os = "macos") {
            std::process::Command::new("/usr/bin/security")
                .args(["find-generic-password", "-a", "enqueue", "-s", "enqueue-sync-dek", "-w"])
                .output()
                .ok()
                .and_then(|out| String::from_utf8(out.stdout).ok())
                // The keychain already stores the DEK base64-encoded (44 chars = 32 raw
                // bytes). Pass it through verbatim; re-encoding would double-encode and the
                // phone would decode to 44 bytes, not 32, silently zeroing the DEK.
                .map(|s| s.trim().to_string())
                .unwrap_or_default()
        } else {
            let dek_path = std::path::Path::new(".enqueue-poc/sync-dek.bin");
            if dek_path.exists() {
                let dek = std::fs::read(dek_path).unwrap_or_default();
                base64::engine::general_purpose::STANDARD.encode(&dek)
            } else {
                String::new()
            }
        };

        if relay_url.is_empty() {
            return Err("sync not configured".into());
        }

        // LINKSTAY.1: refuse to bake an unreachable relay URL into the link QR.
        if is_loopback_or_private_url(&relay_url) {
            return Err(
                "This relay URL is only reachable from this Mac. Set a hosted relay URL first                  (Settings > Sync, see docs/sync-relay.md), then show the QR again.".into()
            );
        }

        Ok((relay_url, secret, dek_b64))
    }

    /// Build the linking QR SVG from relay URL + secret + DEK base64 string.
    /// This is extracted from desktop_link_code so it can be unit-tested (QR.3).
    fn build_link_qr(relay_url: &str, secret: &str, dek_b64: &str) -> Result<String, String> {
        // Build the pinned wire format JSON: {"v":1,"relay_url":"...","relay_secret":"...","dek":"<base64>"}
        let payload = serde_json::json!({
            "v": 1,
            "relay_url": relay_url,
            "relay_secret": secret,
            "dek": dek_b64,
        });
        let payload_str = payload.to_string();

        // Generate QR code SVG locally (no external network calls)
        let qr_code = qrcode::QrCode::new(payload_str.as_bytes()).map_err(|e| e.to_string())?;
        let qr_svg = qr_code.render()
            .min_dimensions(200, 200)
            .dark_color(qrcode::render::svg::Color("#000000"))
            .light_color(qrcode::render::svg::Color("#ffffff"))
            .build();

        Ok(qr_svg)
    }

    /// Build the pinned wire format payload string (testable without QR rendering).
    #[cfg(test)]
    fn build_link_payload(relay_url: &str, secret: &str, dek_b64: &str) -> String {
        let payload = serde_json::json!({
            "v": 1,
            "relay_url": relay_url,
            "relay_secret": secret,
            "dek": dek_b64,
        });
        payload.to_string()
    }

    /// Check if a URL is loopback or LAN-private (LINKSTAY.1).
    /// Such URLs are not reachable from a phone on a different network.
    fn is_loopback_or_private_url(url: &str) -> bool {
        let lowered = url.to_lowercase();
        let stripped = if lowered.starts_with("https://") {
            &lowered[8..]
        } else if lowered.starts_with("http://") {
            &lowered[7..]
        } else {
            return false;
        };
        // Extract host (before first '/', '?', '#', or ':')
        let host_end = stripped.find(['/', '?', '#', ':'])
            .unwrap_or(stripped.len());
        let host = stripped[..host_end].to_lowercase();

        // Loopback
        if host == "localhost" || host == "127.0.0.1" || host == "::1" {
            return true;
        }
        // LAN private ranges: 10.x, 192.168.x, 172.16-31.x, 169.254.x (link-local)
        if host.starts_with("10.") || host.starts_with("192.168.") {
            return true;
        }
        if let Some(rest) = host.strip_prefix("172.") {
            if let Some(octet_str) = rest.split('.').next() {
                if let Ok(octet) = octet_str.parse::<u8>() {
                    if (16..=31).contains(&octet) {
                        return true;
                    }
                }
            }
        }
        if host.starts_with("169.254.") {
            return true;
        }
        false
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
                capture_drag,
                hotkey_changed,
                open_external,
                window_drag,
                desktop_link_code
            ])
            .setup(move |app| {
                // The webview loads the engine's URL, so it cannot be built until the
                // engine answers. By now Tauri has initialised concurrently with the
                // boot, so this waits only for whatever time the engine still needs.
                // 60s (was 30) covers a cold start where the embedding load and index
                // bootstrap run long; a tight window meant the webview was built against
                // an engine that had not bound yet, loaded an error page, and never
                // retried - the "cannot load artifacts" blank the reload-watcher below
                // now recovers from.
                let engine_ready = !spawned_here || wait_for_engine(Duration::from_secs(60));
                if !engine_ready {
                    eprintln!("[shell] engine did not come up within 60s; will reload the window when it does");
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

                // If the engine had not bound by the time the windows were built, they
                // are showing an error page pinned to a URL that now works. Nothing in a
                // webview retries a failed top-level load on its own, so poll for the
                // engine on a background thread and reload both windows once it answers.
                // This is the recovery path for a slow cold start (and for an engine that
                // died and was restarted): the window heals instead of staying blank.
                if !engine_ready {
                    let main_win = window.clone();
                    let capture_win = capture.clone();
                    thread::spawn(move || {
                        // Keep waiting well past the initial 60s - a truly stuck engine is
                        // rare, and a long poll costs nothing but a refused connection.
                        if wait_for_engine(Duration::from_secs(120)) {
                            let _ = main_win.eval("window.location.reload()");
                            let _ = capture_win.eval("window.location.reload()");
                        }
                    });
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

    #[cfg(test)]
    mod tests {
        use super::*;

        /// QR.3: headless test asserting the QR encodes the pinned wire format.
        #[test]
        fn link_qr_payload_is_pinned_wire_format() {
            let payload_str = build_link_payload(
                "https://relay.example.com",
                "test-secret-123",
                "AAECAwQFBgk=",
            );
            let parsed: serde_json::Value = serde_json::from_str(&payload_str).unwrap();
            // Exactly 4 keys, no extras
            let keys: std::collections::HashSet<&str> = parsed
                .as_object()
                .unwrap()
                .keys()
                .map(|k| k.as_str())
                .collect();
            assert_eq!(keys.len(), 4);
            assert_eq!(parsed["v"], 1);
            assert_eq!(parsed["relay_url"], "https://relay.example.com");
            assert_eq!(parsed["relay_secret"], "test-secret-123");
            assert_eq!(parsed["dek"], "AAECAwQFBgk=");
        }

        /// QR.3: verify the QR SVG renders without error.
        #[test]
        fn link_qr_renders_svg() {
            let svg = build_link_qr("https://relay.example.com", "secret", "dek123==").unwrap();
            assert!(svg.contains("<svg"), "SVG should contain <svg tag: {}", &svg.chars().take(60).collect::<String>());
            assert!(svg.contains("</svg>"), "SVG should contain closing </svg> tag");
        }

        /// QR.3: round-trip - generate QR, encode to grayscale image, decode with rqrr.
        #[test]
        fn link_qr_decodes_to_same_payload() {
            let payload_str = build_link_payload("https://relay.example.com", "test-secret", "AAECAwQFBgk=");
            let qr_code = qrcode::QrCode::new(payload_str.as_bytes()).unwrap();
            // Render to grayscale image
            let img: image::GrayImage = qr_code.render::<image::Luma<u8>>()
                .min_dimensions(200, 200)
                .build();
            // Decode with rqrr
            let mut prepared = rqrr::PreparedImage::prepare(img);
            let grids = prepared.detect_grids();
            assert!(!grids.is_empty(), "QR code was not detected");
            let (_meta, decoded) = grids[0].decode().unwrap();
            let parsed: serde_json::Value = serde_json::from_str(&decoded).unwrap();
            let expected: serde_json::Value = serde_json::from_str(&payload_str).unwrap();
            assert_eq!(parsed, expected);
        }

        /// LINKSTAY.1: verify loopback/private detection.
        #[test]
        fn loopback_url_detection() {
            assert!(is_loopback_or_private_url("http://localhost:8788"));
            assert!(is_loopback_or_private_url("https://127.0.0.1:8788"));
            assert!(is_loopback_or_private_url("http://10.0.0.1:8788"));
            assert!(is_loopback_or_private_url("http://192.168.1.1:8788"));
            assert!(is_loopback_or_private_url("http://172.16.0.1:8788"));
            assert!(is_loopback_or_private_url("http://169.254.1.1:8788"));
            assert!(!is_loopback_or_private_url("https://relay.example.com"));
            assert!(!is_loopback_or_private_url("https://relay.up.railway.app"));
        }
    }
}