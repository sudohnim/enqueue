// The desktop binary. All the shell logic lives in the library (src/lib.rs) so the
// same code builds as a mobile library too; this just calls into it.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    enqueue_lib::run();
}
