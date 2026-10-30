#!/usr/bin/env python3
"""Ícone na bandeja (AppIndicator) com menu rápido do MultiLUT Controller.

O GTK4 não tem mais Gtk.StatusIcon; o caminho suportado no Linux é o
protocolo StatusNotifier via libayatana-appindicator (AyatanaAppIndicator3,
com fallback para AppIndicator3 clássico). O import de gi é lazy: sem a
biblioteca, o app abre normalmente sem bandeja e o doctor/Sistema explicam.

No GNOME é necessário o suporte a AppIndicator (extensão “AppIndicator and
Kyls...”/AppIndicator extension) ou um shell que implemente StatusNotifier.
"""

from __future__ import annotations

from pathlib import Path

import multilut_core as core


class TrayError(core.MultiLUTError):
    """Sem suporte a bandeja neste ambiente."""


INDICATOR_ID = "multilut-controller"


def tray_icon_path() -> str | None:
    """Caminho do ícone SVG do app (repositório, diretório do módulo ou hicolor)."""
    module_dir = Path(core.__file__).resolve().parent
    candidates = [
        module_dir / "assets/com.felipesantiago.MultiLUTController.svg",
        Path("/usr/local/share/icons/hicolor/scalable/apps")
        / "com.felipesantiago.MultiLUTController.svg",
        Path("/usr/share/icons/hicolor/scalable/apps")
        / "com.felipesantiago.MultiLUTController.svg",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _import_indicator():
    """Módulo do indicador disponível (Ayatana → clássico) ou None."""
    try:
        import gi
    except ImportError:
        return None
    for name in ("AyatanaAppIndicator3", "AppIndicator3"):
        try:
            gi.require_version(name, "0.1")
        except (ValueError, ImportError):
            continue
        try:
            return __import__(f"gi.repository.{name}", fromlist=[name])
        except (ImportError, ValueError):
            continue
    return None


def tray_supported() -> bool:
    """True quando há libayatana-appindicator (ou AppIndicator3) no sistema."""
    return _import_indicator() is not None


def recent_profiles(limit: int = 5) -> list[tuple[int, str]]:
    """Perfis das últimas trocas, sem repetição e mais recentes primeiro."""
    seen: list[int] = []
    result: list[tuple[int, str]] = []
    for entry in core.read_history(limit=40):
        try:
            profile_id = int(entry.get("profile_id"))
        except (TypeError, ValueError):
            continue
        if profile_id in seen or profile_id not in core.PROFILE_BY_ID:
            continue
        seen.append(profile_id)
        result.append((profile_id, core.PROFILE_BY_ID[profile_id].name))
        if len(result) >= limit:
            break
    return result


def build_menu_entries(
    recent_profiles: list[tuple[int, str]] | None = None,
    pilot_on: bool = True,
) -> list[tuple]:
    """Itens do menu da bandeja em formato puro e testável.

    ("profile", id, rótulo) aciona app.activate-profile::<id>;
    ("action", rótulo, ação) aciona a ação do aplicativo diretamente.
    """
    items: list[tuple] = []
    for profile_id, name in recent_profiles or []:
        items.append(("profile", int(profile_id), f"{int(profile_id):02d} — {name}"))
    if items:
        items.append(("action", "—", "disabled"))
    items.append(("action", "Próximo perfil", "app.next-profile"))
    items.append(("action", "Perfil anterior", "app.prev-profile"))
    items.append(("action", "Pausar piloto" if pilot_on else "Retomar piloto", "app.toggle-pilot"))
    items.append(("action", "Abrir janela", "app.open-window"))
    items.append(("action", "Sair", "app.quit"))
    return items


class TrayIcon:
    """Indicador de bandeja com menu reconstruído a cada troca relevante."""

    def __init__(self, icon_path: str | None = None):
        module = _import_indicator()
        if module is None:
            raise TrayError(
                "Sem suporte a bandeja: instale libayatana-appindicator "
                "(Solus: sudo eopkg it libayatana-appindicator-gtk3) e, no "
                "GNOME, habilite a extensão AppIndicator."
            )
        self._module = module
        self.indicator = module.Indicator.new(
            INDICATOR_ID,
            icon_path or tray_icon_path() or "image-missing",
            module.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(module.IndicatorStatus.ACTIVE)
        self._menu_model = self._gio_menu()
        self.indicator.set_menu(self._menu_from_model(self._menu_model))

    @staticmethod
    def _gio_menu():
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio

        return Gio.Menu()

    @staticmethod
    def _menu_from_model(model):
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk

        return Gtk.Menu.new_from_model(model)

    def update(self, items: list[tuple]) -> None:
        """Reconstrói o menu a partir do formato de build_menu_entries."""
        self._menu_model.remove_all()
        for item in items:
            if item[0] == "profile":
                _, profile_id, label = item
                menu_item = self._menu_item(
                    label, f"app.activate-profile::{int(profile_id)}"
                )
            elif item[2] == "disabled":
                continue  # separador textual: Gio.Menu nativo cuidaria disso
            else:
                _, label, action = item
                menu_item = self._menu_item(label, action)
            self._menu_model.append_item(menu_item)

    @staticmethod
    def _menu_item(label: str, action: str):
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio

        return Gio.MenuItem.new(label, action)

    def destroy(self) -> None:
        try:
            self.indicator.set_status(self._module.IndicatorStatus.PASSIVE)
        except (AttributeError, RuntimeError):
            pass
