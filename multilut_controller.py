#!/usr/bin/env python3
"""Native GTK4/Libadwaita profile controller for MultiLUT + vkBasalt."""

from __future__ import annotations

from pathlib import Path
import sys

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_version("Gdk", "4.0")
    gi.require_version("Pango", "1.0")
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango
except (ImportError, ValueError) as exc:
    print(
        "MultiLUT Controller requer Python 3, PyGObject, GTK 4 e libadwaita.\n"
        "Instale as dependências pelo Centro de Programas do Solus e tente novamente.",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc

import multilut_core as core
import multilut_scopes as scopes


BASE_DIR = Path(__file__).resolve().parent
BUNDLE_DIR = BASE_DIR / "bundle"


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
        self.set_child(box)


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
        self.config["scopes"] = scopes.normalize_scope_config(self.config.get("scopes"))

        self.toast_overlay = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.view_stack = Adw.ViewStack()
        self.view_stack.set_vexpand(True)
        switcher = Adw.ViewSwitcher(stack=self.view_stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)

        self.restore_button = Gtk.Button.new_from_icon_name("edit-undo-symbolic")
        self.restore_button.set_tooltip_text("Restaurar último backup")
        self.restore_button.connect("clicked", self.on_restore)
        header.pack_end(self.restore_button)

        folder_button = Gtk.Button.new_from_icon_name("folder-open-symbolic")
        folder_button.set_tooltip_text("Abrir pasta do shader")
        folder_button.connect("clicked", self.on_open_folder)
        header.pack_end(folder_button)
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
        page_scopes = self.view_stack.add_titled(
            self.build_scopes_page(), "scopes", "Lunetas"
        )
        page_scopes.set_icon_name("zoom-in-symbolic")

        body.append(self.view_stack)

        toolbar.set_content(body)
        self.toast_overlay.set_child(toolbar)
        self.set_content(self.toast_overlay)

        self.refresh_shader_status(select_active=True)
        self.refresh_game_status()
        self.refresh_scopes_page()
        if window_state.get("maximized"):
            self.maximize()
        GLib.timeout_add_seconds(2, self.refresh_game_status)
        self.start_file_monitor()

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
        hint = Gtk.Label(label="Mapas e modos competitivos", xalign=0)
        hint.add_css_class("muted")
        heading.append(label)
        heading.append(hint)
        sidebar.append(heading)

        self.search = Gtk.SearchEntry(placeholder_text="Buscar perfil ou mapa")
        self.search.set_margin_start(12)
        self.search.set_margin_end(12)
        self.search.connect("search-changed", self.on_search_changed)
        sidebar.append(self.search)

        self.profile_list = Gtk.ListBox()
        self.profile_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.profile_list.connect("row-selected", self.on_profile_selected)
        for profile in core.profiles_alphabetical():
            self.profile_list.append(ProfileRow(profile))
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(self.profile_list)
        sidebar.append(scroller)

        auto_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        auto_box.set_margin_start(16)
        auto_box.set_margin_end(16)
        auto_box.set_margin_top(8)
        auto_box.set_margin_bottom(14)
        auto_label = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        auto_title = Gtk.Label(label="Aplicar ao selecionar", xalign=0)
        auto_hint = Gtk.Label(label="Salva o arquivo imediatamente", xalign=0)
        auto_hint.add_css_class("category-label")
        auto_label.append(auto_title)
        auto_label.append(auto_hint)
        auto_label.set_hexpand(True)
        self.auto_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.auto_switch.set_active(bool(self.config.get("auto_apply", False)))
        self.auto_switch.connect("notify::active", self.on_auto_changed)
        auto_box.append(auto_label)
        auto_box.append(self.auto_switch)
        sidebar.append(auto_box)
        return sidebar

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
        path_line.append(self.path_label)
        path_line.append(choose)
        self.shader_validation = Gtk.Label(xalign=0, wrap=True)
        self.shader_validation.add_css_class("muted")
        path_inner.append(path_title)
        path_inner.append(path_line)
        path_inner.append(self.shader_validation)
        path_card.append(path_inner)
        content.append(path_card)

        self.install_button = Gtk.Button(label="Instalar/atualizar pacote MultiLUT v1.8")
        self.install_button.connect("clicked", self.on_install_bundle)
        content.append(self.install_button)

        actions = self._wrap_box(10, homogeneous=True)
        self.apply_button = Gtk.Button(label="Aplicar perfil")
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

    # ------------------------------------------------------------ lunetas
    def build_scopes_page(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_start(26)
        content.set_margin_end(26)
        content.set_margin_top(24)
        content.set_margin_bottom(24)

        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        title = Gtk.Label(label="Lunetas ampliadas", xalign=0)
        title.add_css_class("hero-title")
        subtitle = Gtk.Label(
            label=(
                "Gera um theater nativo do Insurgency (scripts/theaters/multilut_zoom.theater) "
                "que aumenta a ampliação das lunetas selecionadas até 12x, com opções "
                "rápidas de 3x, 5x, 10x e 12x. O mecanismo é o oficial do jogo "
                "(mp_theater_override): nenhum arquivo original é alterado e desfazer é "
                "instantâneo."
            ),
            xalign=0,
            wrap=True,
        )
        subtitle.add_css_class("muted")
        hero.append(title)
        hero.append(subtitle)
        content.append(hero)

        fair = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        fair.add_css_class("card")
        fair_title = Gtk.Label(label="Jogo justo", xalign=0)
        fair_title.add_css_class("warning")
        fair_text = Gtk.Label(
            label=(
                "O theater vale quando você hospeda a partida (coop, prática ou servidor "
                "próprio). Em servidores de terceiros o theater é definido pelo servidor e "
                "o ajuste não se aplica — o que também evita vantagem indevida sobre outros "
                "jogadores. Respeite sempre as regras do servidor ou do torneio."
            ),
            xalign=0,
            wrap=True,
        )
        fair.append(fair_title)
        fair.append(fair_text)
        content.append(fair)

        install_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        install_card.add_css_class("card")
        install_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        install_inner.set_margin_start(18)
        install_inner.set_margin_end(18)
        install_inner.set_margin_top(16)
        install_inner.set_margin_bottom(16)
        install_caption = Gtk.Label(label="Instalação do Insurgency", xalign=0)
        install_caption.add_css_class("section-title")
        self.scopes_path_label = Gtk.Label(xalign=0, wrap=True)
        self.scopes_path_label.add_css_class("muted")
        manual_row = self._wrap_box(8)
        self.scopes_path_entry = Gtk.Entry(placeholder_text="Caminho manual, ex.: ~/.local/share/Steam/steamapps/common/insurgency2/insurgency")
        self.scopes_path_entry.set_hexpand(True)
        use_button = Gtk.Button(label="Usar este caminho")
        use_button.connect("clicked", self.on_scopes_use_manual_path)
        refresh_button = Gtk.Button(label="Procurar novamente")
        refresh_button.connect("clicked", self.on_scopes_refresh_clicked)
        manual_row.append(self.scopes_path_entry)
        manual_row.append(use_button)
        manual_row.append(refresh_button)
        install_inner.append(install_caption)
        install_inner.append(self.scopes_path_label)
        install_inner.append(manual_row)
        install_card.append(install_inner)
        content.append(install_card)

        settings_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        settings_card.add_css_class("card")
        settings_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        settings_inner.set_margin_start(18)
        settings_inner.set_margin_end(18)
        settings_inner.set_margin_top(16)
        settings_inner.set_margin_bottom(16)

        target_row = self._wrap_box(10)
        target_label = Gtk.Label(label="Ampliação máxima", xalign=0)
        target_label.set_size_request(190, -1)
        self.target_value_label = Gtk.Label(xalign=1)
        self.target_value_label.add_css_class("success")
        target_row.append(target_label)
        self.target_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, scopes.MIN_TARGET, scopes.MAX_TARGET, 0.5
        )
        self.target_scale.set_value(self.config["scopes"]["target"])
        self.target_scale.set_digits(1)
        self.target_scale.set_hexpand(True)
        self.target_scale.connect("value-changed", self.on_scopes_target_changed)
        target_row.append(self.target_scale)
        target_row.append(self.target_value_label)
        settings_inner.append(target_row)

        preset_row = self._wrap_box(10)
        preset_label = Gtk.Label(label="Opções rápidas", xalign=0)
        preset_label.set_size_request(190, -1)
        preset_row.append(preset_label)
        presets_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for mag in scopes.QUICK_TARGETS:
            button = Gtk.Button(label=f"{mag:g}x")
            button.add_css_class("pill")
            button.connect("clicked", self.on_scopes_preset, mag)
            presets_box.append(button)
        preset_row.append(presets_box)
        settings_inner.append(preset_row)

        optics_caption = Gtk.Label(label="Lunetas a ampliar", xalign=0)
        optics_caption.add_css_class("category-label")
        settings_inner.append(optics_caption)
        self.scope_checks: dict[str, Gtk.CheckButton] = {}
        for optic_id, label, _scope, _iron, _focus, mag in scopes.SCOPED_OPTICS:
            check = Gtk.CheckButton(label=f"{label} — hoje {mag:g}x")
            check.set_active(optic_id in self.config["scopes"]["optics"])
            settings_inner.append(check)
            self.scope_checks[optic_id] = check

        autoexec_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        autoexec_label = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        autoexec_title = Gtk.Label(
            label="Ativar sozinho ao iniciar o jogo", xalign=0, wrap=True
        )
        autoexec_hint = Gtk.Label(
            label="Grava mp_theater_override no autoexec.cfg do jogo",
            xalign=0,
            wrap=True,
        )
        autoexec_hint.add_css_class("category-label")
        autoexec_label.append(autoexec_title)
        autoexec_label.append(autoexec_hint)
        autoexec_label.set_hexpand(True)
        self.scopes_autoexec_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.scopes_autoexec_switch.set_active(bool(self.config["scopes"]["autoexec"]))
        autoexec_row.append(autoexec_label)
        autoexec_row.append(self.scopes_autoexec_switch)
        settings_inner.append(autoexec_row)

        launch_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        launch_label = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        launch_title = Gtk.Label(
            label="Ativar pela opção de inicialização do Steam", xalign=0, wrap=True
        )
        launch_hint = Gtk.Label(
            label="Grava +mp_theater_override multilut_zoom nas opções de "
            "inicialização do jogo (requer Steam fechado). Nos modos coop o "
            "playlist do jogo sobrepõe essa opção — a ativação principal é o "
            "listenserver.cfg, feita automaticamente ao Ativar",
            xalign=0,
            wrap=True,
        )
        launch_hint.add_css_class("category-label")
        launch_label.append(launch_title)
        launch_label.append(launch_hint)
        launch_label.set_hexpand(True)
        self.scopes_launch_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.scopes_launch_switch.set_active(
            bool(self.config["scopes"].get("launch_option", True))
        )
        launch_row.append(launch_label)
        launch_row.append(self.scopes_launch_switch)
        settings_inner.append(launch_row)

        server_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        server_label = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        server_title = Gtk.Label(
            label="Aplicar também nos theaters de servidores (client-side)",
            xalign=0,
            wrap=True,
        )
        server_hint = Gtk.Label(
            label="Alterna a cópia LOCAL dos theaters que os servidores baixam "
            "para o seu disco (backup automático .multilut.bak e reversível pelo "
            "Restaurar). Use SOMENTE com autorização dos admins. O efeito é só "
            "visual: dano e recuo continuam do servidor. Se um servidor "
            "atualizar o theater dele, clique em Ativar de novo",
            xalign=0,
            wrap=True,
        )
        server_hint.add_css_class("category-label")
        server_label.append(server_title)
        server_label.append(server_hint)
        server_label.set_hexpand(True)
        self.scopes_server_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.scopes_server_switch.set_active(
            bool(self.config["scopes"].get("server_patch", False))
        )
        server_row.append(server_label)
        server_row.append(self.scopes_server_switch)
        settings_inner.append(server_row)
        settings_card.append(settings_inner)
        content.append(settings_card)

        actions = self._wrap_box(10)
        self.scopes_apply_button = Gtk.Button(label="Ativar lunetas ampliadas")
        self.scopes_apply_button.add_css_class("suggested-action")
        self.scopes_apply_button.connect("clicked", self.on_scopes_apply)
        self.scopes_revert_button = Gtk.Button(label="Restaurar padrão do jogo")
        self.scopes_revert_button.connect("clicked", self.on_scopes_revert)
        actions.append(self.scopes_apply_button)
        actions.append(self.scopes_revert_button)
        self.scopes_export_button = Gtk.Button(label="Gerar para servidor…")
        self.scopes_export_button.set_tooltip_text(
            "Gera o arquivo multilut_zoom.theater para enviar ao administrador "
            "de um servidor que autorizou a instalação — o theater é instalado "
            "NO SERVIDOR e passa a valer para todos os jogadores"
        )
        self.scopes_export_button.connect("clicked", self.on_scopes_export)
        actions.append(self.scopes_export_button)
        content.append(actions)

        self.scopes_status = Gtk.Label(xalign=0, wrap=True)
        self.scopes_status.add_css_class("muted")
        content.append(self.scopes_status)

        note = Gtk.Label(
            label=(
                "Como funciona: os playlists coop do jogo forçam o theater "
                "classic — o nosso override herda esse classic inteiro "
                "(squads, classes, armas) e troca só os FOVs das lunetas. O "
                "aplicativo grava o theater multilut_zoom e ativa pelo "
                "cfg/listenserver.cfg, executado pelo jogo depois dos "
                "playlists a cada partida local (solo incluso). Comando manual "
                "no console precisa de um mapa recarregado depois "
                "(changelevel) — no meio da partida ele apenas reinicia a "
                "rodada. Em servidores de terceiros o theater é escolhido "
                "pelo servidor: use Gerar para servidor e envie o arquivo ao "
                "admin (com autorização) para instalar lá — assim vale para "
                "todos, sem alterar o seu cliente."
            ),
            xalign=0,
            wrap=True,
        )
        note.add_css_class("muted")
        content.append(note)

        scroller.set_child(content)
        return scroller

    def on_scopes_target_changed(self, _scale) -> None:
        self.target_value_label.set_label(f"{self.target_scale.get_value():g}x")

    def on_scopes_preset(self, _button, mag: float) -> None:
        """Atalho de ampliação (3x, 5x, 10x, 12x): ajusta e grava a preferência."""
        self.target_scale.set_value(mag)
        self._persist_scopes_config()

    def _selected_optics(self) -> list[str]:
        return [
            optic_id
            for optic_id, check in self.scope_checks.items()
            if check.get_active()
        ]

    def _persist_scopes_config(self) -> None:
        self.config["scopes"]["target"] = self.target_scale.get_value()
        self.config["scopes"]["optics"] = self._selected_optics()
        self.config["scopes"]["autoexec"] = bool(self.scopes_autoexec_switch.get_active())
        self.config["scopes"]["launch_option"] = bool(
            self.scopes_launch_switch.get_active()
        )
        self.config["scopes"]["server_patch"] = bool(
            self.scopes_server_switch.get_active()
        )
        try:
            core.save_config(self.config)
        except (OSError, core.MultiLUTError) as exc:
            self.toast(f"Não foi possível salvar as preferências das lunetas: {exc}", 6)

    def refresh_scopes_page(self) -> None:
        configured = self.config["scopes"].get("game_dir")
        game_dir = None
        if configured:
            candidate = Path(configured).expanduser()
            if scopes.looks_like_game_dir(candidate):
                game_dir = candidate
        if game_dir is None:
            found = scopes.find_game_dirs()
            game_dir = found[0] if found else None
        self.scopes_game_dir = game_dir
        if game_dir is not None:
            self.scopes_path_label.set_label(str(game_dir))
            if scopes.is_applied(game_dir):
                target = scopes.applied_target(game_dir)
                if scopes.listenserver_zoom_enabled(game_dir):
                    text = (
                        f"Ativo: lunetas ampliadas para {target:g}x — o theater "
                        "carrega no início de cada partida local (solo incluso)."
                    )
                    self.scopes_status.remove_css_class("muted")
                    self.scopes_status.remove_css_class("warning")
                    self.scopes_status.add_css_class("success")
                else:
                    text = (
                        f"Theater gravado para {target:g}x, mas sem ativação "
                        "automática — clique em “Ativar lunetas ampliadas” para "
                        "o jogo carregar o theater nas partidas."
                    )
                    self.scopes_status.remove_css_class("success")
                    self.scopes_status.add_css_class("warning")
            else:
                text = "Padrão do jogo — nenhum theater customizado ativo."
                self.scopes_status.remove_css_class("success")
                self.scopes_status.remove_css_class("warning")
                self.scopes_status.add_css_class("muted")
            try:
                server_patched = scopes.server_patches_present(game_dir)
            except (OSError, core.MultiLUTError):
                server_patched = []
            if server_patched:
                text += (
                    f" Client-side em vigor em {len(server_patched)} "
                    "theater(s) de servidor."
                )
            self.scopes_status.set_label(text)
        else:
            self.scopes_path_label.set_label(
                "Não encontrei a instalação do Insurgency nas bibliotecas Steam "
                "conhecidas. Informe o caminho manualmente — ex.: "
                "~/.local/share/Steam/steamapps/common/insurgency2/insurgency."
            )
            self.scopes_status.set_label("Informe o caminho do jogo para ativar.")
            self.scopes_status.remove_css_class("success")
            self.scopes_status.add_css_class("muted")
        has_game = game_dir is not None
        self.scopes_apply_button.set_sensitive(has_game)
        self.scopes_revert_button.set_sensitive(has_game)

    def on_scopes_use_manual_path(self, _button) -> None:
        text = self.scopes_path_entry.get_text().strip()
        if not text:
            self.toast("Informe o caminho da pasta insurgency2/insurgency.", 5)
            return
        candidate = Path(text).expanduser()
        if not candidate.exists():
            self.toast(f"A pasta não existe: {candidate}", 6)
            return
        if not candidate.is_dir():
            self.toast(f"O caminho informado não é uma pasta: {candidate}", 6)
            return
        if not scopes.looks_like_game_dir(candidate):
            inside = scopes.find_game_dir_above(candidate)
            if inside is not None:
                self.config["scopes"]["game_dir"] = str(inside)
                try:
                    core.save_config(self.config)
                except (OSError, core.MultiLUTError) as exc:
                    self.toast(f"Não foi possível salvar o caminho: {exc}", 6)
                    return
                self.refresh_scopes_page()
                self.toast(
                    f"Essa pasta não é a do jogo, mas encontrei a instalação em: {inside}",
                    7,
                )
                return
            self.toast(
                "Essa pasta existe, mas não reconheci a instalação do jogo: "
                "faltam subpastas típicas (maps, cfg, scripts…).", 7
            )
            return
        self.config["scopes"]["game_dir"] = str(candidate)
        try:
            core.save_config(self.config)
        except (OSError, core.MultiLUTError) as exc:
            self.toast(f"Não foi possível salvar o caminho: {exc}", 6)
            return
        self.refresh_scopes_page()
        self.toast("Instalação do jogo reconhecida.", 4)

    def on_scopes_refresh_clicked(self, _button) -> None:
        self.refresh_scopes_page()
        if self.scopes_game_dir is not None:
            self.toast("Instalação encontrada.")

    def on_scopes_apply(self, _button) -> None:
        if getattr(self, "scopes_game_dir", None) is None:
            self.toast("Encontre ou informe a instalação do jogo primeiro.", 6)
            return
        optics = self._selected_optics()
        if not optics:
            self.toast("Selecione pelo menos uma luneta.", 5)
            return
        target = self.target_scale.get_value()
        try:
            scopes.apply_zoom(self.scopes_game_dir, target, optics)
            scopes.set_autoexec_zoom(
                self.scopes_game_dir, bool(self.scopes_autoexec_switch.get_active())
            )
            scopes.set_listenserver_zoom(self.scopes_game_dir, True)
        except (OSError, core.MultiLUTError) as exc:
            self.toast(f"Não foi possível aplicar: {exc}", 8)
            return
        launch_warning = ""
        try:
            scopes.set_launch_option(
                bool(self.scopes_launch_switch.get_active())
            )
        except (OSError, core.MultiLUTError) as exc:
            launch_warning = f" Opção de inicialização não aplicada: {exc}"
        server_note = ""
        if self.scopes_server_switch.get_active():
            try:
                patch_result = scopes.patch_server_theaters(
                    self.scopes_game_dir, target, optics
                )
            except (OSError, core.MultiLUTError) as exc:
                self.toast(
                    f"Lunetas locais aplicadas, mas o patch client-side "
                    f"falhou: {exc}",
                    8,
                )
            else:
                if patch_result["patched"]:
                    server_note = (
                        f" Client-side: {len(patch_result['patched'])} "
                        "theater(s) de servidor alterado(s)."
                    )
                elif patch_result["skipped"]:
                    server_note = (
                        " Client-side: nenhum theater de servidor alterado "
                        f"({patch_result['skipped'][0]})."
                    )
                else:
                    server_note = (
                        " Client-side: nada a alterar nos theaters de "
                        "servidor."
                    )
        self._persist_scopes_config()
        self.refresh_scopes_page()
        self.toast(
            f"Lunetas ampliadas para {target:g}x. Vale na próxima partida local: "
            f"saia da partida atual e comece outra.{launch_warning}{server_note}",
            8,
        )

    def on_scopes_revert(self, _button) -> None:
        if getattr(self, "scopes_game_dir", None) is None:
            self.toast("Encontre ou informe a instalação do jogo primeiro.", 6)
            return
        try:
            changed = scopes.revert_zoom(self.scopes_game_dir)
        except (OSError, core.MultiLUTError) as exc:
            self.toast(f"Não foi possível restaurar: {exc}", 8)
            return
        try:
            servers_restored = scopes.revert_server_patches(self.scopes_game_dir)
        except (OSError, core.MultiLUTError) as exc:
            self.toast(
                f"Padrão local restaurado, mas os theaters de servidor "
                f"ficaram pendentes: {exc}",
                8,
            )
            servers_restored = 0
        try:
            scopes.set_launch_option(False)
        except (OSError, core.MultiLUTError) as exc:
            self.toast(
                f"Restaurado, mas a opção de inicialização do Steam ficou "
                f"pendente: {exc}",
                6,
            )
        self.refresh_scopes_page()
        suffix = (
            f" {servers_restored} theater(s) de servidor devolvido(s) ao "
            "original."
            if servers_restored
            else ""
        )
        self.toast(
            "Padrão do jogo restaurado."
            if changed or servers_restored
            else "Nada para restaurar.",
        )
        if suffix:
            self.toast(suffix, 6)

    def on_scopes_export(self, _button) -> None:
        """Gera o theater das lunetas em um local escolhido (p/ servidores)."""
        optics = self._selected_optics()
        if not optics:
            self.toast("Selecione pelo menos uma luneta.", 5)
            return
        target = self.target_scale.get_value()
        self._pending_export = (target, optics)
        default_name = f"{scopes.THEATER_NAME}.theater"
        if hasattr(Gtk, "FileDialog"):  # GTK 4.10+
            dialog = Gtk.FileDialog()
            dialog.set_title("Salvar theater para servidor")
            dialog.set_initial_name(default_name)
            try:
                dialog.save(self, None, self._on_export_dialog_done)
            except GLib.Error as exc:
                self.toast(f"Não foi possível abrir o diálogo: {exc}", 6)
            return
        dialog = Gtk.FileChooserNative.new(  # GTK < 4.10
            "Salvar theater para servidor",
            self,
            Gtk.FileChooserAction.SAVE,
            "Salvar",
            "Cancelar",
        )
        dialog.set_current_name(default_name)
        dialog.connect("response", self._on_export_native_done)
        dialog.show()

    def _on_export_dialog_done(self, dialog, result) -> None:
        try:
            file = dialog.save_finish(result)
        except GLib.Error as exc:
            if exc.code != Gtk.DialogError.DISMISSED:
                self.toast(f"Não foi possível escolher o local: {exc}", 6)
            return
        if file is not None:
            self._write_export(file.get_path())

    def _on_export_native_done(self, dialog, response) -> None:
        if response != Gtk.ResponseType.ACCEPT:
            return
        file = dialog.get_file()
        if file is not None:
            self._write_export(file.get_path())

    def _write_export(self, path: str | None) -> None:
        if not path:
            return
        pending = getattr(self, "_pending_export", None)
        if pending is None:
            return
        target, optics = pending
        try:
            saved = scopes.export_theater_file(path, target, optics)
        except (OSError, core.MultiLUTError) as exc:
            self.toast(f"Não foi possível gerar o arquivo: {exc}", 8)
            return
        self.toast(
            f"Theater {target:g}x gerado: {saved}. Envie-o ao admin do "
            "servidor para instalar — lá vale para todos os jogadores.",
            10,
        )

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

    def select_profile_id(self, profile_id: int) -> None:
        # A lista aparece em ordem alfabética: localize pelo id do perfil,
        # não pela posição da linha.
        self._programmatic_selection = True
        try:
            row = self.profile_list.get_first_child()
            while row is not None:
                if row.profile.id == profile_id:
                    self.profile_list.select_row(row)
                    self.update_detail(row.profile)
                    break
                row = row.get_next_sibling()
        finally:
            self._programmatic_selection = False

    def on_profile_selected(self, _listbox, row) -> None:
        if row is None:
            return
        self.update_detail(row.profile)
        if self.auto_switch.get_active() and not self._programmatic_selection:
            self.apply_selected_profile()

    def on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        query = entry.get_text().casefold().strip()
        row = self.profile_list.get_first_child()
        while row is not None:
            profile = row.profile
            haystack = " ".join(
                (profile.name, profile.category, profile.summary, profile.best_for)
            ).casefold()
            row.set_visible(not query or query in haystack)
            row = row.get_next_sibling()

    def on_auto_changed(self, switch, _param) -> None:
        self.config["auto_apply"] = switch.get_active()
        core.save_config(self.config)

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
        elif core.is_game_running():
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
        if valid:
            self.shader_validation.remove_css_class("warning")
            self.shader_validation.add_css_class("success")
            try:
                active = core.read_active_profile(self.shader_path)
            except core.MultiLUTError:
                return
            self.status_icon.set_from_icon_name("emblem-ok-symbolic")
            self.status_label.set_label(f"Ativo: {active:02d} — {core.PROFILE_BY_ID[active].name}")
            if select_active:
                self.select_profile_id(active)
        else:
            self.shader_validation.remove_css_class("success")
            self.shader_validation.add_css_class("warning")
            self.status_icon.set_from_icon_name("dialog-warning-symbolic")
            self.status_label.set_label("Shader não localizado ou incompatível")

    def refresh_game_status(self) -> bool:
        running = core.is_game_running()
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
