#!/usr/bin/env bash
set -eu

SOURCE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
DATA_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$DATA_ROOT/multilut-controller"
DESKTOP_DIR="$DATA_ROOT/applications"
ICON_DIR="$DATA_ROOT/icons/hicolor/scalable/apps"
DESKTOP_FILE="$DESKTOP_DIR/com.felipesantiago.MultiLUTController.desktop"

if command -v xdg-user-dir >/dev/null 2>&1; then
  USER_DESKTOP="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
else
  USER_DESKTOP=""
fi
if [ -z "$USER_DESKTOP" ] || [ "$USER_DESKTOP" = "$HOME" ]; then
  if [ -d "$HOME/Área de Trabalho" ]; then
    USER_DESKTOP="$HOME/Área de Trabalho"
  else
    USER_DESKTOP="$HOME/Desktop"
  fi
fi
USER_DESKTOP_FILE="$USER_DESKTOP/MultiLUT_Controller.desktop"

mkdir -p "$APP_DIR" "$DESKTOP_DIR" "$ICON_DIR"
cp -a "$SOURCE_DIR/." "$APP_DIR/"
chmod 755 "$APP_DIR/run.sh" "$APP_DIR/install.sh" "$APP_DIR/uninstall.sh"
chmod 644 "$APP_DIR/multilut_controller.py" "$APP_DIR/multilut_core.py" "$APP_DIR/multilut_extra.py" "$APP_DIR/multilut_ctl.py" "$APP_DIR/multilut_preview.py"

BIN_DIR="$DATA_ROOT/bin"
mkdir -p "$BIN_DIR"
cp "$SOURCE_DIR/multilut_ctl.py" "$BIN_DIR/multilut-ctl"
chmod 755 "$BIN_DIR/multilut-ctl"

sed "s|@APP_DIR@|$APP_DIR|g" \
  "$SOURCE_DIR/com.felipesantiago.MultiLUTController.desktop.in" \
  > "$DESKTOP_FILE"
chmod 644 "$DESKTOP_FILE"
cp "$SOURCE_DIR/assets/com.felipesantiago.MultiLUTController.svg" \
  "$ICON_DIR/com.felipesantiago.MultiLUTController.svg"

mkdir -p "$USER_DESKTOP"
cp "$DESKTOP_FILE" "$USER_DESKTOP_FILE"
chmod 755 "$USER_DESKTOP_FILE"
if command -v gio >/dev/null 2>&1; then
  gio set "$USER_DESKTOP_FILE" metadata::trusted true >/dev/null 2>&1 || true
fi

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "$DATA_ROOT/icons/hicolor" >/dev/null 2>&1 || true
fi

if python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")' >/dev/null 2>&1; then
  printf '%s\n' "MultiLUT Controller instalado com sucesso."
  printf '%s\n' "Abra-o pelo ícone da área de trabalho ou pelo menu de aplicativos."
  printf '%s\n' "CLI instalada em $BIN_DIR/multilut-ctl (use: multilut-ctl --help)."
  if python3 -c 'import numpy, PIL' >/dev/null 2>&1; then
    printf '%s\n' "Simulação de LUT pronta (numpy + Pillow encontrados)."
  else
    printf '%s\n' "Dica: para a pré-visualização de LUT, instale numpy e Pillow:"
    printf '%s\n' "  sudo eopkg it python3-numpy python3-pillow"
  fi
else
  printf '%s\n' "O aplicativo foi instalado, mas faltam dependências gráficas."
  printf '%s\n' "No Centro de Programas do Solus, instale: PyGObject para Python 3, GTK 4 e libadwaita."
  printf '%s\n' "Depois, abra MultiLUT Controller pelo menu de aplicativos."
fi
