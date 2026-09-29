#!/usr/bin/env python3
"""GTK4 widgets for aim training: shared crosshair renderer, flick trainer
and progress charts.

Usa apenas Gtk/Gdk/GLib/cairo (sem libadwaita) para poder ser reaproveitado
pelo processo separado do overlay de mira.
"""

from __future__ import annotations

from datetime import datetime
import random
import time

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

import cairo

import multilut_aim as aim


CANVAS_BG = (0.086, 0.090, 0.106)          # #16171b
CANVAS_HUD = (0.88, 0.90, 0.92)
TARGET_COLOR = (0.18, 0.76, 0.50)          # #2ec27e
TARGET_RING = (0.95, 0.97, 0.96)
MISS_COLOR = (0.90, 0.22, 0.25)
ACCENT_COLOR = (0.21, 0.52, 0.89)          # #3584e4


def _centered_text(ctx, center_x: float, center_y: float, text: str, size: float,
                   color, bold: bool = True) -> None:
    ctx.set_font_size(size)
    ctx.select_font_face(
        "Sans",
        cairo.FontSlant.NORMAL,
        cairo.FontWeight.BOLD if bold else cairo.FontWeight.NORMAL,
    )
    extents = ctx.text_extents(text)
    ctx.set_source_rgba(*color, 1.0)
    ctx.move_to(center_x - extents.width / 2 - extents.x_bearing,
                center_y - extents.height / 2 - extents.y_bearing)
    ctx.show_text(text)


def _corner_text(ctx, x: float, y: float, text: str, size: float,
                 color, bold: bool = False) -> None:
    ctx.set_font_size(size)
    ctx.select_font_face(
        "Sans",
        cairo.FontSlant.NORMAL,
        cairo.FontWeight.BOLD if bold else cairo.FontWeight.NORMAL,
    )
    extents = ctx.text_extents(text)
    ctx.set_source_rgba(*color, 1.0)
    ctx.move_to(x, y - extents.y_bearing)
    ctx.show_text(text)


def draw_crosshair(ctx, width: float, height: float, cfg: dict) -> None:
    """Desenha o crosshair clássico (4 traços + ponto opcional) no centro."""
    cfg = aim.normalize_crosshair_config(cfg)
    red, green, blue = aim.hex_to_rgb(cfg["color"])
    alpha = cfg["opacity"]
    center_x = width / 2.0
    center_y = height / 2.0
    gap = float(cfg["gap"])
    length = float(cfg["length"])
    thickness = float(cfg["thickness"])
    ctx.set_line_cap(cairo.LineCap.BUTT)

    def stroke_arms(line_width: float, rgba) -> None:
        ctx.set_source_rgba(rgba[0], rgba[1], rgba[2], rgba[3])
        ctx.set_line_width(line_width)
        ctx.move_to(center_x, center_y - gap - length)
        ctx.line_to(center_x, center_y - gap)
        ctx.move_to(center_x, center_y + gap)
        ctx.line_to(center_x, center_y + gap + length)
        ctx.move_to(center_x - gap - length, center_y)
        ctx.line_to(center_x - gap, center_y)
        ctx.move_to(center_x + gap, center_y)
        ctx.line_to(center_x + gap + length, center_y)
        ctx.stroke()

    if cfg["outline"]:
        stroke_arms(thickness + 2.0, (0.0, 0.0, 0.0, min(1.0, alpha)))
    stroke_arms(thickness, (red, green, blue, alpha))

    if cfg["dot"]:
        dot_radius = float(cfg["dot_size"])
        if cfg["outline"]:
            ctx.set_source_rgba(0.0, 0.0, 0.0, min(1.0, alpha))
            ctx.arc(center_x, center_y, dot_radius + 1.0, 0.0, 2.0 * 3.141592653589793)
            ctx.fill()
        ctx.set_source_rgba(red, green, blue, alpha)
        ctx.arc(center_x, center_y, dot_radius, 0.0, 2.0 * 3.141592653589793)
        ctx.fill()


class CrosshairPreview(Gtk.DrawingArea):
    """Miniatura do crosshair atual para a página de configuração."""

    def __init__(self):
        super().__init__()
        self.config = aim.CROSSHAIR_DEFAULTS
        self.set_size_request(260, 140)
        self.set_draw_func(self._draw)

    def set_config(self, config: dict) -> None:
        self.config = aim.normalize_crosshair_config(config)
        self.queue_draw()

    def _draw(self, _area, ctx, width, height) -> None:
        ctx.set_source_rgba(*CANVAS_BG, 1.0)
        ctx.set_operator(cairo.Operator.SOURCE)
        ctx.paint()
        ctx.set_operator(cairo.Operator.OVER)
        draw_crosshair(ctx, width, height, self.config)


