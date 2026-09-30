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
        body.append(self.view_stack)

        toolbar.set_content(body)
        self.toast_overlay.set_child(toolbar)
        self.set_content(self.toast_overlay)

        self.refresh_shader_status(select_active=True)
        self.refresh_game_status()
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
        hint = Gtk.Label(label="Efeitos de mapa e utilitários", xalign=0)
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
        for section_title, profiles in core.profiles_by_section():
            self.profile_list.append(SectionHeaderRow(section_title))
            for profile in profiles:
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
        for row in rows:
            profile = getattr(row, "profile", None)
            if profile is None:  # cabeçalho: fecha a seção anterior
                if header is not None:
                    visible[header] = section_has_match
                header = row
                section_has_match = False
                continue
            haystack = " ".join(
                (profile.name, profile.category, profile.summary, profile.best_for)
            ).casefold()
            shows = not query or query in haystack
            visible[row] = shows
            if shows:
                section_has_match = True
        if header is not None:
            visible[header] = section_has_match
        for row, shows in visible.items():
            row.set_visible(shows)

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
