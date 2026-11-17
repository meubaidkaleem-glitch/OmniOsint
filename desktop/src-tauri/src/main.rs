// No console window behind the application in release builds on Windows.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    omniosint_desktop_lib::run();
}
