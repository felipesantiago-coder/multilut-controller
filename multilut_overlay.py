#!/usr/bin/env python3
"""Overlay de mira do MultiLUT Controller.

Processo separado forçado para o backend X11 (XWayland no GNOME Wayland).
O jogo do Insurgency (via Proton) também vive no XWayland, então o Mutter
honra o estado EWMH "sempre acima" e o XShape de região de entrada vazia,
deixando a mira visível sobre o jogo sem roubar um único clique.

Este processo não lê memória do jogo, não injeta código e não interfere na
entrada do jogador: é apenas uma janela visual transparente.
"""

from __future__ import annotations

import os

os.environ["GDK_BACKEND"] = "x11"  # precisa vir antes de qualquer import do gi

from pathlib import Path
import ctypes
import signal
import sys

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import warnings

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk

try:
    from gi import PyGIDeprecationWarning
    warnings.filterwarnings("ignore", category=PyGIDeprecationWarning)
except ImportError:  # pragma: no cover
    pass

try:
    gi.require_version("GdkX11", "4.0")
    from gi.repository import GdkX11  # noqa: F401  (necessário para get_xid)
except (ImportError, ValueError):  # pragma: no cover
    pass

import cairo

import multilut_aim as aim
import multilut_core as core
import multilut_trainer as trainer


# ---------------------------------------------------------------- X11 direto
_SHAPE_INPUT = 2
_SHAPE_SET = 0
_YXBANDED = 3
_NET_WM_STATE_ADD = 1
_SUBSTRUCTURE_NOTIFY = 1 << 19
_SUBSTRUCTURE_REDIRECT = 1 << 20
_CLIENT_MESSAGE = 33


class _XClientMessageEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", ctypes.c_long * 5),
    ]


class X11Bridge:
    """Chamadas X11 fora da API do GTK4: XShape (clique-através) e EWMH (acima)."""

    def __init__(self):
        self.available = False
        self.xlib = None
        self.xext = None
        self.display = None
        try:
            self.xlib = ctypes.CDLL("libX11.so.6")
            self.xext = ctypes.CDLL("libXext.so.6")
        except OSError:
            return
        try:
            self.xlib.XOpenDisplay.restype = ctypes.c_void_p
            self.xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
            self.xlib.XDefaultRootWindow.restype = ctypes.c_ulong
            self.xlib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            self.xlib.XInternAtom.restype = ctypes.c_ulong
            self.xlib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
            self.xlib.XSendEvent.restype = ctypes.c_int
            self.xlib.XSendEvent.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.c_void_p
            ]
            self.xlib.XFlush.argtypes = [ctypes.c_void_p]
            self.xlib.XMoveResizeWindow.restype = ctypes.c_int
            self.xlib.XMoveResizeWindow.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                ctypes.c_uint, ctypes.c_uint,
            ]
            self.xext.XShapeCombineRectangles.restype = ctypes.c_int
            self.xext.XShapeCombineRectangles.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int
            ]
        except AttributeError:
            return
        self.display = self.xlib.XOpenDisplay(None)
        self.available = self.display is not None

    def _atom(self, name: str) -> int:
        return int(self.xlib.XInternAtom(self.display, name.encode(), False))

    def make_input_transparent(self, xid: int) -> bool:
        """Região de entrada vazia: todos os eventos de mouse atravessam a janela."""
        if not self.available:
            return False
        result = self.xext.XShapeCombineRectangles(
            self.display, xid, _SHAPE_INPUT, 0, 0, None, 0, _SHAPE_SET, _YXBANDED
        )
        self.xlib.XFlush(self.display)
        return result != 0

    def move_resize(self, xid: int, x: int, y: int, width: int, height: int) -> bool:
        """Geometria explícita da janela, sem depender do fullscreen do WM."""
        if not self.available:
            return False
        self.xlib.XMoveResizeWindow(
            self.display, xid, int(x), int(y), int(width), int(height)
        )
        self.xlib.XFlush(self.display)
        return True

    def request_states(self, xid: int, states: list[str]) -> bool:
        """Envia _NET_WM_STATE (sempre acima, sem barra de tarefas/pager)."""
        if not self.available:
            return False
        wm_state = self._atom("_NET_WM_STATE")
        root = self.xlib.XDefaultRootWindow(self.display)
        atoms = [self._atom(name) for name in states]
        mask = _SUBSTRUCTURE_NOTIFY | _SUBSTRUCTURE_REDIRECT
        for index in range(0, len(atoms), 2):
            event = _XClientMessageEvent()
            event.type = _CLIENT_MESSAGE
            event.window = xid
            event.message_type = wm_state
            event.format = 32
            event.data[0] = _NET_WM_STATE_ADD
            event.data[1] = atoms[index]
            event.data[2] = atoms[index + 1] if index + 1 < len(atoms) else 0
            self.xlib.XSendEvent(self.display, root, False, mask, ctypes.byref(event))
        self.xlib.XFlush(self.display)
        return True


