// The commands the page calls (`plugin:billing|<command>`); each becomes an `allow-*`
// permission the mobile capability lists (tauri.conf.json).
const COMMANDS: &[&str] = &["start", "status", "offerings", "purchase", "restore"];

fn main() {
    tauri_plugin::Builder::new(COMMANDS).ios_path("ios").build();
}
