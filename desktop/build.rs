fn main() {
    // Both pages are served by the engine, so Tauri sees their webviews as a remote
    // origin, and remote origins are refused every command unless a capability names
    // them. Declaring the commands here is what generates the `allow-*` permissions
    // those capabilities reference (see app.security.capabilities in tauri.conf.json).
    //
    // Registering a command in `generate_handler!` is only half of it: without the
    // matching permission the call is refused at runtime with "not allowed. Command
    // not found", which reads like the handler is missing when in fact it is present
    // and the ACL is doing its job.
    
    // For desktop builds, override capabilities via TAURI_CONFIG env var to exclude
    // mobile-only capabilities that reference plugins not available on desktop
    // (e.g., barcode-scanner). This env var is merged into the config at compile time
    // by tauri-codegen's get_config function.
    let target_os = std::env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    let is_mobile = target_os == "ios" || target_os == "android";
    
    if !is_mobile {
        let desktop_capabilities = serde_json::json!({
            "app": {
                "security": {
                    "capabilities": [
                        {
                            "identifier": "capture-overlay",
                            "description": "Lets the quick-capture overlay put itself away and be dragged by its title bar.",
                            "windows": ["capture"],
                            "remote": {
                                "urls": [
                                    "http://127.0.0.1:8787/*",
                                    "http://localhost:8787/*"
                                ]
                            },
                            "permissions": [
                                "allow-capture-dismiss",
                                "allow-capture-drag",
                                "core:event:allow-listen",
                                "core:event:allow-unlisten"
                            ]
                        },
                        {
                            "identifier": "home-links",
                            "description": "Lets the home window hand a saved http(s) address to the system browser, drag its own window by the top strip, and show the Signal-style linking QR for mobile setup (QR.3). All are refused by default because the page is served from a remote origin.",
                            "windows": ["main"],
                            "remote": {
                                "urls": [
                                    "http://127.0.0.1:8787/*",
                                    "http://localhost:8787/*"
                                ]
                            },
                            "permissions": [
                                "allow-hotkey-changed",
                                "allow-open-external",
                                "allow-window-drag",
                                "allow-desktop-link-code",
                                "core:event:allow-listen",
                                "core:event:allow-unlisten"
                            ]
                        }
                    ]
                }
            }
        });
        // Use cargo:rustc-env to pass TAURI_CONFIG to the compiler for macro expansion
        println!("cargo:rustc-env=TAURI_CONFIG={}", desktop_capabilities);
        println!("cargo:rerun-if-changed=tauri.conf.json");
    }
    
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(
            tauri_build::AppManifest::new().commands(&[
                "capture_dismiss",
                "capture_drag",
                "hotkey_changed",
                "mobile_blob",
                "mobile_capture",
                "mobile_get",
                "mobile_link_qr",
                "mobile_list",
                "mobile_search",
                "mobile_status",
                "mobile_sync",
                "open_external",
                "window_drag",
                "mobile_vault_status",
                "mobile_vault_setup",
                "mobile_vault_unlock",
                "mobile_vault_lock",
                "mobile_vault_change_pin",
                "mobile_set_vault",
                "mobile_vault_list",
                "mobile_vault_get",
                "mobile_vault_blob",
                "mobile_events",
                "start_sync_foreground_service",
                "stop_sync_foreground_service",
            ]),
        ),
    )
    .expect("failed to prepare the Enqueue shell build")
}
