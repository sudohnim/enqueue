const COMMANDS: &[&str] = &["status", "applock", "create", "read", "clear", "quick", "apple"];

fn main() {
    tauri_plugin::Builder::new(COMMANDS).ios_path("ios").build();
}