# ------------------------------------------------------------- janela overlay
OVERLAY_CSS = b"window { background: rgba(0, 0, 0, 0); }"


class OverlayWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application, parent_pid: int | None):
        super().__init__(application=app)
        self.parent_pid = parent_pid
        self.x11 = X11Bridge()
        self.config_monitor = None
        self.monitor_geometry: tuple[int, int, int, int] | None = None

        self.set_title("MultiLUT Overlay")
        self.set_decorated(False)
        # Redimensionável de verdade: sem dicas de tamanho fixo, o GTK aceita a
        # geometria grande imposta pelo X11 em vez de brigar de volta com ela.
        self.set_resizable(True)
        try:
            self.set_focusable(False)  # WM_HINTS input=false: nunca recebe foco
        except AttributeError:
            pass

        provider = Gtk.CssProvider()
        provider.load_from_data(OVERLAY_CSS)
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

        self.crosshair = aim.crosshair_config_from_config(core.load_config())
        self.canvas = Gtk.DrawingArea()
        self.canvas.set_hexpand(True)
        self.canvas.set_vexpand(True)
        self.canvas.set_draw_func(self._draw)
        self.set_child(self.canvas)

        self.connect("map", self.on_map)
        self.start_config_monitor()
        GLib.timeout_add_seconds(1, self.reapply_x11_hacks)
        if parent_pid:
            GLib.timeout_add_seconds(2, self.check_parent_alive)

    # --------------------------------------------------------------- desenho
    def _draw(self, _area, ctx, width, height) -> None:
        ctx.set_source_rgba(0.0, 0.0, 0.0, 0.0)
        ctx.set_operator(cairo.Operator.SOURCE)
        ctx.paint()
        ctx.set_operator(cairo.Operator.OVER)
        trainer.draw_crosshair(ctx, width, height, self.crosshair)

    # -------------------------------------------------------------- X11/XWayland
    def on_map(self, _window) -> None:
        self.pick_monitor()
        self.reapply_x11_hacks()

    def pick_monitor(self) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            return
        monitor = self._monitor_at_pointer(display)
        if monitor is None:
            monitors = display.get_monitors()
            if monitors is None or monitors.get_n_items() == 0:
                return
            monitor = monitors.get_item(0)
        geometry = monitor.get_geometry()
        if geometry is not None:
            self.monitor_geometry = (
                int(geometry.x), int(geometry.y),
                int(geometry.width), int(geometry.height),
            )
        try:
            self.fullscreen_on_monitor(monitor)
        except (AttributeError, TypeError):
            self.fullscreen()

    @staticmethod
    def _monitor_at_pointer(display: Gdk.Display):
        try:
            seat = display.get_default_seat()
            pointer = seat.get_pointer()
            result = pointer.get_position()
            if not isinstance(result, tuple):
                return None
            if len(result) == 4:      # (ok, surface, x, y)
                _ok, _surface, x, y = result
            elif len(result) == 3:    # (surface, x, y)
                _surface, x, y = result
            elif len(result) == 2:    # (x, y)
                x, y = result
            else:
                return None
            return display.get_monitor_at_point(float(x), float(y))
        except (AttributeError, TypeError, ValueError):
            return None

    def enforce_geometry(self, xid: int) -> None:
        """Impõe a geometria do monitor via X11: centro da janela = centro da tela."""
        if self.monitor_geometry is None:
            return
        mx, my, mw, mh = self.monitor_geometry
        if mw <= 0 or mh <= 0:
            return
        self.x11.move_resize(xid, mx, my, mw, mh)

    def reapply_x11_hacks(self) -> bool:
        surface = self.get_surface()
        if surface is None:
            return GLib.SOURCE_CONTINUE
        try:
            xid = surface.get_xid()
        except AttributeError:
            print(
                "MultiLUT Overlay: superfície não é X11; sem clique-através/"
                "sempre-acima. Confira se o XWayland está disponível.",
                file=sys.stderr,
            )
            return GLib.SOURCE_REMOVE
        self.enforce_geometry(int(xid))
        self.x11.make_input_transparent(int(xid))
        self.x11.request_states(
            int(xid),
            ["_NET_WM_STATE_ABOVE", "_NET_WM_STATE_SKIP_TASKBAR", "_NET_WM_STATE_SKIP_PAGER"],
        )
        return GLib.SOURCE_CONTINUE

    # ------------------------------------------------------------ config viva
    def start_config_monitor(self) -> None:
        path = core.app_config_path()
        if not path.is_file():
            return
        try:
            file = Gio.File.new_for_path(str(path))
            self.config_monitor = file.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self.config_monitor.connect("changed", self.on_config_changed)
        except GLib.Error:
            self.config_monitor = None

    def on_config_changed(self, _monitor, _file, _other, event_type) -> None:
        if event_type in (
            Gio.FileMonitorEvent.CHANGES_DONE_HINT,
            Gio.FileMonitorEvent.CREATED,
            Gio.FileMonitorEvent.MOVED_IN,
        ):
            self.crosshair = aim.crosshair_config_from_config(core.load_config())
            self.canvas.queue_draw()

    # ------------------------------------------------------------- ciclo vida
    def check_parent_alive(self) -> bool:
        if not self.parent_pid:
            return GLib.SOURCE_REMOVE
        try:
            os.kill(self.parent_pid, 0)
        except ProcessLookupError:
            application = self.get_application()
            if application is not None:
                application.quit()
            return GLib.SOURCE_REMOVE
        except PermissionError:
            pass
        return GLib.SOURCE_CONTINUE


