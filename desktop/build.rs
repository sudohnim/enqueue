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
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(
            tauri_build::AppManifest::new().commands(&[
                "capture_dismiss",
                "capture_done",
                "capture_drag",
                "hotkey_changed",
                "mobile_blob",
                "mobile_capture",
                "mobile_get",
                "mobile_list",
                "mobile_search",
                "mobile_status",
                "mobile_sync",
                "open_external",
                "window_drag",
            ]),
        ),
    )
    .expect("failed to prepare the Enqueue shell build")
}