class TrendChart(Gtk.DrawingArea):
    """Gráfico de tendência simples: pontos por rodada + média móvel."""

    def __init__(self, title: str, unit: str, line_color=ACCENT_COLOR):
        super().__init__()
        self.title = title
        self.unit = unit
        self.line_color = line_color
        self.values: list[float] = []
        self.set_size_request(320, 168)
        self.set_vexpand(True)
        self.set_draw_func(self._draw)

    def set_series(self, values: list[float]) -> None:
        self.values = [float(value) for value in values if value >= 0]
        self.queue_draw()

    def _draw(self, _area, ctx, width, height) -> None:
        ctx.set_source_rgba(*CANVAS_BG, 1.0)
        ctx.set_operator(cairo.Operator.SOURCE)
        ctx.paint()
        ctx.set_operator(cairo.Operator.OVER)

        _corner_text(ctx, 12, 20, self.title, 13, CANVAS_HUD, bold=True)
        if not self.values:
            _centered_text(ctx, width / 2, height / 2, "Sem dados ainda — faça uma rodada de treino",
                           12, (*CANVAS_HUD, 0.55), bold=False)
            return

        left, right, top, bottom = 14.0, 14.0, 34.0, 26.0
        plot_w = max(10.0, width - left - right)
        plot_h = max(10.0, height - top - bottom)
        values = self.values
        low = min(values)
        high = max(values)
        if high - low < 1e-9:
            low -= 1.0
            high += 1.0
        span = high - low
        low -= span * 0.10
        high += span * 0.10

        def point_x(index: int) -> float:
            if len(values) == 1:
                return left + plot_w / 2
            return left + plot_w * index / (len(values) - 1)

        def point_y(value: float) -> float:
            return top + plot_h * (1.0 - (value - low) / (high - low))

        ctx.set_line_width(1.0)
        ctx.set_source_rgba(*CANVAS_HUD, 0.12)
        for fraction in (0.25, 0.5, 0.75):
            grid_y = top + plot_h * fraction
            ctx.move_to(left, grid_y)
            ctx.line_to(left + plot_w, grid_y)
            ctx.stroke()

        ctx.set_source_rgba(*CANVAS_HUD, 0.45)
        ctx.set_font_size(10)
        ctx.select_font_face("Sans", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.move_to(left, top - 6)
        ctx.show_text(f"{high:.0f}{self.unit}")
        ctx.move_to(left, top + plot_h + 14)
        ctx.show_text(f"{low:.0f}{self.unit}")
        _corner_text(ctx, left + plot_w - 120, top + plot_h + 14, "antiga → recente",
                     10, (*CANVAS_HUD, 0.45), bold=False)

        # Pontos por rodada (suaves).
        for index, value in enumerate(values):
            ctx.set_source_rgba(*self.line_color, 0.28)
            ctx.arc(point_x(index), point_y(value), 3.0, 0.0, 2.0 * 3.141592653589793)
            ctx.fill()

        # Média móvel.
        smoothed = aim.moving_average(values, 5)
        ctx.set_line_width(2.4)
        ctx.set_source_rgba(*self.line_color, 0.95)
        for index, value in enumerate(smoothed):
            x = point_x(index)
            y = point_y(value)
            if index == 0:
                ctx.move_to(x, y)
            else:
                ctx.line_to(x, y)
        ctx.stroke()

        last_x = point_x(len(smoothed) - 1)
        last_y = point_y(smoothed[-1])
        ctx.set_source_rgba(*self.line_color, 1.0)
        ctx.arc(last_x, last_y, 4.0, 0.0, 2.0 * 3.141592653589793)
        ctx.fill()
        _corner_text(ctx, min(last_x + 8, width - 70), last_y - 8,
                     f"{smoothed[-1]:.0f}{self.unit}", 11, CANVAS_HUD, bold=True)


class FlickTrainer(Gtk.Box):
    """Treinador de flick: um alvo por vez, medição de reação e precisão."""

    def __init__(self, on_session_saved=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.on_session_saved = on_session_saved
        self.state = "idle"          # idle | countdown | running | finished
        self.countdown_value = 0
        self.total_targets = 20
        self.target_radius = 22
        self.hits = 0
        self.misses = 0
        self.reactions: list[float] = []
        self.spawn_time = 0.0
        self.round_start = 0.0
        self.target_xy: tuple[float, float] | None = None
        self.previous_xy: tuple[float, float] | None = None
        self.miss_marks: list[tuple[float, float, float]] = []
        self.round_duration = 0.0
        self.last_error = ""

        self.set_margin_top(6)

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        panel.set_size_request(268, -1)

        title = Gtk.Label(label="Treino de flick", xalign=0)
        title.set_markup("<span size='125%' weight='800'>Treino de flick</span>")
        description = Gtk.Label(
            label=(
                "Um alvo aparece por vez. Clique nele o mais rápido possível; "
                "a reação e a precisão ficam no histórico para acompanhar a evolução."
            ),
            xalign=0,
            wrap=True,
        )
        description.add_css_class("muted")
        panel.append(title)
        panel.append(description)

        settings = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        settings.add_css_class("card")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        inner.set_margin_start(14)
        inner.set_margin_end(14)
        inner.set_margin_top(12)
        inner.set_margin_bottom(12)

        targets_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        targets_label = Gtk.Label(label="Alvos por rodada", xalign=0)
        targets_label.set_hexpand(True)
        self.targets_spin = Gtk.SpinButton.new(
            Gtk.Adjustment.new(20, 5, 100, 5, 10, 0), 1, 0
        )
        targets_row.append(targets_label)
        targets_row.append(self.targets_spin)

        radius_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        radius_label = Gtk.Label(label="Raio do alvo (px)", xalign=0)
        radius_label.set_hexpand(True)
        self.radius_spin = Gtk.SpinButton.new(
            Gtk.Adjustment.new(22, 10, 60, 2, 6, 0), 1, 0
        )
        radius_row.append(radius_label)
        radius_row.append(self.radius_spin)

        inner.append(targets_row)
        inner.append(radius_row)
        settings.append(inner)
        panel.append(settings)

        self.start_button = Gtk.Button(label="Iniciar rodada")
        self.start_button.add_css_class("suggested-action")
        self.start_button.connect("clicked", self.on_start_clicked)
        panel.append(self.start_button)

        results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        results.add_css_class("card")
        results_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        results_inner.set_margin_start(14)
        results_inner.set_margin_end(14)
        results_inner.set_margin_top(12)
        results_inner.set_margin_bottom(12)
        self.results_label = Gtk.Label(xalign=0, wrap=True)
        self.results_label.set_markup(
            "<b>Resultado da última rodada</b>\nNenhuma rodada ainda nesta sessão."
        )
        results_inner.append(self.results_label)
        results.append(results_inner)
        panel.append(results)

        tip = Gtk.Label(
            label=(
                "Dica: treine 10 minutos antes de jogar e compare no gráfico de "
                "progresso. Aumente a dificuldade reduzindo o raio do alvo."
            ),
            xalign=0,
            wrap=True,
        )
        tip.add_css_class("muted")
        panel.append(tip)

        canvas_frame = Gtk.Frame()
        canvas_frame.set_hexpand(True)
        canvas_frame.set_vexpand(True)
        self.canvas = Gtk.DrawingArea()
        self.canvas.set_hexpand(True)
        self.canvas.set_vexpand(True)
        self.canvas.set_draw_func(self._draw_canvas)
        canvas_frame.set_child(self.canvas)

        self.append(panel)
        self.append(canvas_frame)

        click = Gtk.GestureClick()
        click.connect("pressed", self.on_canvas_click)
        self.canvas.add_controller(click)

    # ------------------------------------------------------------------ fluxo
    def on_start_clicked(self, _button) -> None:
        if self.state in ("countdown", "running"):
            self.reset("Rodada encerrada antes do fim.")
            return
        self.total_targets = int(self.targets_spin.get_value())
        self.target_radius = int(self.radius_spin.get_value())
        self.hits = 0
        self.misses = 0
        self.reactions = []
        self.miss_marks = []
        self.target_xy = None
        self.previous_xy = None
        self.state = "countdown"
        self.countdown_value = 3
        self.start_button.set_label("Encerrar rodada")
        self.canvas.queue_draw()
        GLib.timeout_add(700, self._countdown_tick)

    def _countdown_tick(self) -> bool:
        if self.state != "countdown":
            return GLib.SOURCE_REMOVE
        self.countdown_value -= 1
        if self.countdown_value <= 0:
            self.state = "running"
            self.round_start = time.monotonic()
            self.spawn_target()
            self.canvas.queue_draw()
            return GLib.SOURCE_REMOVE
        self.canvas.queue_draw()
        return GLib.SOURCE_CONTINUE

    def spawn_target(self) -> None:
        width = max(40.0, float(self.canvas.get_width()))
        height = max(40.0, float(self.canvas.get_height()))
        margin = self.target_radius + 24
        min_flick = max(180.0, self.target_radius * 3.5)
        chosen = None
        for _attempt in range(120):
            x = random.uniform(margin, width - margin)
            y = random.uniform(margin, height - margin)
            if self.previous_xy is not None:
                distance = ((x - self.previous_xy[0]) ** 2 + (y - self.previous_xy[1]) ** 2) ** 0.5
                if distance < min_flick:
                    continue
            chosen = (x, y)
            break
        if chosen is None:
            chosen = (random.uniform(margin, width - margin), random.uniform(margin, height - margin))
        self.target_xy = chosen
        self.previous_xy = chosen
        self.spawn_time = time.monotonic()
        self.canvas.queue_draw()

    def on_canvas_click(self, _gesture, _n_press, x: float, y: float) -> None:
        if self.state != "running" or self.target_xy is None:
            return
        distance = ((x - self.target_xy[0]) ** 2 + (y - self.target_xy[1]) ** 2) ** 0.5
        if distance <= self.target_radius:
            reaction_ms = (time.monotonic() - self.spawn_time) * 1000.0
            self.reactions.append(reaction_ms)
            self.hits += 1
            if self.hits >= self.total_targets:
                self.finish_round()
            else:
                self.spawn_target()
        else:
            self.misses += 1
            self.miss_marks.append((x, y, time.monotonic() + 0.28))
            GLib.timeout_add(300, self._expire_miss_marks)

    def _expire_miss_marks(self) -> bool:
        now = time.monotonic()
        self.miss_marks = [mark for mark in self.miss_marks if mark[2] > now]
        self.canvas.queue_draw()
        return GLib.SOURCE_REMOVE

    def finish_round(self) -> None:
        duration = max(0.05, time.monotonic() - self.round_start)
        self.round_duration = duration
        self.state = "finished"
        self.target_xy = None
        self.start_button.set_label("Iniciar rodada")
        avg = sum(self.reactions) / len(self.reactions)
        session = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "mode": "flick",
            "targets": self.hits,
            "misses": self.misses,
            "avg_reaction_ms": avg,
            "best_reaction_ms": min(self.reactions),
            "targets_per_minute": self.hits / (duration / 60.0),
            "duration_s": duration,
        }
        saved_message = ""
        try:
            aim.append_training_session(session)
            saved_message = "Histórico atualizado — veja a aba Progresso."
        except (aim.MultiLUTError, OSError) as exc:
            saved_message = f"Falha ao salvar: {exc}"
        clicks = self.hits + self.misses
        accuracy = 100.0 * self.hits / clicks if clicks else 0.0
        self.results_label.set_markup(
            "<b>Resultado da última rodada</b>\n"
            f"Reação média: <b>{avg:.0f} ms</b>\n"
            f"Melhor reação: <b>{min(self.reactions):.0f} ms</b>\n"
            f"Precisão: <b>{accuracy:.0f}%</b> ({self.hits}/{clicks} cliques)\n"
            f"Ritmo: <b>{session['targets_per_minute']:.0f} alvos/min</b>\n"
            f"{saved_message}"
        )
        self.canvas.queue_draw()
        if self.on_session_saved is not None:
            self.on_session_saved(session)

    def reset(self, note: str = "") -> None:
        self.state = "idle"
        self.countdown_value = 0
        self.target_xy = None
        self.miss_marks = []
        self.start_button.set_label("Iniciar rodada")
        if note:
            self.results_label.set_markup(f"<b>Resultado da última rodada</b>\n{note}")
        self.canvas.queue_draw()

    # -------------------------------------------------------------- desenho
    def _draw_canvas(self, _area, ctx, width, height) -> None:
        ctx.set_source_rgba(*CANVAS_BG, 1.0)
        ctx.set_operator(cairo.Operator.SOURCE)
        ctx.paint()
        ctx.set_operator(cairo.Operator.OVER)

        if self.state == "idle":
            _centered_text(ctx, width / 2, height / 2 - 16,
                           "Pressione “Iniciar rodada” para treinar", 15, CANVAS_HUD)
            _centered_text(ctx, width / 2, height / 2 + 14,
                           "Cada alvo vale um flick: reagir rápido e errar pouco.", 12,
                           (*CANVAS_HUD, 0.55), bold=False)
            return

        if self.state == "countdown":
            _centered_text(ctx, width / 2, height / 2, str(max(1, self.countdown_value)),
                           64, TARGET_COLOR)
            _centered_text(ctx, width / 2, height / 2 + 62, "Prepare a mira no centro…", 12,
                           (*CANVAS_HUD, 0.6), bold=False)
            return

        for mark_x, mark_y, _expire in self.miss_marks:
            ctx.set_line_width(2.0)
            ctx.set_source_rgba(*MISS_COLOR, 0.85)
            ctx.move_to(mark_x - 6, mark_y - 6)
            ctx.line_to(mark_x + 6, mark_y + 6)
            ctx.move_to(mark_x + 6, mark_y - 6)
            ctx.line_to(mark_x - 6, mark_y + 6)
            ctx.stroke()

        if self.state == "running" and self.target_xy is not None:
            center_x, center_y = self.target_xy
            radius = float(self.target_radius)
            ctx.set_source_rgba(*TARGET_COLOR, 0.28)
            ctx.arc(center_x, center_y, radius + 7.0, 0.0, 2.0 * 3.141592653589793)
            ctx.fill()
            ctx.set_source_rgba(*TARGET_COLOR, 0.95)
            ctx.arc(center_x, center_y, radius, 0.0, 2.0 * 3.141592653589793)
            ctx.fill()
            ctx.set_line_width(2.0)
            ctx.set_source_rgba(*TARGET_RING, 0.9)
            ctx.arc(center_x, center_y, radius, 0.0, 2.0 * 3.141592653589793)
            ctx.stroke()
            ctx.set_source_rgba(*CANVAS_BG, 0.85)
            ctx.arc(center_x, center_y, 3.2, 0.0, 2.0 * 3.141592653589793)
            ctx.fill()

        clicks = self.hits + self.misses
        accuracy = 100.0 * self.hits / clicks if clicks else 0.0
        average = sum(self.reactions) / len(self.reactions) if self.reactions else 0.0
        last = self.reactions[-1] if self.reactions else 0.0
        _corner_text(ctx, 14, 28,
                     f"Alvo {min(self.hits + 1, self.total_targets)}/{self.total_targets}",
                     14, CANVAS_HUD, bold=True)
        _corner_text(ctx, 14, 52, f"Última reação: {last:.0f} ms", 12, CANVAS_HUD)
        _corner_text(ctx, 14, 74, f"Reação média: {average:.0f} ms", 12, CANVAS_HUD)
        _corner_text(ctx, 14, 96, f"Precisão: {accuracy:.0f}%", 12, CANVAS_HUD)

        if self.state == "finished":
            box_w, box_h = min(360.0, width - 40), 168.0
            box_x, box_y = (width - box_w) / 2, (height - box_h) / 2
            ctx.set_source_rgba(0.05, 0.06, 0.07, 0.88)
            ctx.arc(box_x + 14, box_y + 14, 14, 3.141592653589793, 4.71238898038469)
            ctx.arc(box_x + box_w - 14, box_y + 14, 14, 4.71238898038469, 6.283185307179586)
            ctx.arc(box_x + box_w - 14, box_y + box_h - 14, 14, 0.0, 1.5707963267948966)
            ctx.arc(box_x + 14, box_y + box_h - 14, 14, 1.5707963267948966, 3.141592653589793)
            ctx.close_path()
            ctx.fill()
            ctx.set_line_width(1.2)
            ctx.set_source_rgba(*TARGET_COLOR, 0.5)
            ctx.stroke()
            center = width / 2
            _centered_text(ctx, center, box_y + 38, "Rodada concluída", 16, TARGET_COLOR)
            _centered_text(ctx, center, box_y + 70,
                           f"Reação média {average:.0f} ms  •  melhor {min(self.reactions):.0f} ms",
                           13, CANVAS_HUD)
            _centered_text(ctx, center, box_y + 94,
                           f"Precisão {accuracy:.0f}%  •  ritmo {self._last_tempo():.0f} alvos/min",
                           13, CANVAS_HUD)
            _centered_text(ctx, center, box_y + 126,
                           "Rodada salva na aba Progresso", 11, (*CANVAS_HUD, 0.6), bold=False)

    def _last_tempo(self) -> float:
        duration = self.round_duration if self.round_duration > 0 else 0.05
        return self.hits / (duration / 60.0) if self.hits else 0.0
