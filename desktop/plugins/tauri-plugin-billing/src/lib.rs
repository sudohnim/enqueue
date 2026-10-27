//! Enqueue Pro bought on iPhone, through RevenueCat over StoreKit (ios/Sources). The page
//! calls `plugin:billing|start|status|offerings|purchase|restore`, and the Swift side
//! answers in the same shapes as Android's Billing.kt, so one paywall serves both.
//! Android has its own bridge (Billing.kt); there this plugin registers nothing.

use tauri::{
    plugin::{Builder, TauriPlugin},
    Runtime,
};

#[cfg(target_os = "ios")]
tauri::ios_plugin_binding!(init_plugin_billing);

pub fn init<R: Runtime>() -> TauriPlugin<R> {
    Builder::new("billing")
        .setup(|_app, _api| {
            #[cfg(target_os = "ios")]
            _api.register_ios_plugin(init_plugin_billing)?;
            Ok(())
        })
        .build()
}
