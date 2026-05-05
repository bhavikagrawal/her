// HER's Rust entrypoint: boots the Tauri runtime and opens the single main window.
// Think of this file as the usher: it does not know Python, only how to display the UI shell.
// Python starts separately via `beforeDevCommand`, then the WebView connects over localhost.
// Later phases still keep heavy AI work out of Rust — this file should stay thin on purpose.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::Manager;

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![open_settings_window])
        .run(tauri::generate_context!())
        .expect("error while running HER (Tauri application)");
}

#[tauri::command]
fn open_settings_window(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(w) = app.get_webview_window("settings") {
        w.show().map_err(|e| e.to_string())?;
        w.set_focus().map_err(|e| e.to_string())?;
        return Ok(());
    }

    tauri::WebviewWindowBuilder::new(
        &app,
        "settings",
        tauri::WebviewUrl::App("settings.html".into()),
    )
    .title("HER — Settings")
    .inner_size(520.0, 720.0)
    .resizable(true)
    .build()
    .map_err(|e| e.to_string())?;

    Ok(())
}
