#!/usr/bin/env python3
"""Native GTK4/Libadwaita profile controller for MultiLUT + vkBasalt."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
import sys

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_version("Gdk", "4.0")
    gi.require_version("GdkPixbuf", "2.0")
    gi.require_version("Pango", "1.0")
    from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango
except (ImportError, ValueError) as exc:
    print(
        "MultiLUT Controller requer Python 3, PyGObject, GTK 4 e libadwaita.\n"
        "Instale as dependências pelo Centro de Programas do Solus e tente novamente.",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc

import multilut_atlas as atlas
import multilut_core as core
import multilut_extra as extra
import multilut_preview as preview


BASE_DIR = Path(__file__).resolve().parent
BUNDLE_DIR = BASE_DIR / "bundle"
MAP_IMAGE_DIR = BASE_DIR / "assets" / "maps"

ORIGIN_LABELS = {
    "manual": "Manual",
    "auto-map": "Piloto automático",
    "auto-launch": "Início do jogo",
    "cli": "CLI",
    "hotkey": "Atalho global",
    "external": "Troca externa",
}

# Portal de atalhos globais (org.freedesktop.portal.GlobalShortcuts; GNOME 46+)
PORTAL_BUS_NAME = "org.freedesktop.portal.Desktop"
PORTAL_OBJECT_PATH = "/org/freedesktop/portal/desktop"
GLOBAL_SHORTCUTS_IFACE = "org.freedesktop.portal.GlobalShortcuts"
HOTKEY_SHORTCUT_ID = "multilut-next"
HOTKEY_PREFERRED = "<Control><Alt>l"


CSS = b"""
window { background: @window_bg_color; }
.app-title { font-size: 20px; font-weight: 800; }
.hero-title { font-size: 28px; font-weight: 800; }
.profile-number {
  background: alpha(@accent_bg_color, 0.18);
  color: @accent_color;
  border-radius: 999px;
  font-weight: 800;
  min-width: 34px;
  min-height: 34px;
}
.category-label { color: alpha(currentColor, 0.62); font-size: 12px; }
.section-title { font-weight: 700; font-size: 15px; }
.muted { color: alpha(currentColor, 0.67); }
.status-strip {
  background: alpha(@accent_bg_color, 0.10);
  border-bottom: 1px solid alpha(currentColor, 0.10);
}
.status-live { background: alpha(#2ec27e, 0.12); }
.card {
  background: @card_bg_color;
  border: 1px solid alpha(currentColor, 0.10);
  border-radius: 14px;
}
.path-box {
  background: alpha(currentColor, 0.055);
  border-radius: 10px;
}
.success { color: #2ec27e; font-weight: 700; }
.warning { color: #e5a50a; font-weight: 700; }
.sidebar { background: alpha(@headerbar_bg_color, 0.72); }
list row { border-radius: 10px; margin: 2px 6px; }
list row:selected { background: alpha(@accent_bg_color, 0.18); }
.map-card {
  border-radius: 12px;
}
.map-card:hover { filter: brightness(1.08); }
.map-scrim {
  min-height: 78px;
  background-image: linear-gradient(
    to bottom,
    alpha(#000000, 0.22) 0%,
    alpha(#000000, 0.10) 45%,
    alpha(#000000, 0.68) 100%
  );
}
.map-card-fallback {
  min-height: 78px;
  background: linear-gradient(
    to bottom,
    alpha(@accent_bg_color, 0.30),
    alpha(@accent_bg_color, 0.55)
  );
}
.map-card-title {
  font-size: 17px;
  font-weight: 800;
  color: #ffffff;
  text-shadow: 0 1px 3px alpha(#000000, 0.9), 0 0 8px alpha(#000000, 0.55);
}
.map-card-badge {
  background: alpha(#000000, 0.45);
  color: #ffffff;
  border-radius: 999px;
  font-weight: 800;
  font-size: 12px;
  min-width: 26px;
  min-height: 26px;
}
.map-card-frame {
  border-radius: 12px;
  border: 1px solid alpha(currentColor, 0.12);
}
.active-flag {
  min-width: 18px;
  min-height: 18px;
  -gtk-icon-shadow: 0 1px 3px alpha(black, 0.85);
}
"""


class ProfileRow(Gtk.ListBoxRow):
    def __init__(self, profile: core.Profile):
        super().__init__()
        self.profile = profile
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)

        number = Gtk.Label(label=f"{profile.id:02d}")
        number.add_css_class("profile-number")
        number.set_halign(Gtk.Align.CENTER)
        number.set_valign(Gtk.Align.CENTER)
        box.append(number)

        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label=profile.name, xalign=0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_hexpand(True)
        category = Gtk.Label(label=profile.category, xalign=0)
        category.add_css_class("category-label")
        labels.append(title)
        labels.append(category)
        box.append(labels)

        self.active_flag = Gtk.Image.new_from_icon_name("media-playback-start-symbolic")
        self.active_flag.add_css_class("accent")
        self.active_flag.add_css_class("active-flag")
        self.active_flag.set_tooltip_text("Perfil aplicado no shader")
        self.active_flag.set_valign(Gtk.Align.CENTER)
        self.active_flag.set_visible(False)
        box.append(self.active_flag)
        self.set_child(box)

    def set_active_flag(self, active: bool) -> None:
        self.active_flag.set_visible(active)


class SectionHeaderRow(Gtk.ListBoxRow):
    """Cabeçalho de seção da lista de perfis (não selecionável)."""
    def __init__(self, title: str):
        super().__init__()
        self.set_selectable(False)
        self.set_activatable(False)
        self.set_focusable(False)
        label = Gtk.Label(label=title, xalign=0)
        label.add_css_class("section-title")
        label.set_margin_top(12)
        label.set_margin_bottom(2)
        label.set_margin_start(16)
        self.set_child(label)


class MapCardRow(Gtk.ListBoxRow):
    """Cartão de perfil de mapa: foto oficial de fundo + nome em destaque.

    A foto vem de assets/maps/<slug>.jpg (extraída dos depots oficiais do
    jogo). Sem a foto, cai num degradê com a cor de destaque do tema.
    """

    CARD_HEIGHT = 84

    def __init__(self, profile: core.Profile, image_path: Path | None):
        super().__init__()
        self.profile = profile
        overlay = Gtk.Overlay()
        overlay.add_css_class("map-card")
        if hasattr(Gtk, "Overflow") and hasattr(overlay, "set_overflow"):
            # GTK 4.8+: recorta a foto nos cantos arredondados do cartão.
            overlay.set_overflow(Gtk.Overflow.HIDDEN)
        overlay.set_size_request(-1, self.CARD_HEIGHT)

        if image_path is not None and image_path.is_file():
            background = Gtk.Picture()
            try:
                texture = Gdk.Texture.new_from_filename(str(image_path))
                background.set_paintable(texture)
            except (GLib.Error, AttributeError):
                pass
            if hasattr(Gtk, "ContentFit"):
                background.set_content_fit(Gtk.ContentFit.COVER)
            else:  # GTK < 4.8: mantém proporção cortando pelo meio
                background.set_keep_aspect_ratio(False)
            background.set_can_shrink(True)
            background.set_hexpand(True)
            background.set_vexpand(True)
        else:
            background = Gtk.Box()
            background.add_css_class("map-card-fallback")
            background.set_hexpand(True)
            background.set_vexpand(True)
        overlay.set_child(background)

        scrim = Gtk.Box()
        scrim.add_css_class("map-scrim")
        scrim.set_hexpand(True)
        scrim.set_vexpand(True)
        overlay.add_overlay(scrim)

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        content.set_margin_top(8)
        content.set_margin_bottom(8)
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.set_valign(Gtk.Align.END)
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        title_box.set_valign(Gtk.Align.END)
        title = Gtk.Label(label=profile.name, xalign=0)
        title.add_css_class("map-card-title")
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_hexpand(True)
        title_box.append(title)
        content.append(title_box)
        self.active_flag = Gtk.Image.new_from_icon_name("media-playback-start-symbolic")
        self.active_flag.add_css_class("accent")
        self.active_flag.add_css_class("active-flag")
        self.active_flag.set_tooltip_text("Perfil aplicado no shader")
        self.active_flag.set_valign(Gtk.Align.CENTER)
        self.active_flag.set_visible(False)
        content.append(self.active_flag)
        badge = Gtk.Label(label=f"{profile.id:02d}")
        badge.add_css_class("map-card-badge")
        badge.set_valign(Gtk.Align.CENTER)
        badge.set_halign(Gtk.Align.END)
        content.append(badge)
        overlay.add_overlay(content)

        self.set_child(overlay)

    def set_active_flag(self, active: bool) -> None:
        self.active_flag.set_visible(active)


class MultiLUTWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application):
        super().__init__(application=application)
        self.set_title("MultiLUT Controller")
        self.set_size_request(420, 400)

        self.config = core.load_config()
        window_state = self.config.get("window")
        if not isinstance(window_state, dict):
            window_state = {}
        start_w, start_h = self._fit_size_to_monitor(
            int(window_state.get("width") or 1040),
            int(window_state.get("height") or 700),
        )
        self.set_default_size(start_w, start_h)
        self.connect("close-request", self.on_close_request)
        remembered = self.config.get("shader_path")
        candidates = core.find_shader_candidates()
        self.shader_path = Path(remembered).expanduser() if remembered else (
            candidates[0] if candidates else core.default_shader_path()
        )
        self.selected_profile = core.PROFILE_BY_ID[14]
        self.shader_valid = False
        self.file_monitor = None
        self._programmatic_selection = False
        self._atlas_pixbuf = None
        self._atlas_pixbuf_source = None
        # pré-visualização LUT (simulação em CPU do shader)
        self._preview_generation = 0
        self._preview_programmatic = False
        self._preview_map_choices: list[tuple[str, str]] = []
        self.game_resolution = self._game_resolution_from_config()
        self._game_was_running = None
        self._shader_was_valid = False
        # piloto automático por mapa (console.log)
        self._console_monitor = None
        self._console_path = None
        self._console_tail = None
        self._console_debounce_id = None
        # atalho global (portal)
        self._hotkey_bus = None
        self._hotkey_session = None
        self._hotkey_signal_ids: list[int] = []
        self._hotkey_thread = None
        self._hotkey_applying = False

        self.toast_overlay = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.view_stack = Adw.ViewStack()
        self.view_stack.set_vexpand(True)
        switcher = Adw.ViewSwitcher(stack=self.view_stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)

        self.restore_button = Gtk.Button.new_from_icon_name("edit-undo-symbolic")
        self.restore_button.set_tooltip_text("Restaurar último backup (Ctrl+Z)")
        self.restore_button.connect("clicked", self.on_restore)
        header.pack_end(self.restore_button)

        folder_button = Gtk.Button.new_from_icon_name("folder-open-symbolic")
        folder_button.set_tooltip_text("Abrir pasta do shader")
        folder_button.connect("clicked", self.on_open_folder)
        header.pack_end(folder_button)

        about_button = Gtk.Button.new_from_icon_name("help-about-symbolic")
        about_button.set_tooltip_text("Sobre o aplicativo")
        about_button.connect("clicked", self.on_about)
        header.pack_end(about_button)
        toolbar.add_top_bar(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.status_strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.status_strip.add_css_class("status-strip")
        self.status_strip.set_margin_start(0)
        self.status_strip.set_margin_end(0)
        self.status_strip.set_margin_top(0)
        self.status_strip.set_margin_bottom(0)
        inner_status = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        inner_status.set_hexpand(True)
        inner_status.set_margin_start(18)
        inner_status.set_margin_end(18)
        inner_status.set_margin_top(10)
        inner_status.set_margin_bottom(10)
        self.status_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        self.status_label = Gtk.Label(xalign=0)
        self.status_label.set_hexpand(True)
        self.game_label = Gtk.Label(xalign=1)
        self.game_label.add_css_class("muted")
        self.game_label.set_ellipsize(Pango.EllipsizeMode.START)
        inner_status.append(self.status_icon)
        inner_status.append(self.status_label)
        inner_status.append(self.game_label)
        self.status_strip.append(inner_status)
        body.append(self.status_strip)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_vexpand(True)
        paned.set_position(340)
        paned.set_shrink_start_child(False)
        paned.set_shrink_end_child(False)
        paned.set_wide_handle(True)
        paned.set_start_child(self.build_sidebar())
        paned.set_end_child(self.build_detail())

        page_profiles = self.view_stack.add_titled(paned, "profiles", "Perfis")
        page_profiles.set_icon_name("view-grid-symbolic")
        self._page_profiles = page_profiles
        page_atlas = self.view_stack.add_titled(
            self.build_atlas_page(), "atlas", "Atlas"
        )
        page_atlas.set_icon_name("image-x-generic-symbolic")
        page_history = self.view_stack.add_titled(
            self.build_history_page(), "history", "Histórico"
        )
        page_history.set_icon_name("document-open-recent-symbolic")
        page_system = self.view_stack.add_titled(
            self.build_system_page(), "system", "Sistema"
        )
        page_system.set_icon_name("emblem-system-symbolic")
        self.view_stack.connect("notify::visible-child", self.on_visible_page_changed)
        body.append(self.view_stack)

        toolbar.set_content(body)
        self.toast_overlay.set_child(toolbar)
        self.set_content(self.toast_overlay)
        self._install_shortcuts()

        self.refresh_shader_status(select_active=True)
        self.refresh_game_status()
        if window_state.get("maximized"):
            self.maximize()
        GLib.timeout_add_seconds(2, self.refresh_game_status)
        GLib.timeout_add_seconds(6, self._check_updates_once)
        self.start_file_monitor()
        self.start_console_monitor()
        if bool(self.config.get("global_shortcut", False)):
            self._register_global_shortcut()

    # ------------------------------------------------------------ adaptação à tela
    def _fit_size_to_monitor(self, width: int, height: int) -> tuple[int, int]:
        """Limita o tamanho pedido à área útil do monitor (pontos lógicos).

        Respeita a escala do sistema (Wayland/HiDPI): a geometria do monitor
        já vem em pontos lógicos, então o limite funciona igual em telas
        normais e com escala fracionária.
        """
        min_w, min_h = 420, 400
        width, height = max(min_w, width), max(min_h, height)
        display = Gdk.Display.get_default()
        if display is None:
            return width, height
        monitor = None
        surface = self.get_surface()
        if surface is not None and hasattr(display, "get_monitor_at_surface"):
            monitor = display.get_monitor_at_surface(surface)
        if monitor is None and hasattr(display, "get_monitors"):
            monitors = display.get_monitors()
            if monitors is not None and monitors.get_n_items() > 0:
                monitor = monitors.get_item(0)
        if monitor is None:
            return width, height
        geometry = monitor.get_geometry()
        usable_w = max(min_w, int(geometry.width * 0.92))
        usable_h = max(min_h, int(geometry.height * 0.92))
        return min(width, usable_w), min(height, usable_h)

    def on_close_request(self, _window) -> bool:
        """Guarda o tamanho da janela para a próxima abertura."""
        state = self.config.get("window")
        if not isinstance(state, dict):
            state = {}
            self.config["window"] = state
        state["width"], state["height"] = self.get_default_size()
        state["maximized"] = bool(self.is_maximized())
        try:
            core.save_config(self.config)
        except (OSError, core.MultiLUTError):
            pass
        return False

    def _wrap_box(self, spacing: int, homogeneous: bool = False) -> Gtk.Widget:
        """Linha que empilha os filhos verticalmente quando falta largura.

        Usa Adw.WrapBox (libadwaita >= 1.7) e cai para Gtk.Box em versões
        antigas — assim a janela nunca depende de APIs instáveis para abrir.
        """
        if hasattr(Adw, "WrapBox"):
            box = Adw.WrapBox()
            box.set_property("line-homogeneous", homogeneous)
            box.set_property("child-spacing", spacing)
            box.set_property("line-spacing", spacing)
            return box
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)
        if homogeneous:
            box.set_homogeneous(True)
        return box

    def build_sidebar(self) -> Gtk.Widget:
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        sidebar.add_css_class("sidebar")
        sidebar.set_size_request(260, -1)

        heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        heading.set_margin_start(16)
        heading.set_margin_end(16)
        heading.set_margin_top(14)
        label = Gtk.Label(label="Perfis", xalign=0)
        label.add_css_class("section-title")
        hint = Gtk.Label(label="Efeitos de mapa e utilitários", xalign=0)
        hint.add_css_class("muted")
        heading.append(label)
        heading.append(hint)
        sidebar.append(heading)

        self.search = Gtk.SearchEntry(placeholder_text="Buscar perfil ou mapa")
        self.search.set_tooltip_text("Busca por nome, mapa ou número do perfil (Ctrl+F foca)")
        self.search.set_margin_start(12)
        self.search.set_margin_end(12)
        self.search.connect("search-changed", self.on_search_changed)
        sidebar.append(self.search)

        self.search_counter = Gtk.Label(xalign=0)
        self.search_counter.add_css_class("category-label")
        self.search_counter.set_margin_start(16)
        self.search_counter.set_margin_end(16)
        sidebar.append(self.search_counter)

        self.profile_list = Gtk.ListBox()
        self.profile_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.profile_list.set_css_classes(["profiles-list"])
        self.profile_list.connect("row-selected", self.on_profile_selected)
        self._rows_by_id: dict[int, Gtk.ListBoxRow] = {}
        for section_title, profiles in core.profiles_by_section():
            self.profile_list.append(SectionHeaderRow(section_title))
            for profile in profiles:
                slug = core.map_image_slug(profile)
                if slug is not None:
                    row = MapCardRow(profile, MAP_IMAGE_DIR / f"{slug}.jpg")
                else:
                    row = ProfileRow(profile)
                self._rows_by_id[profile.id] = row
                self.profile_list.append(row)
        self.search_counter.set_label(f"{len(core.PROFILES)} perfis")
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(self.profile_list)
        sidebar.append(scroller)

        toggles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        toggles.set_margin_start(16)
        toggles.set_margin_end(16)
        toggles.set_margin_top(4)
        toggles.set_margin_bottom(14)
        toggles.append(
            self._build_toggle_row(
                "Aplicar ao selecionar",
                "Salva o arquivo imediatamente",
                bool(self.config.get("auto_apply", False)),
                self.on_auto_changed,
                "auto_switch",
            )
        )
        toggles.append(
            self._build_toggle_row(
                "Notificar ao trocar de perfil",
                "Aviso discreto do desktop quando a troca vier da automação",
                bool(self.config.get("notify_changes", False)),
                self.on_notify_changed,
                "notify_switch",
            )
        )
        toggles.append(
            self._build_toggle_row(
                "Aplicar último perfil ao abrir o jogo",
                "Detecta a inicialização do Insurgency e aplica o último perfil",
                bool(self.config.get("auto_apply_on_launch", False)),
                self.on_auto_launch_changed,
                "auto_launch_switch",
            )
        )
        toggles.append(
            self._build_toggle_row(
                "Piloto automático por mapa",
                "Acompanha o console.log e aplica o perfil do mapa carregado "
                "(requer -condebug)",
                bool(self.config.get("auto_map_switch", False)),
                self.on_auto_map_changed,
                "auto_map_switch",
            )
        )
        toggles.append(
            self._build_toggle_row(
                "Atalho global de próximo perfil",
                "Registra um atalho do GNOME (portal) para trocar de perfil "
                "de qualquer lugar; padrão sugerido Ctrl+Alt+L",
                bool(self.config.get("global_shortcut", False)),
                self.on_hotkey_changed,
                "hotkey_switch",
            )
        )
        sidebar.append(toggles)
        return sidebar

    def _build_toggle_row(
        self,
        title: str,
        hint: str,
        active: bool,
        callback,
        attr_name: str,
    ) -> Gtk.Widget:
        """Linha de interruptor da barra lateral (título + dica + switch)."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_top(8)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        title_label = Gtk.Label(label=title, xalign=0)
        hint_label = Gtk.Label(label=hint, xalign=0)
        hint_label.add_css_class("category-label")
        hint_label.set_wrap(True)
        labels.set_hexpand(True)
        labels.append(title_label)
        labels.append(hint_label)
        switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        switch.set_active(active)
        switch.connect("notify::active", callback)
        setattr(self, attr_name, switch)
        box.append(labels)
        box.append(switch)
        return box

    def build_detail(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_start(26)
        content.set_margin_end(26)
        content.set_margin_top(24)
        content.set_margin_bottom(24)

        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        category_line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.detail_number = Gtk.Label(label="14")
        self.detail_number.add_css_class("profile-number")
        self.detail_category = Gtk.Label(label="COMPETITIVO")
        self.detail_category.add_css_class("category-label")
        category_line.append(self.detail_number)
        category_line.append(self.detail_category)
        self.detail_title = Gtk.Label(label="Competitivo neutro", xalign=0)
        self.detail_title.add_css_class("hero-title")
        self.detail_title.set_wrap(True)
        self.detail_summary = Gtk.Label(xalign=0, wrap=True)
        self.detail_summary.add_css_class("muted")
        hero.append(category_line)
        hero.append(self.detail_title)
        hero.append(self.detail_summary)
        content.append(hero)

        photo_frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        photo_frame.add_css_class("map-card-frame")
        if hasattr(Gtk, "Overflow") and hasattr(photo_frame, "set_overflow"):
            photo_frame.set_overflow(Gtk.Overflow.HIDDEN)
        self.detail_photo = Gtk.Picture()
        if hasattr(Gtk, "ContentFit"):
            self.detail_photo.set_content_fit(Gtk.ContentFit.COVER)
        self.detail_photo.set_can_shrink(True)
        self.detail_photo.set_size_request(-1, 180)
        photo_frame.append(self.detail_photo)
        photo_frame.set_visible(False)
        self.detail_photo_frame = photo_frame
        content.append(photo_frame)

        information = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        information.add_css_class("card")
        information.set_margin_top(4)
        information.set_margin_bottom(2)
        for widget in (information,):
            widget.set_margin_start(0)
            widget.set_margin_end(0)
        info_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        info_inner.set_margin_start(18)
        info_inner.set_margin_end(18)
        info_inner.set_margin_top(16)
        info_inner.set_margin_bottom(16)
        best_title = Gtk.Label(label="Indicado para", xalign=0)
        best_title.add_css_class("section-title")
        self.detail_best = Gtk.Label(xalign=0, wrap=True)
        self.detail_tone = Gtk.Label(xalign=0)
        self.detail_tone.add_css_class("muted")
        info_inner.append(best_title)
        info_inner.append(self.detail_best)
        info_inner.append(self.detail_tone)
        information.append(info_inner)
        content.append(information)

        path_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        path_card.add_css_class("card")
        path_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        path_inner.set_margin_start(18)
        path_inner.set_margin_end(18)
        path_inner.set_margin_top(16)
        path_inner.set_margin_bottom(16)
        path_title = Gtk.Label(label="Arquivo do shader", xalign=0)
        path_title.add_css_class("section-title")
        path_line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        path_line.add_css_class("path-box")
        self.path_label = Gtk.Label(xalign=0)
        self.path_label.set_hexpand(True)
        self.path_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.path_label.set_margin_start(10)
        choose = Gtk.Button(label="Selecionar…")
        choose.set_margin_top(4)
        choose.set_margin_bottom(4)
        choose.set_margin_end(4)
        choose.connect("clicked", self.on_choose_shader)
        copy_path = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        copy_path.set_tooltip_text("Copiar caminho do shader")
        copy_path.set_margin_top(4)
        copy_path.set_margin_bottom(4)
        copy_path.connect("clicked", self.on_copy_shader_path)
        path_line.append(self.path_label)
        path_line.append(copy_path)
        path_line.append(choose)
        self.shader_validation = Gtk.Label(xalign=0, wrap=True)
        self.shader_validation.add_css_class("muted")
        path_inner.append(path_title)
        path_inner.append(path_line)
        path_inner.append(self.shader_validation)
        path_card.append(path_inner)
        content.append(path_card)

        # --- Atlas do perfil (linha da LUT usada pelo shader) --------------
        atlas_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        atlas_card.add_css_class("card")
        atlas_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        atlas_inner.set_margin_start(18)
        atlas_inner.set_margin_end(18)
        atlas_inner.set_margin_top(14)
        atlas_inner.set_margin_bottom(14)
        atlas_title = Gtk.Label(label="Atlas do perfil", xalign=0)
        atlas_title.add_css_class("section-title")
        self.atlas_row_label = Gtk.Label(xalign=0)
        self.atlas_row_label.add_css_class("category-label")
        self.atlas_picture = Gtk.Picture()
        self.atlas_picture.set_content_fit(Gtk.ContentFit.FILL)
        self.atlas_picture.set_size_request(-1, 26)
        self.atlas_status = Gtk.Label(xalign=0, wrap=True)
        self.atlas_status.add_css_class("muted")
        atlas_inner.append(atlas_title)
        atlas_inner.append(self.atlas_row_label)
        atlas_inner.append(self.atlas_picture)
        atlas_inner.append(self.atlas_status)
        atlas_card.append(atlas_inner)
        content.append(atlas_card)

        # --- Pré-visualização (simulação em CPU do pipeline do shader) -----
        preview_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        preview_card.add_css_class("card")
        preview_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        preview_inner.set_margin_start(18)
        preview_inner.set_margin_end(18)
        preview_inner.set_margin_top(14)
        preview_inner.set_margin_bottom(14)
        preview_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        preview_title = Gtk.Label(label="Pré-visualização (simulação)", xalign=0)
        preview_title.add_css_class("section-title")
        preview_title.set_hexpand(True)
        self._preview_map_choices = self._build_preview_map_choices()
        preview_model = Gtk.StringList.new(
            [title for _, title in self._preview_map_choices]
        )
        self.preview_dropdown = Gtk.DropDown(model=preview_model)
        self.preview_dropdown.set_tooltip_text(
            "Foto do mapa usada como base da simulação"
        )
        remembered_slug = str(self.config.get("preview_map") or "")
        initial_index = next(
            (
                i
                for i, (candidate, _) in enumerate(self._preview_map_choices)
                if candidate == remembered_slug
            ),
            0,
        )
        self.preview_dropdown.set_selected(initial_index)  # antes do connect
        self.preview_dropdown.connect("notify::selected", self.on_preview_map_changed)
        preview_header.append(preview_title)
        preview_header.append(self.preview_dropdown)
        # resolução do jogo: escala o raio do contraste local (P_RADIUS) na simulação
        self.resolution_choices = self._build_resolution_choices()
        resolution_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        resolution_label = Gtk.Label(label="Resolução do jogo:", xalign=0)
        resolution_label.add_css_class("muted")
        resolution_label.set_hexpand(True)
        resolution_model = Gtk.StringList.new(self.resolution_choices)
        self.resolution_dropdown = Gtk.DropDown(model=resolution_model)
        self.resolution_dropdown.set_tooltip_text(
            "Resolução de render configurada no jogo; o raio do contraste local "
            "da simulação é escalado por ela"
        )
        current_resolution = "x".join(str(v) for v in self.game_resolution)
        self.resolution_dropdown.set_selected(
            self.resolution_choices.index(current_resolution)
            if current_resolution in self.resolution_choices
            else 0
        )  # antes do connect
        self.resolution_dropdown.connect(
            "notify::selected", self.on_preview_resolution_changed
        )
        resolution_box.append(resolution_label)
        resolution_box.append(self.resolution_dropdown)
        self.preview_picture = Gtk.Picture()
        self.preview_picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.preview_picture.set_can_shrink(True)
        self.preview_picture.set_size_request(-1, 190)
        preview_labels = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        preview_label_left = Gtk.Label(label="Original", xalign=0.5, hexpand=True)
        preview_label_right = Gtk.Label(label="Simulado", xalign=0.5, hexpand=True)
        for label in (preview_label_left, preview_label_right):
            label.add_css_class("category-label")
            preview_labels.append(label)
        self.preview_status = Gtk.Label(xalign=0, wrap=True)
        self.preview_status.add_css_class("muted")
        self.preview_status.set_label("Selecione um perfil para simular o resultado.")
        preview_inner.append(preview_header)
        preview_inner.append(resolution_box)
        preview_inner.append(self.preview_picture)
        preview_inner.append(preview_labels)
        preview_inner.append(self.preview_status)
        preview_card.append(preview_inner)
        content.append(preview_card)

        self.install_button = Gtk.Button(label="Instalar/atualizar pacote MultiLUT v1.8")
        self.install_button.connect("clicked", self.on_install_bundle)
        content.append(self.install_button)

        self.bundle_check_label = Gtk.Label(xalign=0, wrap=True)
        self.bundle_check_label.add_css_class("category-label")
        content.append(self.bundle_check_label)

        actions = self._wrap_box(10, homogeneous=True)
        self.apply_button = Gtk.Button(label="Aplicar perfil")
        self.apply_button.set_tooltip_text("Aplica o perfil selecionado (Ctrl+Enter)")
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.connect("clicked", self.on_apply)
        self.launch_button = Gtk.Button(label="Aplicar e iniciar o jogo")
        self.launch_button.connect("clicked", self.on_apply_and_launch)
        actions.append(self.apply_button)
        actions.append(self.launch_button)
        content.append(actions)

        limitation = Gtk.Label(
            label=(
                "Troca em tempo real confirmada nesta instalação: ao salvar o .fx, "
                "o vkBasalt recarrega o perfil mesmo com o jogo aberto. F3 continua "
                "disponível para ativar ou desativar todo o efeito."
            ),
            xalign=0,
            wrap=True,
        )
        limitation.add_css_class("muted")
        content.append(limitation)

        scroller.set_child(content)
        self.update_detail(self.selected_profile)
        return scroller

    def toast(self, message: str, timeout: int = 4) -> None:
        toast = Adw.Toast.new(message)
        toast.set_timeout(timeout)
        self.toast_overlay.add_toast(toast)

    def update_detail(self, profile: core.Profile) -> None:
        self.selected_profile = profile
        self.detail_number.set_label(f"{profile.id:02d}")
        self.detail_category.set_label(profile.category.upper())
        self.detail_title.set_label(profile.name)
        self.detail_summary.set_label(profile.summary)
        self.detail_best.set_label(profile.best_for)
        self.detail_tone.set_label(f"Resposta visual: {profile.tone}")
        self._update_detail_photo(profile)
        self.update_atlas_card(profile)
        self.update_preview_card(profile)

    # ------------------------------------------------------- atlas v1.8
    def atlas_source_path(self) -> Path:
        installed = core.default_texture_path()
        if installed.is_file():
            return installed
        return BUNDLE_DIR / "Textures/MultiLut_Insurgency_Optimized.png"

    def load_atlas_pixbuf(self) -> GdkPixbuf.Pixbuf | None:
        source = self.atlas_source_path()
        cached = self._atlas_pixbuf
        if cached is not None and self._atlas_pixbuf_source == str(source):
            return cached
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(source))
        except GLib.Error:
            self._atlas_pixbuf = None
            self._atlas_pixbuf_source = None
            return None
        self._atlas_pixbuf = pixbuf
        self._atlas_pixbuf_source = str(source)
        return pixbuf

    def update_atlas_card(self, profile: core.Profile) -> None:
        """Mostra a faixa da LUT usada pelo perfil no atlas v1.8."""
        if not hasattr(self, "atlas_picture"):
            return
        mapping = self.current_lut_row_map()
        row = (
            mapping.get(profile.id, core.lut_row_for_profile(profile.id))
            if mapping
            else core.lut_row_for_profile(profile.id)
        )
        self.atlas_row_label.set_label(
            f"Perfil {profile.id:02d} · linha {row} do atlas "
            f"({core.ATLAS_SLICES} fatias x {core.ATLAS_ROWS} linhas)"
        )
        pixbuf = self.load_atlas_pixbuf()
        if pixbuf is None:
            self.atlas_picture.set_visible(False)
            self.atlas_status.set_label(
                "Atlas não localizado — instale o pacote MultiLUT para pré-visualizar."
            )
            return
        valid, message = core.validate_texture(self.atlas_source_path())
        if not valid:
            self.atlas_picture.set_visible(False)
            self.atlas_status.set_label(message)
            return
        width = pixbuf.get_width()
        height = pixbuf.get_height()
        row_height = max(1, height // core.ATLAS_ROWS)
        top = min(row * row_height, max(0, height - row_height))
        strip = pixbuf.new_subpixbuf(0, top, width, row_height)
        self.atlas_picture.set_paintable(Gdk.Texture.new_for_pixbuf(strip))
        self.atlas_picture.set_visible(True)
        self.atlas_status.set_label(message)

    # ------------------------------------------------------- aba Atlas (Lote 2)
    def build_atlas_page(self) -> Gtk.Widget:
        """Página do atlas v1.8: override de linhas com .cube e reindexação."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.set_margin_start(26)
        page.set_margin_end(26)
        page.set_margin_top(20)
        page.set_margin_bottom(20)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        title = Gtk.Label(label="Atlas v1.8", xalign=0)
        title.add_css_class("hero-title")
        title.set_hexpand(True)
        restore_bundle_button = Gtk.Button(label="Restaurar atlas do pacote")
        restore_bundle_button.set_tooltip_text(
            "Copia o atlas original do pacote v1.8 por cima do instalado "
            "(o atlas atual fica de backup)"
        )
        restore_bundle_button.connect("clicked", self.on_atlas_restore_bundle)
        header.append(title)
        header.append(restore_bundle_button)
        page.append(header)

        self.atlas_page_status = Gtk.Label(xalign=0, wrap=True)
        self.atlas_page_status.add_css_class("muted")
        page.append(self.atlas_page_status)

        self.atlas_rows_list = Gtk.ListBox()
        self.atlas_rows_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.atlas_rows_list.add_css_class("card")
        self.atlas_rows_list.connect("row-selected", self.on_atlas_row_selected)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.atlas_rows_list)
        scroller.set_vexpand(True)
        page.append(scroller)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.atlas_override_button = Gtk.Button(label="Substituir por .cube…")
        self.atlas_override_button.add_css_class("suggested-action")
        self.atlas_override_button.set_tooltip_text(
            "Interpreta a LUT 3D do .cube, reamostra para 32³ e grava na linha "
            "selecionada do atlas instalado (com backup)"
        )
        self.atlas_override_button.connect("clicked", self.on_atlas_override_clicked)
        self.atlas_restore_row_button = Gtk.Button(
            label="Restaurar linha do pacote"
        )
        self.atlas_restore_row_button.set_tooltip_text(
            "Devolve a linha selecionada à LUT original do pacote v1.8"
        )
        self.atlas_restore_row_button.connect(
            "clicked", self.on_atlas_restore_row_clicked
        )
        self.atlas_restore_backup_button = Gtk.Button(label="Restaurar backup (.bak)")
        self.atlas_restore_backup_button.set_tooltip_text(
            "Copia o backup mais recente do atlas de volta ao lugar"
        )
        self.atlas_restore_backup_button.connect(
            "clicked", self.on_atlas_restore_backup_clicked
        )
        for button in (
            self.atlas_override_button,
            self.atlas_restore_row_button,
            self.atlas_restore_backup_button,
        ):
            actions.append(button)
        page.append(actions)

        reindex_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        reindex_card.add_css_class("card")
        reindex_title = Gtk.Label(
            label="Reindexação — perfil → linha do atlas (P_LUT_ROW)", xalign=0
        )
        reindex_title.add_css_class("section-title")
        reindex_help = Gtk.Label(
            xalign=0,
            wrap=True,
            label=(
                "Aponta um perfil para outra LUT-base do atlas reescrevendo o "
                "bloco P_LUT_ROW do shader instalado (com backup). Perfis 0–16 "
                "usam a linha com o próprio número por padrão; 17–24 reaproveitam "
                "linhas de perfis de mapa."
            ),
        )
        reindex_help.add_css_class("muted")
        reindex_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.reindex_profile_dropdown = Gtk.DropDown(
            model=Gtk.StringList.new(
                [
                    f"{profile.id:02d} — {profile.name}"
                    for profile in sorted(core.PROFILES, key=lambda item: item.id)
                ]
            )
        )
        self.reindex_profile_dropdown.set_size_request(300, -1)
        self.reindex_profile_dropdown.connect(
            "notify::selected", self.on_reindex_selection_changed
        )
        arrow_label = Gtk.Label(label="→", xalign=0.5)
        self.reindex_row_dropdown = Gtk.DropDown(
            model=Gtk.StringList.new(
                [
                    f"Linha {row} — {core.PROFILE_BY_ID[row].name}"
                    for row in range(core.ATLAS_ROWS)
                ]
            )
        )
        self.reindex_row_dropdown.set_size_request(300, -1)
        self.reindex_row_dropdown.connect(
            "notify::selected", self.on_reindex_selection_changed
        )
        self.reindex_apply_button = Gtk.Button(label="Aplicar")
        self.reindex_apply_button.connect("clicked", self.on_reindex_apply)
        self.reindex_reset_button = Gtk.Button(label="Restaurar padrão")
        self.reindex_reset_button.connect("clicked", self.on_reindex_reset)
        reindex_controls.append(self.reindex_profile_dropdown)
        reindex_controls.append(arrow_label)
        reindex_controls.append(self.reindex_row_dropdown)
        reindex_controls.append(self.reindex_apply_button)
        reindex_controls.append(self.reindex_reset_button)
        self.reindex_current_label = Gtk.Label(xalign=0, wrap=True)
        self.reindex_current_label.add_css_class("muted")
        reindex_card.append(reindex_title)
        reindex_card.append(reindex_help)
        reindex_card.append(reindex_controls)
        reindex_card.append(self.reindex_current_label)
        page.append(reindex_card)

        self._atlas_selected_row = 0
        self.refresh_atlas_page()
        return page

    def _installed_atlas_path(self) -> Path | None:
        """Atlas instalado no vkBasalt (None quando só existe o pacote interno)."""
        installed = core.default_texture_path()
        return installed if installed.is_file() else None

    def _atlas_row_title(self, row: int) -> str:
        return f"Linha {row} — {core.PROFILE_BY_ID[row].name}"

    def refresh_atlas_page(self) -> None:
        """Reconstrói a lista de 17 linhas com miniaturas e donos atuais."""
        if not hasattr(self, "atlas_rows_list"):
            return
        installed = self._installed_atlas_path()
        pixbuf = self.load_atlas_pixbuf()
        mapping = self.current_lut_row_map()
        if mapping is None:
            mapping = {
                profile_id: core.lut_row_for_profile(profile_id)
                for profile_id in range(len(core.PROFILES))
            }
        owners = atlas.row_owner_profiles(mapping)

        selected = getattr(self, "_atlas_selected_row", 0)
        while True:
            existing = self.atlas_rows_list.get_row_at_index(0)
            if existing is None:
                break
            self.atlas_rows_list.remove(existing)

        width = pixbuf.get_width() if pixbuf else 0
        height = pixbuf.get_height() if pixbuf else 0
        row_height = max(1, height // core.ATLAS_ROWS) if pixbuf else 0
        for row in range(core.ATLAS_ROWS):
            item = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
            item.set_margin_start(12)
            item.set_margin_end(12)
            item.set_margin_top(8)
            item.set_margin_bottom(8)
            picture = Gtk.Picture()
            picture.set_content_fit(Gtk.ContentFit.CONTAIN)
            picture.set_can_shrink(True)
            picture.set_size_request(300, 44)
            if pixbuf is not None:
                top = min(row * row_height, max(0, height - row_height))
                strip = pixbuf.new_subpixbuf(0, top, width, row_height)
                picture.set_paintable(Gdk.Texture.new_for_pixbuf(strip))
            item.append(picture)
            labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            labels.set_hexpand(True)
            name = Gtk.Label(
                label=self._atlas_row_title(row), xalign=0
            )
            name.add_css_class("section-title")
            used = ", ".join(f"{owner:02d}" for owner in owners[row]) or "—"
            detail = Gtk.Label(
                label=f"Usada pelos perfis: {used}", xalign=0
            )
            detail.add_css_class("muted")
            labels.append(name)
            labels.append(detail)
            item.append(labels)
            list_row = Gtk.ListBoxRow()
            list_row.set_name(str(row))
            list_row.set_child(item)
            self.atlas_rows_list.append(list_row)

        self.atlas_rows_list.select_row(self.atlas_rows_list.get_row_at_index(selected))
        for button in (self.atlas_override_button, self.atlas_restore_row_button):
            button.set_sensitive(installed is not None)
        self.atlas_restore_backup_button.set_sensitive(
            installed is not None and core.backup_path(installed).is_file()
        )
        if installed is not None:
            valid, message = core.validate_texture(installed)
            self.atlas_page_status.set_label(
                f"{installed} — {message} Selecione uma linha para substituir "
                "por um .cube ou restaurar a original do pacote."
            )
        else:
            self.atlas_page_status.set_label(
                "Atlas do pacote v1.8 em exibição (somente leitura). Clique em "
                "“Instalar/atualizar pacote MultiLUT v1.8” na aba Perfis para "
                "habilitar substituição e backup."
            )
        self.refresh_reindex_current()

    def on_atlas_row_selected(self, _listbox, row) -> None:
        if row is not None:
            self._atlas_selected_row = int(row.get_name())

    def _selected_atlas_row(self) -> int:
        selected = self.atlas_rows_list.get_selected_row()
        if selected is None:
            return 0
        return int(selected.get_name())

    def _after_atlas_change(self, message: str) -> None:
        """Invalida caches e atualiza todas as superfícies que mostram o atlas."""
        self._atlas_pixbuf = None
        self._atlas_pixbuf_source = None
        self.refresh_atlas_page()
        self.update_atlas_card(self.selected_profile)
        self.update_preview_card(self.selected_profile)
        self.refresh_shader_status()
        self.toast(message)

    def on_atlas_override_clicked(self, _button) -> None:
        installed = self._installed_atlas_path()
        if installed is None:
            self.toast(
                "Instale o pacote MultiLUT v1.8 antes de substituir linhas."
            )
            return
        if not atlas.DEPENDENCIES_AVAILABLE:
            self.toast(
                "Substituição por .cube requer numpy e Pillow "
                "(no Solus: sudo eopkg it numpy python-pillow)."
            )
            return
        dialog = Gtk.FileDialog()
        filters = Gio.ListStore.new(Gtk.FileFilter)
        cube_filter = Gtk.FileFilter()
        cube_filter.set_name("LUT 3D (.cube)")
        cube_filter.add_pattern("*.cube")
        filters.append(cube_filter)
        all_filter = Gtk.FileFilter()
        all_filter.set_name("Todos os arquivos")
        all_filter.add_pattern("*")
        filters.append(all_filter)
        dialog.set_filters(filters)
        dialog.open(self, None, self._atlas_cube_dialog_done)

    def _atlas_cube_dialog_done(self, dialog, result) -> None:
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return  # diálogo cancelado
        path = file.get_path() if file is not None else None
        if not path:
            return
        installed = self._installed_atlas_path()
        if installed is None:
            return
        try:
            info = atlas.override_row_with_cube(
                installed, self._selected_atlas_row(), path
            )
        except core.MultiLUTError as exc:
            self.toast(f"Falha ao substituir a linha: {exc}")
            return
        self._after_atlas_change(
            f"Linha {info['row']} substituída pela LUT “{Path(path).name}” "
            f"({info['cube_size']}³ reamostrada para 32³; backup gravado)."
        )

    def on_atlas_restore_row_clicked(self, _button) -> None:
        installed = self._installed_atlas_path()
        if installed is None:
            self.toast("Instale o pacote MultiLUT v1.8 antes de restaurar linhas.")
            return
        row = self._selected_atlas_row()
        try:
            atlas.restore_row_from_bundle(installed, row, BUNDLE_DIR)
        except core.MultiLUTError as exc:
            self.toast(f"Falha ao restaurar a linha: {exc}")
            return
        self._after_atlas_change(
            f"{self._atlas_row_title(row)} restaurada ao original do pacote."
        )

    def on_atlas_restore_backup_clicked(self, _button) -> None:
        installed = self._installed_atlas_path()
        if installed is None:
            self.toast("Nenhum atlas instalado para restaurar.")
            return
        try:
            backup = atlas.restore_atlas_backup(installed)
        except core.MultiLUTError as exc:
            self.toast(f"Falha ao restaurar o backup: {exc}")
            return
        self._after_atlas_change(f"Atlas restaurado do backup ({backup}).")

    def on_atlas_restore_bundle(self, _button) -> None:
        installed = self._installed_atlas_path()
        if installed is None:
            self.toast("Instale o pacote MultiLUT v1.8 antes de restaurar o atlas.")
            return
        try:
            bundle_image = atlas.load_atlas_image(
                BUNDLE_DIR / "Textures/MultiLut_Insurgency_Optimized.png"
            )
            atlas.save_atlas_atomic(bundle_image, installed)
        except core.MultiLUTError as exc:
            self.toast(f"Falha ao restaurar o atlas: {exc}")
            return
        self._after_atlas_change(
            "Atlas original do pacote v1.8 restaurado (o anterior ficou em .bak)."
        )

    def on_reindex_selection_changed(self, _dropdown, _param) -> None:
        self.refresh_reindex_current()

    def refresh_reindex_current(self) -> None:
        if not hasattr(self, "reindex_current_label"):
            return
        profile_id = self.reindex_profile_dropdown.get_selected()
        mapping = self.current_lut_row_map()
        if mapping is not None:
            row = mapping.get(profile_id, core.lut_row_for_profile(profile_id))
            self.reindex_current_label.set_label(
                f"Situação atual: perfil {profile_id:02d} usa a linha {row} "
                "do atlas."
            )
        else:
            self.reindex_current_label.set_label(
                "Mapeamento atual indisponível (shader não encontrado ou fora "
                "do padrão v1.8)."
            )

    def on_reindex_apply(self, _button) -> None:
        shader_path = Path(self.shader_path).expanduser()
        if not shader_path.is_file():
            self.toast(
                "Shader não encontrado; instale o pacote MultiLUT v1.8 antes "
                "de reindexar."
            )
            return
        profile_id = self.reindex_profile_dropdown.get_selected()
        row = self.reindex_row_dropdown.get_selected()
        try:
            info = atlas.reindex_profile(shader_path, profile_id, row)
        except core.MultiLUTError as exc:
            self.toast(f"Falha na reindexação: {exc}")
            return
        if not info["changed"]:
            self.toast(f"Perfil {profile_id:02d} já usa a linha {row}.")
            return
        self._after_atlas_change(
            f"Perfil {profile_id:02d} reindexado: linha "
            f"{info['previous_row']} → {row} (backup gravado)."
        )

    def on_reindex_reset(self, _button) -> None:
        shader_path = Path(self.shader_path).expanduser()
        if not shader_path.is_file():
            self.toast("Shader não encontrado; nada a restaurar.")
            return
        try:
            info = atlas.reset_lut_row_map(shader_path)
        except core.MultiLUTError as exc:
            self.toast(f"Falha ao restaurar o mapeamento: {exc}")
            return
        if not info["changed"]:
            self.toast("O mapeamento já está no padrão do shader v1.8.")
            return
        self._after_atlas_change(
            "Mapeamento perfil → linha restaurado ao padrão do shader v1.8."
        )

    # --------------------------------------------- pré-visualização (simulação)
    def current_lut_row_map(self) -> dict[int, int] | None:
        """Mapeamento perfil -> linha do shader instalado (None se ilegível)."""
        try:
            text = Path(self.shader_path).expanduser().read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None
        try:
            return atlas.parse_lut_row_map(text)
        except core.MultiLUTError:
            return None

    def _game_resolution_from_config(self) -> tuple[int, int]:
        """Resolução de render do jogo no config.json (padrão 1366x768)."""
        try:
            return preview.parse_game_resolution(
                (int(self.config.get("game_width")), int(self.config.get("game_height")))
            )
        except (TypeError, ValueError, preview.PreviewError):
            return preview.DEFAULT_GAME_RESOLUTION

    def _build_resolution_choices(self) -> list[str]:
        """Resoluções comuns + a configurada (quando fora da lista)."""
        choices = [
            "1280x720",
            "1366x768",
            "1440x900",
            "1600x900",
            "1920x1080",
            "2560x1440",
            "3440x1440",
            "3840x2160",
        ]
        current = "x".join(str(v) for v in self.game_resolution)
        if current not in choices:
            choices.append(current)
        return choices

    def on_preview_resolution_changed(self, dropdown, _param) -> None:
        """Troca da resolução do jogo usada para escalar o raio local."""
        index = dropdown.get_selected()
        if not (0 <= index < len(self.resolution_choices)):
            return
        try:
            self.game_resolution = preview.parse_game_resolution(
                self.resolution_choices[index]
            )
        except preview.PreviewError:
            return
        self.config["game_width"], self.config["game_height"] = self.game_resolution
        core.save_config(self.config)
        self._schedule_preview()

    def _build_preview_map_choices(self) -> list[tuple[str, str]]:
        """[(slug, título)] das fotos de mapa disponíveis, em ordem alfabética."""
        choices: list[tuple[str, str]] = []
        seen: set[str] = set()
        for profile in core.profiles_alphabetical():
            slug = core.map_image_slug(profile)
            if slug is None or slug in seen:
                continue
            if (MAP_IMAGE_DIR / f"{slug}.jpg").is_file():
                seen.add(slug)
                choices.append((slug, profile.name))
        return choices

    def on_preview_map_changed(self, dropdown, _param) -> None:
        """Troca da foto-base da simulação no dropdown."""
        index = dropdown.get_selected()
        if not self._preview_programmatic and 0 <= index < len(
            self._preview_map_choices
        ):
            self.config["preview_map"] = self._preview_map_choices[index][0]
            core.save_config(self.config)
        self._schedule_preview()

    def update_preview_card(self, profile: core.Profile | None = None) -> None:
        """Agenda a simulação do perfil; perfis de mapa usam a própria foto."""
        profile = profile or self.selected_profile
        if not self._preview_map_choices:
            self.preview_picture.set_visible(False)
            self.preview_status.set_label(
                "Pré-visualização indisponível: fotos dos mapas não encontradas."
            )
            return
        own_slug = core.map_image_slug(profile)
        target = own_slug or str(self.config.get("preview_map") or "")
        index = next(
            (
                i
                for i, (candidate, _) in enumerate(self._preview_map_choices)
                if candidate == target
            ),
            0,
        )
        if index != self.preview_dropdown.get_selected():
            self._preview_programmatic = True
            self.preview_dropdown.set_selected(index)  # já agenda a simulação
            self._preview_programmatic = False
        else:
            self._schedule_preview()

    def _schedule_preview(self) -> None:
        """Valida insumos e roda a simulação em uma thread de fundo."""
        if not hasattr(self, "preview_picture"):
            return
        self._preview_generation += 1
        generation = self._preview_generation
        profile = self.selected_profile
        if not preview.DEPENDENCIES_AVAILABLE:
            self.preview_picture.set_visible(False)
            self.preview_status.set_label(
                "Simulação indisponível: instale numpy e Pillow "
                "(no Solus: sudo eopkg it numpy python-pillow) "
                "e reabra o aplicativo."
            )
            return
        atlas_path = self.atlas_source_path()
        valid, message = core.validate_texture(atlas_path)
        if not valid:
            self.preview_picture.set_visible(False)
            self.preview_status.set_label(f"Pré-visualização indisponível: {message}")
            return
        index = self.preview_dropdown.get_selected()
        if not (0 <= index < len(self._preview_map_choices)):
            return
        slug = self._preview_map_choices[index][0]
        source = MAP_IMAGE_DIR / f"{slug}.jpg"
        if not source.is_file():
            self.preview_picture.set_visible(False)
            self.preview_status.set_label(f"Foto do mapa não encontrada: {source.name}")
            return
        shader_path = self.shader_path
        if not Path(shader_path).expanduser().is_file():
            shader_path = BUNDLE_DIR / "Shaders/MultiLUT_Insurgency_Optimized.fx"
        mapping = self.current_lut_row_map()
        lut_row = (
            mapping.get(profile.id) if mapping else core.lut_row_for_profile(profile.id)
        )
        self.preview_picture.set_visible(True)
        self.preview_status.set_label("Simulando o pipeline do shader…")
        worker = threading.Thread(
            target=self._preview_worker,
            args=(
                generation,
                profile.id,
                profile.name,
                source,
                atlas_path,
                shader_path,
                slug,
                self.game_resolution,
                lut_row,
            ),
            daemon=True,
        )
        worker.start()

    def _preview_worker(
        self,
        generation: int,
        profile_id: int,
        profile_name: str,
        source: Path,
        atlas_path: Path,
        shader_path: Path,
        slug: str,
        game_resolution: tuple[int, int],
        lut_row: int | None,
    ) -> None:
        """Thread da simulação; o resultado volta pela fila principal do GLib."""
        try:
            result = preview.render_preview(
                profile_id,
                source,
                atlas_path,
                shader_path,
                max_width=768,
                game_resolution=game_resolution,
                lut_row=lut_row,
            )
            composed = preview.compose_side_by_side(
                result["original"], result["simulated"]
            )
            resolved_w, resolved_h = result["game_resolution"]
            payload = {
                "png": preview.png_bytes(composed),
                "status": (
                    f"Perfil {profile_id:02d} — {profile_name} sobre “{slug}”, "
                    f"simulado em {result['elapsed_ms']:.0f} ms. Aproximação em "
                    "CPU do pipeline completo do shader; raio do contraste local "
                    f"escalado pela resolução do jogo ({resolved_w}x{resolved_h})."
                ),
            }
        except preview.PreviewError as exc:
            payload = {"error": str(exc)}
        except Exception as exc:  # nunca derrubar o app por causa da prévia
            payload = {"error": f"Falha inesperada na simulação: {exc}"}
        GLib.idle_add(self._preview_done, generation, payload)

    def _preview_done(self, generation: int, payload: dict) -> bool:
        if generation != self._preview_generation:
            return False  # obsoleto: outro perfil foi selecionado enquanto rodava
        if "error" in payload:
            self.preview_picture.set_visible(False)
            self.preview_status.set_label(payload["error"])
            return False
        texture = self._texture_from_png_bytes(payload["png"])
        if texture is not None:
            self.preview_picture.set_paintable(texture)
            self.preview_picture.set_visible(True)
        self.preview_status.set_label(payload["status"])
        return False

    def _texture_from_png_bytes(self, data: bytes) -> Gdk.Texture | None:
        try:
            return Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
        except (AttributeError, GLib.Error, TypeError):
            pass
        try:  # GTK antigo sem new_from_bytes: usa arquivo no cache
            cache_dir = Path.home() / ".cache/multilut-controller"
            cache_dir.mkdir(parents=True, exist_ok=True)
            path = cache_dir / "preview.png"
            path.write_bytes(data)
            return Gdk.Texture.new_from_filename(str(path))
        except (GLib.Error, OSError, AttributeError):
            return None

    def copy_to_clipboard(self, text: str, confirmation: str) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            self.toast("Não foi possível acessar a área de transferência.")
            return
        display.get_clipboard().set_text(text)
        self.toast(confirmation)

    def on_copy_shader_path(self, _button) -> None:
        self.copy_to_clipboard(str(self.shader_path), "Caminho do shader copiado.")

    def on_about(self, _button) -> None:
        about = Adw.AboutWindow(transient_for=self)
        about.set_application_name("MultiLUT Controller")
        about.set_application_icon("com.felipesantiago.MultiLUTController")
        about.set_version(core.APP_VERSION)
        about.set_developer_name("Felipe Santiago")
        about.set_website(core.RELEASES_API_URL.replace("/releases/latest", ""))
        about.set_comments(
            "Controlador de perfis LUT (vkBasalt) para o Insurgency (2014)."
        )
        about.set_license_type(Gtk.License.MIT_X11)
        about.present()

    def _update_detail_photo(self, profile: core.Profile) -> None:
        """Mostra a foto oficial do mapa no painel de detalhes, quando houver."""
        slug = core.map_image_slug(profile)
        path = MAP_IMAGE_DIR / f"{slug}.jpg" if slug else None
        if path is not None and path.is_file():
            try:
                self.detail_photo.set_paintable(Gdk.Texture.new_from_filename(str(path)))
                self.detail_photo_frame.set_visible(True)
            except (GLib.Error, AttributeError):
                self.detail_photo_frame.set_visible(False)
        else:
            self.detail_photo_frame.set_visible(False)

    def select_profile_id(self, profile_id: int) -> None:
        # A lista aparece em seções alfabéticas: localize pelo id do perfil,
        # não pela posição da linha, e ignore os cabeçalhos de seção.
        self._programmatic_selection = True
        try:
            row = self.profile_list.get_first_child()
            while row is not None:
                profile = getattr(row, "profile", None)
                if profile is not None and profile.id == profile_id:
                    self.profile_list.select_row(row)
                    self.update_detail(profile)
                    break
                row = row.get_next_sibling()
        finally:
            self._programmatic_selection = False

    def on_profile_selected(self, _listbox, row) -> None:
        profile = getattr(row, "profile", None) if row is not None else None
        if profile is None:  # cabeçalho de seção não é selecionável
            return
        self.update_detail(profile)
        if self.auto_switch.get_active() and not self._programmatic_selection:
            self.apply_selected_profile()

    def on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        query = entry.get_text().casefold().strip()
        # Marca cada perfil como visível ou não; um cabeçalho de seção só
        # aparece se algum perfil da seção dele passar na busca.
        rows: list[Gtk.ListBoxRow] = []
        row = self.profile_list.get_first_child()
        while row is not None:
            rows.append(row)
            row = row.get_next_sibling()
        visible: dict[Gtk.ListBoxRow, bool] = {}
        header: Gtk.ListBoxRow | None = None
        section_has_match = False
        visible_profiles = 0
        total_profiles = 0
        for row in rows:
            profile = getattr(row, "profile", None)
            if profile is None:  # cabeçalho: fecha a seção anterior
                if header is not None:
                    visible[header] = section_has_match
                header = row
                section_has_match = False
                continue
            total_profiles += 1
            haystack = " ".join(
                (profile.name, profile.category, profile.summary, profile.best_for)
            ).casefold()
            shows = not query or query in haystack
            if not shows:
                # Busca pelo número do perfil: "07", "7", "14"...
                shows = query == f"{profile.id:02d}" or (
                    query.isdigit() and int(query) == profile.id
                )
            visible[row] = shows
            if shows:
                visible_profiles += 1
                section_has_match = True
        if header is not None:
            visible[header] = section_has_match
        for row, shows in visible.items():
            row.set_visible(shows)
        if query:
            self.search_counter.set_label(f"{visible_profiles} de {total_profiles} perfis")
        else:
            self.search_counter.set_label(f"{total_profiles} perfis")

    def on_auto_changed(self, switch, _param) -> None:
        self.config["auto_apply"] = switch.get_active()
        core.save_config(self.config)

    def on_notify_changed(self, switch, _param) -> None:
        self.config["notify_changes"] = switch.get_active()
        core.save_config(self.config)
        if switch.get_active():
            self.toast("Notificações do desktop ativadas para trocas automáticas.")

    def on_auto_launch_changed(self, switch, _param) -> None:
        self.config["auto_apply_on_launch"] = switch.get_active()
        core.save_config(self.config)

    def on_auto_map_changed(self, switch, _param) -> None:
        self.config["auto_map_switch"] = switch.get_active()
        core.save_config(self.config)
        if switch.get_active():
            self._ensure_console_monitor()
            if core.find_console_log() is None:
                self.toast(
                    "console.log não encontrado; adicione -condebug à opção "
                    "do jogo (a página Sistema corrige isso).",
                    6,
                )
            else:
                self.toast("Piloto automático por mapa ativado.")

    def on_hotkey_changed(self, switch, _param) -> None:
        self.config["global_shortcut"] = switch.get_active()
        core.save_config(self.config)
        if switch.get_active():
            self._register_global_shortcut()
        else:
            self._close_global_session()

    # ------------------------------------------------------------ piloto automático por mapa
    def start_console_monitor(self) -> None:
        """Arma o monitor do console.log quando ele existir."""
        self._ensure_console_monitor()

    def _ensure_console_monitor(self) -> None:
        if self._console_monitor is not None:
            return
        console = core.find_console_log()
        if console is None:
            return
        try:
            file = Gio.File.new_for_path(str(console))
            monitor = file.monitor_file(Gio.FileMonitorFlags.NONE, None)
            monitor.connect("changed", self._on_console_changed)
            self._console_monitor = monitor
            self._console_path = console
            tail = core.ConsoleTail()
            try:
                tail.offset = console.stat().st_size  # ignora conteúdo antigo
            except OSError:
                tail.offset = 0
            self._console_tail = tail
        except GLib.Error:
            self._console_monitor = None

    def _on_console_changed(self, _monitor, _file, _other, event_type) -> None:
        if event_type in (
            Gio.FileMonitorEvent.DELETED,
            Gio.FileMonitorEvent.MOVED_OUT,
        ):
            # o jogo recria o console.log a cada boot: rearma e zera o offset
            GLib.idle_add(self._rearm_console_monitor)
            return
        if event_type not in (
            Gio.FileMonitorEvent.CHANGES_DONE_HINT,
            Gio.FileMonitorEvent.CREATED,
            Gio.FileMonitorEvent.MOVED_IN,
            Gio.FileMonitorEvent.CHANGED,
        ):
            return
        if self._console_debounce_id is not None:
            GLib.source_remove(self._console_debounce_id)
        self._console_debounce_id = GLib.timeout_add(400, self._drain_console_log)

    def _rearm_console_monitor(self) -> bool:
        if self._console_monitor is not None:
            self._console_monitor.cancel()
            self._console_monitor = None
        self._console_path = None
        self._console_tail = None
        self._ensure_console_monitor()
        return GLib.SOURCE_REMOVE

    def _drain_console_log(self) -> bool:
        """Lê as linhas novas do console.log e reage ao último mapa carregado."""
        self._console_debounce_id = None
        tail = self._console_tail
        path = self._console_path
        if tail is None or path is None:
            return GLib.SOURCE_REMOVE
        try:
            size = path.stat().st_size
            if size < tail.offset:
                tail.reset()  # truncado: o jogo recriou o arquivo
            with path.open("rb") as stream:
                stream.seek(tail.offset)
                data = stream.read(262144)
            lines = tail.feed(data)
        except OSError:
            return GLib.SOURCE_REMOVE
        latest = None
        for token in tail.map_tokens(lines):
            latest = token
        if latest:
            profile = core.match_map_profile(latest)
            if profile is not None:
                self._on_map_detected(profile, latest)
        return GLib.SOURCE_REMOVE

    def _on_map_detected(self, profile: core.Profile, token: str) -> None:
        """Mapa carregado no jogo: aplica o perfil dele se o piloto está ligado."""
        if not self.config.get("auto_map_switch", False):
            return
        if not self.shader_valid:
            return
        try:
            active = core.read_active_profile(self.shader_path)
        except core.MultiLUTError:
            return
        if active == profile.id:
            return
        try:
            core.set_active_profile(self.shader_path, profile.id)
        except (OSError, UnicodeError, core.MultiLUTError) as exc:
            self.toast(f"Piloto automático falhou: {exc}", 6)
            return
        self.config["shader_path"] = str(self.shader_path)
        self.config["last_profile"] = profile.id
        core.save_config(self.config)
        self.select_profile_id(profile.id)
        self.refresh_shader_status()
        self._record_history("auto-map", profile, detail=token)
        self.toast(f"Piloto automático: {token} → {profile.name}", 5)

    # ------------------------------------------------------------ atalho global (portal)
    def _register_global_shortcut(self) -> None:
        if self._hotkey_thread is not None and self._hotkey_thread.is_alive():
            return
        self._hotkey_thread = threading.Thread(
            target=self._global_shortcut_setup, daemon=True
        )
        self._hotkey_thread.start()

    def _global_shortcut_setup(self) -> None:
        """Diálogo completo do portal GlobalShortcuts, em thread própria."""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self._hotkey_bus = bus
            sender = bus.get_unique_name().lstrip(":").replace(".", "_")
            token = f"multilut{int(time.time() * 1000) % 100000000}"
            request_path = (
                f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
            )
            done = threading.Event()
            outcome: dict = {}

            def on_response(_conn, _sender, _path, _iface, _signal, params):
                try:
                    response = int(params[0])
                    raw = params[1] if len(params) > 1 else None
                    values = (
                        raw.unpack() if hasattr(raw, "unpack") else dict(raw or {})
                    )
                except (IndexError, TypeError, ValueError):
                    response, values = 1, {}
                outcome["response"] = response
                outcome["values"] = values if isinstance(values, dict) else {}
                done.set()

            sid = bus.signal_subscribe(
                None,
                "org.freedesktop.portal.Request",
                "Response",
                request_path,
                None,
                Gio.DBusSignalFlags.NONE,
                on_response,
            )
            self._hotkey_signal_ids.append(sid)

            create_reply = bus.call_sync(
                PORTAL_BUS_NAME,
                PORTAL_OBJECT_PATH,
                GLOBAL_SHORTCUTS_IFACE,
                "CreateSession",
                GLib.Variant(
                    "(a{sv})",
                    (
                        {
                            "handle_token": GLib.Variant("s", token),
                            "session_handle_token": GLib.Variant(
                                "s", "multilut-controller"
                            ),
                        },
                    ),
                ),
                GLib.VariantType("(o)"),
                Gio.DBusCallFlags.NONE,
                8000,
                None,
            )
            create_reply.unpack()  # valida a resposta do portal
            if not done.wait(10):
                raise GLib.Error(
                    "o portal de atalhos globais não respondeu"
                )
            if outcome.get("response") != 0:
                raise GLib.Error("sessão do portal recusada")
            session_handle = outcome["values"].get("session_handle")
            if not session_handle:
                raise GLib.Error("portal não devolveu a sessão")
            self._hotkey_session = str(session_handle)

            sid = bus.signal_subscribe(
                PORTAL_BUS_NAME,
                GLOBAL_SHORTCUTS_IFACE,
                "Activated",
                None,
                None,
                Gio.DBusSignalFlags.NONE,
                self._on_portal_activated,
            )
            self._hotkey_signal_ids.append(sid)

            done.clear()
            outcome.clear()
            bus.call_sync(
                PORTAL_BUS_NAME,
                PORTAL_OBJECT_PATH,
                GLOBAL_SHORTCUTS_IFACE,
                "BindShortcuts",
                GLib.Variant(
                    "(oa(sass)a{sv})",
                    (
                        self._hotkey_session,
                        [
                            (
                                HOTKEY_SHORTCUT_ID,
                                HOTKEY_PREFERRED,
                                "Aplicar o próximo perfil do MultiLUT",
                            )
                        ],
                        "",
                        {"handle_token": GLib.Variant("s", token)},
                    ),
                ),
                GLib.VariantType("(o)"),
                Gio.DBusCallFlags.NONE,
                60000,
                None,
            )
            # resposta do diálogo do GNOME (usuário confirma a tecla)
            if not done.wait(120):
                raise GLib.Error("o diálogo do atalho não foi concluído")
            if outcome.get("response") != 0:
                raise GLib.Error("atalho não confirmado")
            GLib.idle_add(
                self.toast,
                "Atalho global registrado. Use o atalho para aplicar o "
                "próximo perfil.",
                6,
            )
        except (GLib.Error, OSError, ValueError) as exc:
            self._close_global_session()
            message = str(exc.message) if hasattr(exc, "message") else str(exc)
            GLib.idle_add(self._disable_hotkey_switch, message)

    def _on_portal_activated(self, _conn, _sender, path, _iface, _signal, params):
        session = self._hotkey_session
        if session is not None and path != session:
            return
        if not params or len(params) < 2:
            return
        try:
            shortcut_id = str(params[1])
        except (IndexError, TypeError):
            return
        if shortcut_id != HOTKEY_SHORTCUT_ID:
            return
        GLib.idle_add(self._apply_next_profile_hotkey)

    def _apply_next_profile_hotkey(self) -> bool:
        """Aplica o próximo perfil (0–24 ciclando) vindo do atalho global."""
        if self._hotkey_applying:
            return GLib.SOURCE_REMOVE
        self._hotkey_applying = True
        try:
            if not self.shader_valid:
                self.toast("Atalho global: shader inválido.", 5)
                return GLib.SOURCE_REMOVE
            try:
                active = core.read_active_profile(self.shader_path)
                target = core.PROFILE_BY_ID[core.next_profile_id(active)]
                core.set_active_profile(self.shader_path, target.id)
            except (OSError, UnicodeError, core.MultiLUTError) as exc:
                self.toast(f"Atalho global falhou: {exc}", 6)
                return GLib.SOURCE_REMOVE
            self.config["shader_path"] = str(self.shader_path)
            self.config["last_profile"] = target.id
            core.save_config(self.config)
            self.select_profile_id(target.id)
            self.refresh_shader_status()
            self._record_history("hotkey", target)
            self.toast(f"{target.name} aplicado pelo atalho global.")
        finally:
            self._hotkey_applying = False
        return GLib.SOURCE_REMOVE

    def _disable_hotkey_switch(self, reason: str) -> bool:
        self.toast(f"Atalho global indisponível: {reason}", 7)
        switch = getattr(self, "hotkey_switch", None)
        if switch is not None:
            switch.set_active(False)
        return GLib.SOURCE_REMOVE

    def _close_global_session(self) -> None:
        session = self._hotkey_session
        bus = self._hotkey_bus
        if session is not None and bus is not None:
            try:
                bus.call_sync(
                    PORTAL_BUS_NAME,
                    session,
                    "org.freedesktop.portal.Session",
                    "Close",
                    None,
                    None,
                    Gio.DBusCallFlags.NONE,
                    3000,
                    None,
                )
            except GLib.Error:
                pass
        for signal_id in self._hotkey_signal_ids:
            try:
                bus.signal_unsubscribe(signal_id)
            except (GLib.Error, TypeError, AttributeError):
                pass
        self._hotkey_signal_ids = []
        self._hotkey_session = None
        self._hotkey_bus = None

    # ------------------------------------------------------------ histórico e notificações
    def _record_history(self, origin: str, profile: core.Profile, detail: str = "") -> None:
        """Registra a troca no histórico local e dispara a notificação configurada."""
        core.append_history(
            {
                "profile_id": profile.id,
                "profile_name": profile.name,
                "origin": origin,
                "detail": detail,
                "shader": str(self.shader_path),
            }
        )
        self.refresh_history()
        self._notify_profile_change(profile, origin)

    def _notify_profile_change(self, profile: core.Profile, origin: str) -> None:
        """Notificação do desktop para trocas que não vieram da própria janela."""
        if not self.config.get("notify_changes", False):
            return
        if origin == "manual":
            return  # o toast da janela já basta para trocas manuais
        origin_text = ORIGIN_LABELS.get(origin, origin)
        notification = Gio.Notification.new("MultiLUT Controller")
        notification.set_body(
            f"{origin_text}: perfil ativo {profile.id:02d} — {profile.name}"
        )
        self.send_notification(None, notification)

    def build_history_page(self) -> Gtk.Widget:
        """Página do ViewStack com os registros locais de trocas de perfil."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.set_margin_start(26)
        page.set_margin_end(26)
        page.set_margin_top(20)
        page.set_margin_bottom(20)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        title = Gtk.Label(label="Histórico de sessões", xalign=0)
        title.add_css_class("hero-title")
        title.set_hexpand(True)
        clear_button = Gtk.Button(label="Limpar histórico")
        clear_button.connect("clicked", self.on_clear_history)
        header.append(title)
        header.append(clear_button)
        page.append(header)
        hint = Gtk.Label(
            label=(
                "Registro local dos perfis aplicados, incluindo a origem da troca "
                "(manual, piloto automático por mapa, início do jogo ou CLI)."
            ),
            xalign=0,
            wrap=True,
        )
        hint.add_css_class("muted")
        page.append(hint)
        self.history_list = Gtk.ListBox()
        self.history_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.history_list.add_css_class("card")
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(self.history_list)
        page.append(scroller)
        self.refresh_history()
        return page

    def refresh_history(self) -> None:
        """Repopula a lista do histórico; chamado após cada troca registrada."""
        history_list = getattr(self, "history_list", None)
        if history_list is None:
            return
        child = history_list.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            history_list.remove(child)
            child = next_child
        entries = core.read_history(limit=120)
        if not entries:
            empty = Gtk.ListBoxRow()
            empty.set_selectable(False)
            empty.set_activatable(False)
            label = Gtk.Label(
                label="Nenhuma troca registrada ainda.", xalign=0
            )
            label.set_margin_top(14)
            label.set_margin_bottom(14)
            label.set_margin_start(16)
            label.add_css_class("muted")
            empty.set_child(label)
            history_list.append(empty)
            return
        for entry in reversed(entries):
            history_list.append(self._history_row(entry))

    def _history_row(self, entry: dict) -> Gtk.ListBoxRow:
        ts_text = "—"
        raw_ts = entry.get("ts")
        if isinstance(raw_ts, str) and raw_ts:
            try:
                moment = datetime.fromisoformat(raw_ts).astimezone()
                ts_text = moment.strftime("%d/%m %H:%M")
            except ValueError:
                ts_text = raw_ts[:19].replace("T", " ")
        profile_id = entry.get("profile_id")
        profile_name = str(entry.get("profile_name") or "Perfil")
        origin = str(entry.get("origin") or "manual")
        origin_text = ORIGIN_LABELS.get(origin, origin)
        detail = str(entry.get("detail") or "")
        text = f"{ts_text} · {profile_id:02d} — {profile_name} · {origin_text}"
        if detail:
            text += f" ({detail})"
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        label = Gtk.Label(label=text, xalign=0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_margin_top(8)
        label.set_margin_bottom(8)
        label.set_margin_start(14)
        label.set_margin_end(14)
        if origin != "manual":
            label.add_css_class("muted")
        row.set_child(label)
        return row

    def on_clear_history(self, _button) -> None:
        core.clear_history()
        self.refresh_history()
        self.toast("Histórico local apagado.")

    # ------------------------------------------------------------ página Sistema
    STATE_ICONS = {
        "ok": "emblem-ok-symbolic",
        "warn": "dialog-warning-symbolic",
        "fail": "dialog-error-symbolic",
        "info": "dialog-information-symbolic",
    }
    STATE_CLASSES = {
        "ok": "success",
        "warn": "warning",
        "fail": "warning",
        "info": "muted",
    }

    def build_system_page(self) -> Gtk.Widget:
        """Página com diagnóstico, instalações Steam e backup do aplicativo."""
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.set_margin_start(26)
        page.set_margin_end(26)
        page.set_margin_top(20)
        page.set_margin_bottom(20)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        title = Gtk.Label(label="Sistema", xalign=0)
        title.add_css_class("hero-title")
        title.set_hexpand(True)
        recheck_button = Gtk.Button(label="Reverificar")
        recheck_button.connect("clicked", self.on_recheck_system)
        header.append(title)
        header.append(recheck_button)
        page.append(header)

        self.system_checks_list = Gtk.ListBox()
        self.system_checks_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.system_checks_list.add_css_class("card")
        checks_scroller = Gtk.ScrolledWindow()
        checks_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        checks_scroller.set_child(self.system_checks_list)
        checks_scroller.set_vexpand(True)
        page.append(checks_scroller)

        install_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        install_title = Gtk.Label(label="Instalação do jogo", xalign=0)
        install_title.set_hexpand(True)
        self.install_dropdown = Gtk.DropDown()
        self.install_dropdown.set_size_request(420, -1)
        self.install_dropdown.connect("notify::selected", self.on_install_selected)
        install_box.append(install_title)
        install_box.append(self.install_dropdown)
        page.append(install_box)

        backup_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        backup_title = Gtk.Label(
            label="Backup do aplicativo (configurações e histórico)", xalign=0
        )
        backup_title.set_hexpand(True)
        export_button = Gtk.Button(label="Exportar…")
        export_button.connect("clicked", self.on_export_backup)
        import_button = Gtk.Button(label="Importar…")
        import_button.connect("clicked", self.on_import_backup)
        backup_box.append(backup_title)
        backup_box.append(export_button)
        backup_box.append(import_button)
        page.append(backup_box)

        update_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.update_label = Gtk.Label(
            label=f"MultiLUT Controller v{core.APP_VERSION}", xalign=0
        )
        self.update_label.set_hexpand(True)
        update_button = Gtk.Button(label="Verificar atualizações agora")
        update_button.connect("clicked", self.on_check_updates_clicked)
        update_box.append(self.update_label)
        update_box.append(update_button)
        page.append(update_box)

        self.refresh_system_page()
        return page

    def on_visible_page_changed(self, stack, _param) -> None:
        name = stack.get_visible_child_name()
        if name == "history":
            self.refresh_history()
        elif name == "system":
            self.refresh_system_page()

    def _diagnostic_row(self, item: dict) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(14)
        box.set_margin_end(14)
        state = str(item.get("state") or "info")
        icon = Gtk.Image.new_from_icon_name(self.STATE_ICONS.get(state, "dialog-information-symbolic"))
        icon.add_css_class(self.STATE_CLASSES.get(state, "muted"))
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        title = Gtk.Label(label=str(item.get("title") or ""), xalign=0)
        title.set_wrap(True)
        detail = Gtk.Label(label=str(item.get("detail") or ""), xalign=0)
        detail.add_css_class("category-label")
        detail.set_wrap(True)
        text_box.append(title)
        text_box.append(detail)
        text_box.set_hexpand(True)
        box.append(icon)
        box.append(text_box)
        action = str(item.get("action") or "")
        if action and state in ("warn", "fail"):
            button = Gtk.Button(label=str(item.get("action_label") or "Corrigir"))
            button.add_css_class("pill")
            button.connect("clicked", getattr(self, action))
            box.append(button)
        row.set_child(box)
        return row

    def refresh_system_page(self) -> None:
        checks_list = getattr(self, "system_checks_list", None)
        if checks_list is None:
            return
        child = checks_list.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            checks_list.remove(child)
            child = next_child
        try:
            items = extra.diagnostic_report()
        except Exception as exc:  # diagnóstico nunca derruba a interface
            items = [{"title": "Diagnóstico", "state": "fail", "detail": str(exc)}]
        for item in items:
            if (
                item.get("title") == "Opção de inicialização do Steam"
                and item.get("state") in ("warn", "fail")
            ):
                item["action"] = "on_fix_launch_option"
            checks_list.append(self._diagnostic_row(item))
        self.refresh_install_dropdown()

    def on_fix_launch_option(self, _button) -> None:
        """Corrige a opção de inicialização do jogo (exige Steam fechado)."""
        if extra.steam_running():
            self.toast("Feche o Steam antes de corrigir a opção de inicialização.", 6)
            return
        try:
            summary = extra.ensure_launch_options()
        except (OSError, core.MultiLUTError) as exc:
            self.toast(f"Não foi possível corrigir: {exc}", 6)
            return
        if summary["changed"]:
            self.toast(f"Opção corrigida em {len(summary['changed'])} arquivo(s).", 6)
        else:
            self.toast("A opção de inicialização já estava correta.")
        self.refresh_system_page()

    def refresh_install_dropdown(self) -> None:
        """Oferece as instalações do jogo encontradas nas bibliotecas Steam."""
        dropdown = getattr(self, "install_dropdown", None)
        if dropdown is None:
            return
        roots = core.find_game_roots()
        self._install_paths = roots
        if len(roots) < 2:
            dropdown.set_visible(False)
            return
        dropdown.set_visible(True)
        labels = [str(root) for root in roots]
        model = Gtk.StringList.new(labels)
        dropdown.set_model(model)
        configured = self.config.get("game_dir")
        selected = 0
        for index, root in enumerate(roots):
            if str(root) == configured:
                selected = index
                break
        dropdown.set_selected(selected)

    def on_install_selected(self, dropdown, _param) -> None:
        index = dropdown.get_selected()
        paths = getattr(self, "_install_paths", [])
        if index is None or not isinstance(index, int) or index >= len(paths):
            return
        self.config["game_dir"] = str(paths[index])
        core.save_config(self.config)
        self.toast(f"Instalação selecionada: {paths[index]}")

    def on_recheck_system(self, _button) -> None:
        self.refresh_system_page()
        self.toast("Diagnóstico atualizado.")

    def on_check_updates_clicked(self, _button) -> None:
        self.toast("Procurando atualização…")
        threading.Thread(target=self._updates_thread, daemon=True).start()

    def on_export_backup(self, _button) -> None:
        chooser = Gtk.FileChooserNative(
            title="Exportar backup do MultiLUT Controller",
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE,
            accept_label="Exportar",
        )
        chooser.set_current_name("multilut-controller-backup.zip")
        chooser.connect("response", self.on_export_chosen)
        chooser.show()

    def on_export_chosen(self, chooser, response) -> None:
        if response != Gtk.ResponseType.ACCEPT:
            return
        chosen = chooser.get_file()
        if chosen is None or chosen.get_path() is None:
            self.toast("Selecione um destino válido.")
            return
        try:
            count = extra.export_config_bundle(Path(chosen.get_path()))
        except (OSError, core.MultiLUTError) as exc:
            self.toast(f"Export falhou: {exc}", 6)
            return
        self.toast(f"Backup exportado com {count} itens.")

    def on_import_backup(self, _button) -> None:
        chooser = Gtk.FileChooserNative(
            title="Importar backup do MultiLUT Controller",
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN,
            accept_label="Importar",
        )
        zip_filter = Gtk.FileFilter()
        zip_filter.set_name("Backup do MultiLUT (*.zip)")
        zip_filter.add_pattern("*.zip")
        chooser.add_filter(zip_filter)
        chooser.connect("response", self.on_import_chosen)
        chooser.show()

    def on_import_chosen(self, chooser, response) -> None:
        if response != Gtk.ResponseType.ACCEPT:
            return
        chosen = chooser.get_file()
        if chosen is None or chosen.get_path() is None:
            self.toast("Selecione um arquivo .zip válido.")
            return
        try:
            summary = extra.import_config_bundle(Path(chosen.get_path()))
        except (OSError, ValueError, core.MultiLUTError) as exc:
            self.toast(f"Import falhou: {exc}", 6)
            return
        self._apply_imported_config()
        self.toast(
            f"Backup restaurado ({summary['history_entries']} registros de histórico).",
            6,
        )

    def _apply_imported_config(self) -> None:
        """Recarrega a configuração importada e repinta toda a interface."""
        self.config = core.load_config()
        remembered = self.config.get("shader_path")
        candidates = core.find_shader_candidates()
        self.shader_path = Path(remembered).expanduser() if (
            isinstance(remembered, str) and remembered.strip()
        ) else (candidates[0] if candidates else core.default_shader_path())
        if hasattr(self, "auto_switch"):
            self.auto_switch.set_active(bool(self.config.get("auto_apply", False)))
        if hasattr(self, "notify_switch"):
            self.notify_switch.set_active(bool(self.config.get("notify_changes", False)))
        if hasattr(self, "auto_launch_switch"):
            self.auto_launch_switch.set_active(
                bool(self.config.get("auto_apply_on_launch", False))
            )
        if hasattr(self, "auto_map_switch"):
            self.auto_map_switch.set_active(
                bool(self.config.get("auto_map_switch", False))
            )
        if hasattr(self, "hotkey_switch"):
            self.hotkey_switch.set_active(
                bool(self.config.get("global_shortcut", False))
            )
        self.start_file_monitor()
        self.refresh_shader_status(select_active=True)
        self.refresh_history()
        self.refresh_system_page()

    # ------------------------------------------------------------ verificação de atualizações
    def _check_updates_once(self) -> bool:
        """Uma verificação discreta após a abertura; nunca bloqueia a UI."""
        if not self.config.get("check_updates", True):
            return GLib.SOURCE_REMOVE
        threading.Thread(target=self._updates_thread, daemon=True).start()
        return GLib.SOURCE_REMOVE

    def _updates_thread(self) -> None:
        release = core.fetch_latest_release()
        if release is not None:
            GLib.idle_add(self._announce_update, release)

    def _announce_update(self, release: dict) -> bool:
        if core.compare_versions(release["tag"], core.APP_VERSION):
            self.toast(
                f"Atualização disponível: {release['tag']} "
                f"(instalada v{core.APP_VERSION})",
                8,
            )
        return GLib.SOURCE_REMOVE

    def on_apply(self, _button) -> None:
        self.apply_selected_profile()

    def apply_selected_profile(self) -> bool:
        try:
            previous = core.set_active_profile(self.shader_path, self.selected_profile.id)
            self.config["shader_path"] = str(self.shader_path)
            self.config["last_profile"] = self.selected_profile.id
            core.save_config(self.config)
        except (OSError, UnicodeError, core.MultiLUTError) as exc:
            self.toast(str(exc), 6)
            self.refresh_shader_status()
            return False
        self.refresh_shader_status()
        self.start_file_monitor()
        if previous == self.selected_profile.id:
            self.toast(f"{self.selected_profile.name} já estava ativo.")
        else:
            self._record_history("manual", self.selected_profile)
            if core.is_game_running():
                self.toast(
                    f"{self.selected_profile.name} aplicado ao jogo em tempo real.",
                    4,
                )
            else:
                self.toast(f"Perfil {self.selected_profile.name} aplicado com segurança.")
        return True

    def on_apply_and_launch(self, _button) -> None:
        if core.is_game_running():
            self.toast("O Insurgency já está aberto. Use “Aplicar perfil” para trocar em tempo real.", 6)
            return
        if not self.apply_selected_profile():
            return
        try:
            core.launch_game()
        except core.MultiLUTError as exc:
            self.toast(str(exc), 6)
            return
        self.toast("Solicitação enviada ao Steam.")

    def on_restore(self, _button) -> None:
        try:
            profile_id = core.restore_backup(self.shader_path)
        except (OSError, UnicodeError, core.MultiLUTError) as exc:
            self.toast(str(exc), 6)
            return
        self.select_profile_id(profile_id)
        self.refresh_shader_status()
        self.start_file_monitor()
        self.toast(f"Backup restaurado: {core.PROFILE_BY_ID[profile_id].name}.")

    def on_choose_shader(self, _button) -> None:
        chooser = Gtk.FileChooserNative(
            title="Selecionar MultiLUT_Insurgency_Optimized.fx",
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN,
            accept_label="Selecionar",
            cancel_label="Cancelar",
        )
        shader_filter = Gtk.FileFilter()
        shader_filter.set_name("Shader ReShade FX (*.fx)")
        shader_filter.add_pattern("*.fx")
        chooser.add_filter(shader_filter)
        chooser.connect("response", self.on_shader_chosen)
        chooser.show()

    def on_shader_chosen(self, chooser, response) -> None:
        if response != Gtk.ResponseType.ACCEPT:
            return
        selected = chooser.get_file()
        if selected is None or selected.get_path() is None:
            self.toast("Selecione um arquivo local.")
            return
        self.shader_path = Path(selected.get_path())
        self.config["shader_path"] = str(self.shader_path)
        core.save_config(self.config)
        self.start_file_monitor()
        self.refresh_shader_status(select_active=True)

    def on_install_bundle(self, _button) -> None:
        try:
            shader, _texture = core.copy_bundle_assets(BUNDLE_DIR)
        except (OSError, core.MultiLUTError) as exc:
            self.toast(str(exc), 6)
            return
        self.shader_path = shader
        self.config["shader_path"] = str(shader)
        core.save_config(self.config)
        self.start_file_monitor()
        self.refresh_shader_status(select_active=True)
        self.toast("Shader e atlas v1.8 instalados. Arquivos anteriores foram preservados.", 6)

    def on_open_folder(self, _button) -> None:
        folder = self.shader_path.expanduser().parent
        if not folder.exists():
            self.toast("A pasta do shader ainda não existe.")
            return
        try:
            Gio.AppInfo.launch_default_for_uri(folder.as_uri(), None)
        except GLib.Error:
            self.toast("Não foi possível abrir a pasta.")

    def refresh_bundle_check(self) -> None:
        """Compara o shader instalado com o do pacote interno (v1.8)."""
        if not hasattr(self, "bundle_check_label"):
            return
        installed_hash = core.file_hash(self.shader_path)
        bundle_hash = core.file_hash(
            BUNDLE_DIR / "Shaders/MultiLUT_Insurgency_Optimized.fx"
        )
        if installed_hash is None:
            self.bundle_check_label.set_label(
                "Pacote interno v1.8 disponível para instalação."
            )
        elif installed_hash == bundle_hash:
            self.bundle_check_label.set_label(
                "Shader instalado é idêntico ao pacote interno v1.8."
            )
        else:
            self.bundle_check_label.set_label(
                "O shader instalado difere do pacote interno v1.8 — “Instalar/"
                "atualizar pacote” alinha a base (o perfil atual é preservado)."
            )

    def _install_shortcuts(self) -> None:
        """Atalhos da janela: Ctrl+F busca, Ctrl+Enter aplica, Ctrl+Z desfaz.

        Navegação por setas na lista e ativação com Enter já são nativas do
        Gtk.ListBox; aqui ficam só os atalhos globais da janela. Falha
        silenciosamente em versões de GTK sem Gtk.Shortcut.
        """
        if not hasattr(Gtk, "Shortcut"):
            return
        specs = (
            ("<Control>f", self._shortcut_focus_search),
            ("<Control>Return", self._shortcut_apply),
            ("<Control>z", self._shortcut_restore),
        )
        installed: list[str] = []
        for trigger, callback in specs:
            try:
                shortcut = Gtk.Shortcut()
                shortcut.set_trigger(Gtk.ShortcutTrigger.parse_string(trigger))
                shortcut.set_action(Gtk.CallbackAction.new(callback))
                self.add_shortcut(shortcut)
                installed.append(trigger)
            except GLib.Error:
                continue
        self._shortcut_triggers = installed

    def _shortcut_focus_search(self, _widget, _args) -> bool:
        """Ctrl+F: volta para a página Perfis e foca a busca."""
        page = self._page_profiles
        # add_titled devolve Adw.ViewStackPage; set_visible_child quer o widget
        if hasattr(page, "get_child"):
            page = page.get_child()
        self.view_stack.set_visible_child(page)
        self.search.grab_focus()
        return True

    def _shortcut_apply(self, _widget, _args) -> bool:
        """Ctrl+Enter: aplica o perfil selecionado (mesma ação do botão)."""
        if not self.shader_valid:
            self.toast("Shader inválido — nada para aplicar.", 5)
            return True
        self.apply_selected_profile()
        return True

    def _shortcut_restore(self, _widget, _args) -> bool:
        """Ctrl+Z: restaura o último backup (mesma ação do botão do cabeçalho)."""
        if not self.shader_valid:
            self.toast("Shader inválido — nada para restaurar.", 5)
            return True
        if not core.backup_path(self.shader_path).is_file():
            self.toast("Não há backup para restaurar.", 5)
            return True
        self.on_restore(None)
        return True

    def _update_active_markers(self, active_id: int | None) -> None:
        """Sincroniza o marcador “aplicado” de cada linha com o shader."""
        for profile_id, row in self._rows_by_id.items():
            try:
                row.set_active_flag(profile_id == active_id)
            except AttributeError:
                continue

    def refresh_shader_status(self, select_active: bool = False) -> None:
        self.path_label.set_label(str(self.shader_path))
        valid, message = core.validate_shader(self.shader_path)
        self.shader_valid = valid
        self.apply_button.set_sensitive(valid)
        self.restore_button.set_sensitive(core.backup_path(self.shader_path).is_file())
        # Keep the updater available even when an older compatible shader is
        # already installed; validation alone cannot identify its package age.
        self.install_button.set_visible(True)
        self.shader_validation.set_label(message)
        self.refresh_bundle_check()
        if valid:
            self.shader_validation.remove_css_class("warning")
            self.shader_validation.add_css_class("success")
            try:
                active = core.read_active_profile(self.shader_path)
            except core.MultiLUTError:
                self._update_active_markers(None)
                return
            self._update_active_markers(active)
            if (
                self._shader_was_valid
                and active != self.selected_profile.id
                and active in core.PROFILE_BY_ID
            ):
                external = core.PROFILE_BY_ID[active]
                self.toast(
                    f"Perfil alterado externamente: {external.id:02d} — {external.name}",
                    5,
                )
                self._notify_profile_change(external, "external")
            self.status_icon.set_from_icon_name("emblem-ok-symbolic")
            self.status_label.set_label(f"Ativo: {active:02d} — {core.PROFILE_BY_ID[active].name}")
            if select_active:
                self.select_profile_id(active)
            self._shader_was_valid = True
        else:
            self.shader_validation.remove_css_class("success")
            self.shader_validation.add_css_class("warning")
            self.status_icon.set_from_icon_name("dialog-warning-symbolic")
            self.status_label.set_label("Shader não localizado ou incompatível")
            self._shader_was_valid = False
            self._update_active_markers(None)

    def refresh_game_status(self) -> bool:
        running = core.is_game_running()
        was_running = self._game_was_running
        self._game_was_running = running
        self._ensure_console_monitor()
        if was_running is not None and running and not was_running:
            self._on_game_started()
        if running:
            self.game_label.set_label("Insurgency em execução — tempo real")
            self.apply_button.set_label("Aplicar agora")
            self.launch_button.set_sensitive(False)
            self.status_strip.add_css_class("status-live")
        else:
            self.game_label.set_label("Jogo fechado — pronto para aplicar")
            self.apply_button.set_label("Aplicar perfil")
            self.launch_button.set_sensitive(self.shader_valid)
            self.status_strip.remove_css_class("status-live")
        return GLib.SOURCE_CONTINUE

    def _on_game_started(self) -> None:
        """O jogo acabou de abrir: opcionalmente aplica o último perfil."""
        if not self.config.get("auto_apply_on_launch", False):
            return
        if not self.shader_valid:
            return
        last = self.config.get("last_profile")
        if not isinstance(last, int) or last not in core.PROFILE_BY_ID:
            return
        try:
            if core.read_active_profile(self.shader_path) == last:
                return
            core.set_active_profile(self.shader_path, last)
        except (OSError, UnicodeError, core.MultiLUTError) as exc:
            self.toast(f"Auto-aplicação no início do jogo falhou: {exc}", 6)
            return
        profile = core.PROFILE_BY_ID[last]
        self.select_profile_id(last)
        self._record_history("auto-launch", profile)
        self.toast(f"{profile.name} aplicado no início do jogo.", 5)

    def start_file_monitor(self) -> None:
        if self.file_monitor is not None:
            self.file_monitor.cancel()
            self.file_monitor = None
        if not self.shader_path.is_file():
            return
        try:
            file = Gio.File.new_for_path(str(self.shader_path))
            self.file_monitor = file.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self.file_monitor.connect("changed", self.on_file_changed)
        except GLib.Error:
            self.file_monitor = None

    def on_file_changed(self, _monitor, _file, _other, event_type) -> None:
        if event_type in (
            Gio.FileMonitorEvent.CHANGES_DONE_HINT,
            Gio.FileMonitorEvent.CREATED,
            Gio.FileMonitorEvent.MOVED_IN,
        ):
            GLib.idle_add(self.refresh_shader_status, True)


class MultiLUTApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=core.APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.connect("activate", self.on_activate)

    def on_activate(self, app) -> None:
        window = self.props.active_window
        if window is None:
            window = MultiLUTWindow(app)
        window.present()


def main() -> int:
    Adw.init()
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    return MultiLUTApplication().run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
