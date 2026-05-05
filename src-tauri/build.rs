// Runs before `rustc` compiles HER: hooks Tauri's codegen and embeds web assets metadata.
// You rarely edit this file; it wires `tauri.conf.json` into Rust's build graph.
// Phase 0 relies on it so the dev server knows where `frontend/` lives on disk.
// Keeping it tiny reduces surprises when you later add icons or permission manifest files.

fn main() {
    tauri_build::build()
}
