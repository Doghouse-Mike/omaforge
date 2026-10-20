#!/bin/bash
# Install OmaForge for this user: launcher symlink, app-menu entry, icon.
# Re-run after moving the checkout. ./install.sh --uninstall to remove.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/.local/bin/omaforge"
DESKTOP="$HOME/.local/share/applications/omaforge.desktop"
ICON="$HOME/.local/share/icons/hicolor/scalable/apps/omaforge.svg"

UNIT="$HOME/.config/systemd/user/omaforge-notify.service"

if [ "${1:-}" = "--uninstall" ]; then
  systemctl --user disable --now omaforge-notify.service 2>/dev/null || true
  rm -f "$BIN" "$DESKTOP" "$ICON" "$UNIT"
  systemctl --user daemon-reload 2>/dev/null || true
  update-desktop-database -q "$HOME/.local/share/applications" 2>/dev/null || true
  echo "Removed (config in ~/.config/omaforge left alone)."
  exit 0
fi

for dep in qs python3; do command -v "$dep" >/dev/null || { echo "missing: $dep" >&2; exit 1; }; done
python3 -c 'import yaml' 2>/dev/null || { echo "needs python-yaml (pacman -S python-yaml)" >&2; exit 1; }

mkdir -p "$(dirname "$BIN")" "$(dirname "$DESKTOP")" "$(dirname "$ICON")"
ln -sf "$HERE/bin/omaforge" "$BIN"
cp "$HERE/share/omaforge.svg" "$ICON"
cat > "$DESKTOP" <<DESK
[Desktop Entry]
Type=Application
Name=OmaForge
GenericName=Tasks
Comment=TaskNotes tasks from your Obsidian vault
Exec=$BIN
Icon=omaforge
Terminal=false
Categories=Office;ProjectManagement;
Keywords=tasks;todo;tasknotes;obsidian;
StartupWMClass=omaforge
DESK
update-desktop-database -q "$HOME/.local/share/applications" 2>/dev/null || true

# Notifications: a user service that runs while you're logged in.
mkdir -p "$(dirname "$UNIT")"
sed "s|@CORE@|$HERE/core|" "$HERE/share/omaforge-notify.service" > "$UNIT"
systemctl --user daemon-reload
systemctl --user enable --now omaforge-notify.service
systemctl --user restart omaforge-notify.service

CONFIG="$HOME/.config/omaforge/config.json"
if [ ! -f "$CONFIG" ]; then
  mkdir -p "$(dirname "$CONFIG")"
  printf '{\n  "vault": "",\n  "writableVaults": []\n}\n' > "$CONFIG"
  echo "Created $CONFIG: set \"vault\", and list it in \"writableVaults\" to allow edits."
fi
echo "Installed. Launch from the app menu or run: omaforge"
