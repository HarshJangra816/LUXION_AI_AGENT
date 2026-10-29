//! Tauri shell — the main window plus the floating orb window (PRD §29) and
//! its system tray (Phase 12b).
//!
//! The orb window is transparent, frameless, always-on-top, draggable and
//! resizable; it persists its position and size across launches and hides (not
//! destroys) on close so it stays genuinely persistent. It loads `orb.html` and
//! *mirrors* the main window's AI state over Tauri events (frontend
//! `orbBridge.ts`); the main window remains the single owner of that state.
//!
//! Nothing here reaches for the network or a device — the orb webview talks to
//! the backend over plain HTTP like the main window does.

use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

/// Label of the floating orb window.
const ORB_LABEL: &str = "orb";
/// Persisted orb geometry, stored under the app config dir.
const ORB_GEOMETRY_FILE: &str = "orb-geometry.json";
/// Default orb size (square) and the smallest it may be resized to.
const ORB_SIZE: u32 = 240;
const ORB_MIN_SIZE: f64 = 160.0;
/// Ignore move/resize bursts closer together than this when saving.
const SAVE_THROTTLE: Duration = Duration::from_millis(400);

/// The orb window's last position and size, in physical pixels.
#[derive(Clone, Copy, serde::Serialize, serde::Deserialize)]
struct OrbGeometry {
  x: i32,
  y: i32,
  width: u32,
  height: u32,
}

fn geometry_path(app: &AppHandle) -> Option<std::path::PathBuf> {
  app
    .path()
    .app_config_dir()
    .ok()
    .map(|dir| dir.join(ORB_GEOMETRY_FILE))
}

fn load_geometry(app: &AppHandle) -> Option<OrbGeometry> {
  let path = geometry_path(app)?;
  let text = std::fs::read_to_string(path).ok()?;
  serde_json::from_str(&text).ok()
}

fn save_geometry(app: &AppHandle, geometry: &OrbGeometry) {
  let Some(path) = geometry_path(app) else { return };
  if let Some(dir) = path.parent() {
    let _ = std::fs::create_dir_all(dir);
  }
  if let Ok(text) = serde_json::to_string(geometry) {
    let _ = std::fs::write(path, text);
  }
}

/// Pull a saved position back onto a connected monitor. A monitor unplugged
/// since the last run must not leave the orb stranded off-screen.
fn clamp_to_visible(app: &AppHandle, geometry: &mut OrbGeometry) {
  let Ok(monitors) = app.available_monitors() else { return };
  let centre_x = geometry.x + (geometry.width as i32 / 2);
  let centre_y = geometry.y + (geometry.height as i32 / 2);
  let on_screen = monitors.iter().any(|monitor| {
    let position = monitor.position();
    let size = monitor.size();
    centre_x >= position.x
      && centre_x < position.x + size.width as i32
      && centre_y >= position.y
      && centre_y < position.y + size.height as i32
  });
  if on_screen {
    return;
  }
  // Re-centre on the primary monitor instead.
  if let Ok(Some(primary)) = app.primary_monitor() {
    let position = primary.position();
    let size = primary.size();
    geometry.x = position.x + (size.width as i32 - geometry.width as i32) / 2;
    geometry.y = position.y + (size.height as i32 - geometry.height as i32) / 2;
  }
}

/// Read the live geometry, refusing a zero/half-hidden snapshot so a window
/// mid-hide is never persisted as an invisible orb.
fn snapshot_geometry(window: &WebviewWindow) -> Option<OrbGeometry> {
  if !window.is_visible().unwrap_or(false) {
    return None;
  }
  let position = window.outer_position().ok()?;
  let size = window.inner_size().ok()?;
  if size.width == 0 || size.height == 0 {
    return None;
  }
  Some(OrbGeometry {
    x: position.x,
    y: position.y,
    width: size.width,
    height: size.height,
  })
}

/// Persist the orb's position/size as it moves and resizes (throttled — a drag
/// emits an event per pixel), and keep the window alive on close by hiding it
/// instead of destroying it.
fn wire_geometry_persistence(app: &AppHandle, window: &WebviewWindow) {
  let app = app.clone();
  let last_saved = Mutex::new(Instant::now() - SAVE_THROTTLE);

  window.on_window_event(move |event| match event {
    tauri::WindowEvent::Moved(..) | tauri::WindowEvent::Resized(..) => {
      let Ok(mut guard) = last_saved.lock() else { return };
      if guard.elapsed() < SAVE_THROTTLE {
        return;
      }
      let Some(window) = app.get_webview_window(ORB_LABEL) else { return };
      let Some(geometry) = snapshot_geometry(&window) else { return };
      *guard = Instant::now();
      save_geometry(&app, &geometry);
    }
    tauri::WindowEvent::CloseRequested { api, .. } => {
      // Persistent by design (PRD §29): the tray brings the orb back.
      api.prevent_close();
      if let Some(window) = app.get_webview_window(ORB_LABEL) {
        let _ = window.hide();
      }
    }
    _ => {}
  });
}

