#!/usr/bin/env bash
set -eu

DATA_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$DATA_ROOT/multilut-controller"
DESKTOP_FILE="$DATA_ROOT/applications/com.felipesantiago.MultiLUTController.desktop"
ICON_FILE="$DATA_ROOT/icons/hicolor/scalable/apps/com.felipesantiago.MultiLUTController.svg"
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
EXPECTED_DEFAULT="$HOME/.local/share/multilut-controller"
EXPECTED_DATA_ROOT="$DATA_ROOT/multilut-controller"

case "$APP_DIR" in
  "$EXPECTED_DEFAULT"|"$EXPECTED_DATA_ROOT") ;;
  *) printf '%s\n' "Caminho inesperado; desinstalação cancelada: $APP_DIR" >&2; exit 1 ;;
esac

if [ -d "$APP_DIR" ]; then
  rm -r -- "$APP_DIR"
fi
CLI_FILE="$DATA_ROOT/bin/multilut-ctl"
if [ -f "$CLI_FILE" ]; then
  rm -- "$CLI_FILE"
fi
if [ -f "$DESKTOP_FILE" ]; then
  rm -- "$DESKTOP_FILE"
fi
if [ -f "$ICON_FILE" ]; then
  rm -- "$ICON_FILE"
fi
if [ -f "$USER_DESKTOP_FILE" ]; then
  rm -- "$USER_DESKTOP_FILE"
fi

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$DATA_ROOT/applications" >/dev/null 2>&1 || true
fi

# encerra e remove o daemon (serviço de usuário) e a entrada de autostart
if command -v systemctl >/dev/null 2>&1; then
  systemctl --user stop multilut-daemon.service >/dev/null 2>&1 || true
  systemctl --user disable multilut-daemon.service >/dev/null 2>&1 || true
fi
rm -f "$HOME/.config/systemd/user/multilut-daemon.service"
rm -f "$HOME/.config/autostart/com.felipesantiago.MultiLUTController.desktop"

printf '%s\n' "MultiLUT Controller removido."
printf '%s\n' "O shader, o atlas e seus backups foram preservados em ~/.config/vkBasalt."