class OverlayApplication(Gtk.Application):
    def __init__(self, parent_pid: int | None):
        super().__init__(
            application_id="com.felipesantiago.MultiLUTController.Overlay",
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.parent_pid = parent_pid
        self.window: OverlayWindow | None = None
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.on_signal)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.on_signal)

    def on_signal(self) -> bool:
        if self.window is not None:
            self.window.destroy()
        self.quit()
        return GLib.SOURCE_REMOVE

    def do_activate(self):
        # O display só existe depois que o Gtk.Application.startup rodou o
        # gtk_init; a checagem precisa acontecer aqui, nunca antes de run().
        if Gdk.Display.get_default() is None:
            print(
                "MultiLUT Overlay: display X11/XWayland indisponível após a "
                "inicialização do GTK.\nConfira se o XWayland está ativo na sua "
                "sessão GNOME Wayland (variável DISPLAY definida).",
                file=sys.stderr,
            )
            sys.stderr.flush()
            os._exit(3)
        if self.window is None:
            self.window = OverlayWindow(self, self.parent_pid)
        self.window.present()


def main() -> int:
    parent_pid = None
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        parent_pid = int(sys.argv[1])
    app = OverlayApplication(parent_pid)
    # NUNCA passar sys.argv para o GApplication: o PID posicional seria
    # interpretado como arquivo a abrir ("This application can not open
    # files") e a ativação — que cria a janela — nunca aconteceria.
    return app.run([])


if __name__ == "__main__":
    raise SystemExit(main())