/// Create the floating orb window — transparent, frameless, always-on-top,
/// resizable, off the taskbar — restored to its last position and size.
fn create_orb_window(app: &AppHandle) -> tauri::Result<WebviewWindow> {
  let saved = load_geometry(app);
  let mut geometry = saved.unwrap_or(OrbGeometry {
    x: 0,
    y: 0,
    width: ORB_SIZE,
    height: ORB_SIZE,
  });
  clamp_to_visible(app, &mut geometry);

  let mut builder = WebviewWindowBuilder::new(app, ORB_LABEL, WebviewUrl::App("orb.html".into()))
    .title("Luxion Orb")
    .inner_size(geometry.width as f64, geometry.height as f64)
    .min_inner_size(ORB_MIN_SIZE, ORB_MIN_SIZE)
    .decorations(false)
    .transparent(true)
    .shadow(false)
    .always_on_top(true)
    .skip_taskbar(true)
    .resizable(true)
    .focused(false)
    .visible(false);

  if saved.is_some() {
    builder = builder.position(geometry.x as f64, geometry.y as f64);
  } else if let Ok(Some(primary)) = app.primary_monitor() {
    // First run: park it in the lower-right of the primary monitor.
    let position = primary.position();
    let size = primary.size();
    builder = builder.position(
      (position.x + size.width as i32 - geometry.width as i32 - 24) as f64,
      (position.y + size.height as i32 - geometry.height as i32 - 48) as f64,
    );
  }

  let window = builder.build()?;
  wire_geometry_persistence(app, &window);
  Ok(window)
}

fn show_orb_window(app: &AppHandle) {
  if let Some(window) = app.get_webview_window(ORB_LABEL) {
    let _ = window.show();
    let _ = window.set_focus();
  }
}

fn hide_orb_window(app: &AppHandle) {
  if let Some(window) = app.get_webview_window(ORB_LABEL) {
    let _ = window.hide();
  }
}

fn open_main_window(app: &AppHandle) {
  if let Some(window) = app.get_webview_window("main") {
    let _ = window.show();
    let _ = window.set_focus();
  }
}

/// Tray menu: Show/Hide the orb, reopen the main window, or quit outright.
fn setup_tray(app: &AppHandle) -> tauri::Result<()> {
  let show_orb = MenuItem::with_id(app, "show_orb", "Show Orb", true, None::<&str>)?;
  let hide_orb = MenuItem::with_id(app, "hide_orb", "Hide Orb", true, None::<&str>)?;
  let open_app = MenuItem::with_id(app, "open_app", "Open Luxion", true, None::<&str>)?;
  let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
  let menu = Menu::with_items(app, &[&show_orb, &hide_orb, &open_app, &quit])?;

  let mut builder = TrayIconBuilder::with_id("main")
    .tooltip("Luxion")
    // Left-click opens this menu (the Tauri default), so Quit is always
    // reachable without relying on platform-specific right-click behaviour.
    .menu(&menu)
    .on_menu_event(|app, event| match event.id.as_ref() {
      "show_orb" => show_orb_window(app),
      "hide_orb" => hide_orb_window(app),
      "open_app" => open_main_window(app),
      "quit" => app.exit(0),
      _ => {}
    });

  if let Some(icon) = app.default_window_icon() {
    builder = builder.icon(icon.clone());
  }

  builder.build(app)?;
  Ok(())
}

/// Closing the main window hides it to the tray rather than destroying it, so
/// the tray's "Open Luxion" can always bring it back.
fn wire_main_hide_on_close(app: &AppHandle) {
  let Some(main) = app.get_webview_window("main") else { return };
  let app = app.clone();
  main.on_window_event(move |event| {
    if let tauri::WindowEvent::CloseRequested { api, .. } = event {
      api.prevent_close();
      if let Some(window) = app.get_webview_window("main") {
        let _ = window.hide();
      }
    }
  });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }

      let handle = app.handle().clone();

      // Closing the main window parks it in the tray instead of quitting
      // (PRD §29 — the app is persistent, and only the tray's Quit exits).
      wire_main_hide_on_close(&handle);

      // The orb shows on launch; the tray and the main window can hide/show it.
      let orb = create_orb_window(&handle)?;
      let _ = orb.show();

      setup_tray(&handle)?;

      Ok(())
    })
    .build(tauri::generate_context!())
    .expect("error while building tauri application")
    // A `code: None` exit request means every window is gone — keep the app
    // alive in the tray. `app.exit(code)` (the tray's Quit) still exits.
    .run(|_, event| {
      if let tauri::RunEvent::ExitRequested { code: None, api, .. } = event {
        api.prevent_exit();
      }
    });
}
