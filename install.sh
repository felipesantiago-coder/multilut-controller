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
chmod 644 "$APP_DIR/multilut_controller.py" "$APP_DIR/multilut_core.py" "$APP_DIR/multilut_extra.py" "$APP_DIR/multilut_ctl.py" "$APP_DIR/multilut_daemon.py" "$APP_DIR/multilut_preview.py" "$APP_DIR/multilut_atlas.py" "$APP_DIR/multilut_tray.py"

# Marcações para o verificador de atualizações: de qual commit veio este
# código e quando a instalação foi feita (falls back do comparador).
if [ -d "$SOURCE_DIR/.git" ]; then
  git -C "$SOURCE_DIR" rev-parse HEAD > "$APP_DIR/source_commit" 2>/dev/null || true
elif [ -f "$SOURCE_DIR/source_commit" ]; then
  cp "$SOURCE_DIR/source_commit" "$APP_DIR/source_commit"
fi
date -u +%s > "$APP_DIR/install_stamp"

# Geração do código: a janela e o daemon que já estão rodando comparam a
# geração que viram no arranque com esta; mudou, eles se reiniciam sozinhos
# para rodar o código novo — ninguém precisa fechar nada na mão.
STATE_ROOT="${XDG_STATE_HOME:-$HOME/.local/state}"
if [ -s "$APP_DIR/source_commit" ]; then
  mkdir -p "$STATE_ROOT/multilut-controller" 2>/dev/null || true
  cp "$APP_DIR/source_commit" \
     "$STATE_ROOT/multilut-controller/update_generation" 2>/dev/null || true
fi

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
  printf '%s\n' "Piloto sem janela (daemon): instalado e iniciado automaticamente pelo app."
  printf '%s\n' "Iniciar com a sessão: multilut-ctl autostart on"
  if python3 -c 'import numpy, PIL' >/dev/null 2>&1; then
    printf '%s\n' "Simulação de LUT pronta (numpy + Pillow encontrados)."
  else
    printf '%s\n' "Dica: para a pré-visualização de LUT, instale numpy e Pillow:"
    printf '%s\n' "  sudo eopkg it numpy python-pillow"
  fi
  # Indicador de bandeja: binding do AppIndicator não dá para instalar sem
  # sudo; o install.sh é o único momento em que o app consegue buscar isso.
  if ! python3 -c 'import gi; gi.require_version("AyatanaAppIndicator3", "0.1")' >/dev/null 2>&1 \
     && ! python3 -c 'import gi; gi.require_version("AppIndicator3", "0.1")' >/dev/null 2>&1; then
    printf '%s\n' "Para o indicador de bandeja (menu rápido com a janela fechada) falta o"
    printf '%s\n' "suporte a AppIndicator."
    if command -v eopkg >/dev/null 2>&1 && [ -t 0 ]; then
      printf '%s' "Instalar agora (sudo eopkg it libayatana-appindicator-gtk3)? [s/N] "
      resposta=""
      read -r resposta || resposta=""
      case "$resposta" in
        s|S|sim|Sim|SIM)
          if sudo eopkg it libayatana-appindicator-gtk3; then
            printf '%s\n' "Suporte ao indicador instalado."
          else
            printf '%s\n' "Não foi possível instalar agora; rode manualmente:"
            printf '%s\n' "  sudo eopkg it libayatana-appindicator-gtk3"
          fi
          ;;
      esac
    else
      printf '%s\n' "  Solus: sudo eopkg it libayatana-appindicator-gtk3"
    fi
  fi
else
  printf '%s\n' "O aplicativo foi instalado, mas faltam dependências gráficas."
  printf '%s\n' "No Centro de Programas do Solus, instale: PyGObject para Python 3, GTK 4 e libadwaita."
  printf '%s\n' "Depois, abra MultiLUT Controller pelo menu de aplicativos."
fi
