//! The app lock and the vault's Face ID on iPhone (ios/Sources), answering in the
//! shapes of Android's bridge (MainActivity.kt, Biometrics.kt). Android registers nothing.

use tauri::{
    plugin::{Builder, TauriPlugin},
    Runtime,
};

#[cfg(target_os = "ios")]
tauri::ios_plugin_binding!(init_plugin_native);

pub fn init<R: Runtime>() -> TauriPlugin<R> {
    Builder::new("native")
        .setup(|_app, _api| {
            #[cfg(target_os = "ios")]
            _api.register_ios_plugin(init_plugin_native)?;
            Ok(())
        })
        .build()
}
