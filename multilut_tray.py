#!/usr/bin/env python3
"""Ícone na bandeja (AppIndicator) com menu rápido do MultiLUT Controller.

A janela principal é GTK4 e um processo GTK4 não consegue usar o binding
GTK3 do AppIndicator: Gtk.Menu foi removido no GTK4 e a namespace Gtk já
está carregada como 4.0, de modo que AyatanaAppIndicator3 (GTK3) nem
importa dentro da janela. Por isso o indicador roda em um processo
auxiliar próprio, GTK3 puro — este módulo é a biblioteca e o ponto de
entrada dele:

    python3 multilut_tray.py --serve

O auxiliar lê sozinho o config (piloto ativo?) e o histórico (perfis
recentes) a cada poucos segundos e aciona as ações do aplicativo
(next-profile, prev-profile, activate-profile, toggle-pilot, open-window,
quit) por D-Bus (Gio.DBusActionGroup). Quando o aplicativo some da
sessão, o auxiliar encerra a si mesmo. Sem libayatana-appindicator, sai
com o código 3 e o aplicativo avisa o que falta.

Itens de Gio.Menu com ações "app.*" não resolvem fora de uma janela de
aplicação; o menu é montado então com Gtk.MenuItem clássico e o clique
ativa a ação remota via DBusActionGroup.

No GNOME é necessário o suporte a AppIndicator (extensão “AppIndicator
and Kyls...”) ou um shell que implemente StatusNotifier.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

import multilut_core as core


class TrayError(core.MultiLUTError):
    """Sem suporte a bandeja neste ambiente."""


INDICATOR_ID = "multilut-controller"
POLL_SECONDS = 2
APP_APPEAR_TIMEOUT = 60
EXIT_USAGE = 2
EXIT_NO_BINDING = 3
EXIT_NO_SESSION_BUS = 4


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


def app_action_target(app_id: str = core.APP_ID) -> tuple[str, str]:
    """(nome no barramento, caminho do objeto) das ações do aplicativo.

    O GApplication exporta as ações da sessão com o id como nome de
    barramento e o caminho de objeto derivado (pontos → barras).
    """
    return app_id, "/" + app_id.replace(".", "/")


def entries_signature(entries: list[tuple]) -> tuple:
    """Assinatura comparável do menu: reconstrói só quando muda de verdade."""
    return tuple(tuple(str(part) for part in item) for item in entries)


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

    ("profile", id, rótulo) aciona activate-profile::<id>;
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
    """Indicador GTK3 com menu de widgets (padrão clássico do AppIndicator)."""

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
        self._menu = None

    def update(self, items: list[tuple], on_profile, on_action) -> None:
        """Reconstrói o menu a partir do formato de build_menu_entries.

        on_profile(_item, profile_id) e on_action(_item, ação) são os
        handlers de clique fornecidos pelo processo auxiliar.
        """
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk

        menu = Gtk.Menu.new()
        for item in items:
            kind = item[0]
            if kind == "profile":
                _, profile_id, label = item
                widget = Gtk.MenuItem.new_with_label(label)
                widget.connect("activate", on_profile, int(profile_id))
            elif item[2] == "disabled":
                widget = Gtk.SeparatorMenuItem.new()
            else:
                _, label, action = item
                widget = Gtk.MenuItem.new_with_label(label)
                widget.connect("activate", on_action, action)
            menu.append(widget)
        menu.show_all()
        self._menu = menu
        self.indicator.set_menu(menu)

    def destroy(self) -> None:
        try:
            self.indicator.set_status(self._module.IndicatorStatus.PASSIVE)
        except (AttributeError, RuntimeError):
            pass


def _actions_proxy():
    """Gio.DBusActionGroup das ações do aplicativo (janela principal)."""
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio

    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    name, path = app_action_target()
    return Gio.DBusActionGroup.get(bus, name, path), name


def serve() -> int:
    """Processo auxiliar do indicador; retorna o código de saída.

    Requer GTK3 (namespace livre neste processo) + AppIndicator. Nunca
    toca no GTK4: quem chama este módulo é um processo separado da
    janela principal.
    """
    import signal

    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gio, GLib, Gtk
    except (ImportError, ValueError):
        print(
            "multilut-tray: PyGObject ou GTK3 indisponível neste ambiente",
            flush=True,
        )
        return EXIT_NO_BINDING

    module = _import_indicator()
    if module is None:
        print(
            "multilut-tray: libayatana-appindicator ausente "
            "(Solus: sudo eopkg it libayatana-appindicator-gtk3)",
            flush=True,
        )
        return EXIT_NO_BINDING
    try:
        actions, bus_name = _actions_proxy()
    except Exception as exc:  # sem barramento de sessão não há bandeja
        print(f"multilut-tray: sem barramento de sessão ({exc})", flush=True)
        return EXIT_NO_SESSION_BUS

    state = {"seen": False, "deadline": None, "sig": None}
    icon = TrayIcon()

    def on_profile(_item, profile_id: int) -> None:
        actions.activate_action(
            "activate-profile", GLib.Variant.new_string(str(int(profile_id)))
        )

    def on_action(_item, action: str) -> None:
        actions.activate_action(action.split(".", 1)[-1], None)

    def rebuild() -> None:
        """Lê config + histórico e reconstrói o menu só quando mudou."""
        pilot_on = bool(core.load_config().get("auto_map_switch", False))
        entries = build_menu_entries(recent_profiles(), pilot_on=pilot_on)
        signature = entries_signature(entries)
        if signature != state["sig"]:
            state["sig"] = signature
            icon.update(entries, on_profile, on_action)

    def tick() -> bool:
        try:
            rebuild()
        except Exception:  # arquivo corrompido etc.: registra e segue vivo
            traceback.print_exc()
        return True

    def appeared(*_args) -> None:
        state["seen"] = True
        if state["deadline"] is not None:
            GLib.source_remove(state["deadline"])
            state["deadline"] = None

    def give_up() -> bool:
        if not state["seen"]:
            Gtk.main_quit()
        return GLib.SOURCE_REMOVE

    def vanished(*_args) -> None:
        if state["seen"]:
            Gtk.main_quit()  # o aplicativo saiu da sessão: encerrar junto
            return
        if state["deadline"] is None:
            # corrida de partida: tolera o app ainda não registrado
            state["deadline"] = GLib.timeout_add_seconds(
                APP_APPEAR_TIMEOUT, give_up
            )

    try:
        rebuild()  # menu pronto já na primeira exibição
    except Exception:
        traceback.print_exc()
    GLib.timeout_add_seconds(POLL_SECONDS, tick)
    Gio.bus_watch_name(
        Gio.BusType.SESSION,
        bus_name,
        Gio.BusNameWatcherFlags.NONE,
        appeared,
        vanished,
    )
    try:
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, Gtk.main_quit)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, Gtk.main_quit)
    except (AttributeError, ValueError):
        pass

    Gtk.main()
    icon.destroy()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    if "--serve" not in argv:
        print("uso: multilut_tray.py --serve", file=sys.stderr)
        return EXIT_USAGE
    try:
        return serve()
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
