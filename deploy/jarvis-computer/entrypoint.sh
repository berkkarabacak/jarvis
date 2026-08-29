#!/bin/sh
# Start Jarvis's one Linux desktop. Home is a named volume; keep it writable.
# ORCH-402: apply the Windows-like XFCE theme on first start of this image.
# ORCH-403: seed desktop shortcuts. Do not launch the apps here.
# ORCH-404: live noVNC of THIS display (Xvfb :1). Not a second machine.
# ORCH-405: tools docker-exec into this display; do not launch apps here.
set -eu

HOME_DIR="/home/jarvis"
MARKER="$HOME_DIR/.jarvis-computer-ready"
THEME_MARKER="$HOME_DIR/.jarvis-windows-theme-ready"
APPS_MARKER="$HOME_DIR/.jarvis-apps-ready"
UBLOCK_MARKER="$HOME_DIR/.jarvis-ublock-unpacked-ready"
THEME_SRC="/usr/src/jarvis-windows-theme/xfce-config"
APPS_SRC="/usr/share/jarvis-computer/apps"
XFCONF_DST="$HOME_DIR/.config/xfce4/xfconf/xfce-perchannel-xml"
DISPLAY_NUM="${DISPLAY:-:1}"
SCREEN="${JARVIS_SCREEN:-1280x720x24}"

apply_windows_theme() {
  mkdir -p "$XFCONF_DST"
  if [ -d "$THEME_SRC" ]; then
    cp "$THEME_SRC/xfce4-panel.xml" "$XFCONF_DST/xfce4-panel.xml"
    cp "$THEME_SRC/xfwm4.xml" "$XFCONF_DST/xfwm4.xml"
    cp "$THEME_SRC/xsettings.xml" "$XFCONF_DST/xsettings.xml"
    cp "$THEME_SRC/xfce4-desktop.xml" "$XFCONF_DST/xfce4-desktop.xml"
  fi
  touch "$THEME_MARKER"
}

seed_desktop_shortcuts() {
  mkdir -p "$HOME_DIR/Desktop"
  if [ -d "$APPS_SRC" ]; then
    cp "$APPS_SRC"/*.desktop "$HOME_DIR/Desktop/"
    chmod 0755 "$HOME_DIR/Desktop"/*.desktop
  fi
  touch "$APPS_MARKER"
}

# Persisted homes keep Desktop/chrome.desktop from the first seed. Always
# rewrite Chrome so Exec stays /usr/local/bin/chrome after image updates.
refresh_chrome_desktop() {
  mkdir -p "$HOME_DIR/Desktop"
  if [ -f "$APPS_SRC/chrome.desktop" ]; then
    cp "$APPS_SRC/chrome.desktop" "$HOME_DIR/Desktop/chrome.desktop"
    chmod 0755 "$HOME_DIR/Desktop/chrome.desktop"
  fi
}

# A profile that tried to force-install from clients2.google.com can ignore
# --load-extension. Seed developer mode and drop that stale store state once.
seed_chromium_ublock_profile() {
  conf="$HOME_DIR/.config/chromium/Default"
  mkdir -p "$conf"
  prefs="$conf/Preferences"
  secure="$conf/Secure Preferences"
  stale=""
  for candidate in "$prefs" "$secure"; do
    if [ -f "$candidate" ] && grep -Eq 'clients2\.google\.com|cjpalhdlnbpafiamejdnhcphjbkeiagm' "$candidate"; then
      stale=1
    fi
  done
  if [ -n "$stale" ]; then
    rm -f "$prefs" "$secure"
  fi
  if [ ! -f "$prefs" ]; then
    cat > "$prefs" <<'EOF'
{
  "extensions": {
    "ui": {
      "developer_mode": true
    }
  }
}
EOF
  fi
  touch "$UBLOCK_MARKER"
}

seed_home() {
  mkdir -p "$HOME_DIR/Desktop" "$HOME_DIR/Documents" "$HOME_DIR/Downloads" "$HOME_DIR/.config"
  if [ ! -f "$MARKER" ]; then
    cat > "$HOME_DIR/README.txt" <<'EOF'
This is Jarvis's one Linux computer (ORCH-401 / ORCH-402 / ORCH-403 / ORCH-404).
The desktop is themed to look like Windows (taskbar, Start, title bars).
Chrome, Notepad, Files, Terminal, Calculator, and Image Viewer are on the desktop
and in the Start menu. Files, app settings, and logins in this home survive restarts.
Open the same desktop in a browser: http://127.0.0.1:6080
EOF
    touch "$MARKER"
  fi
  if [ ! -f "$THEME_MARKER" ]; then
    apply_windows_theme
  fi
  if [ ! -f "$APPS_MARKER" ]; then
    seed_desktop_shortcuts
  fi
  refresh_chrome_desktop
  if [ ! -f "$UBLOCK_MARKER" ]; then
    seed_chromium_ublock_profile
  fi
  chown -R jarvis:jarvis "$HOME_DIR"
}

start_desktop() {
  export DISPLAY="$DISPLAY_NUM"
  export HOME="$HOME_DIR"
  export USER=jarvis
  export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/runtime-jarvis}"
  mkdir -p "$XDG_RUNTIME_DIR"
  chmod 700 "$XDG_RUNTIME_DIR"

  Xvfb "$DISPLAY" -screen 0 "$SCREEN" -ac +extension RANDR +render -noreset &
  XVFB_PID=$!

  i=0
  sock="/tmp/.X11-unix/X${DISPLAY_NUM#:}"
  while [ "$i" -lt 50 ]; do
    if [ -e "$sock" ]; then
      break
    fi
    i=$((i + 1))
    sleep 0.1
  done

  if ! kill -0 "$XVFB_PID" 2>/dev/null; then
    echo "Xvfb failed to start" >&2
    exit 1
  fi

  # Attach to the existing Xvfb display. This is the same desktop, not a recording.
  x11vnc \
    -display "$DISPLAY" \
    -forever \
    -shared \
    -nopw \
    -listen 127.0.0.1 \
    -rfbport 5900 \
    -noxdamage \
    -noshm \
    -xkb \
    -o /tmp/x11vnc.log \
    -bg

  # Browser UI. Compose publishes 127.0.0.1:6080 on the host only.
  websockify --web=/usr/share/novnc 6080 127.0.0.1:5900 &
  echo "Jarvis desktop (live): http://127.0.0.1:6080"

  if command -v dbus-launch >/dev/null 2>&1; then
    eval "$(dbus-launch --sh-syntax)"
  fi

  startxfce4 &

  # The virtual display is the computer. Restart policy brings it back;
  # the named volume keeps /home/jarvis.
  wait "$XVFB_PID"
}

if [ "$(id -u)" = "0" ]; then
  seed_home
  exec runuser -u jarvis -- "$0"
fi

start_desktop
