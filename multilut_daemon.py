#!/usr/bin/env python3
"""Daemon headless do MultiLUT Controller: piloto automático sem janela.

Roda como serviço de usuário (systemd) ou avulso em terminal e mantém o
piloto por mapa ativo mesmo com a interface fechada. A GUI e a CLI não
trocam perfil diretamente quando o daemon está ativo: passam a controlá-lo
pelo socket UNIX de controle (JSON por linha):

  {"cmd": "status"}                      -> estado completo do daemon
  {"cmd": "reload"}                      -> relê a configuração do app
  {"cmd": "apply", "token": "tell"}      -> simula a detecção de um mapa
  {"cmd": "stop"}                        -> encerramento gracioso

Estado persistente: XDG_STATE_HOME/multilut-controller/daemon.json
(garante status para a CLI mesmo quando o daemon acabou de sair).
"""

from __future__ import annotations

import gc
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

try:
    import gi

    gi.require_version("GLib", "2.0")
    gi.require_version("Gio", "2.0")
    from gi.repository import GLib, Gio  # noqa: E402
except (ImportError, ValueError):  # monitor de arquivo exige GLib (não é o caso da GUI/CLI)
    GLib = None
    Gio = None

import multilut_core as core  # noqa: E402
import multilut_extra as extra  # noqa: E402


def _require_glib() -> None:
    if GLib is None or Gio is None:
        raise SystemExit(
            "O daemon requer PyGObject (GLib/Gio) para monitorar o console.log."
        )


class DaemonPilot:
    """Piloto por mapa sem GTK: monitor do console.log + troca de perfil."""

    def __init__(self) -> None:
        self.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.events = 0
        self.last_map: dict | None = None
        self._monitor: Gio.FileMonitor | None = None
        self._console_path: Path | None = None
        self._tail: core.ConsoleTail | None = None
        self._debounce_id: int | None = None
        self.stop_requested = False
        self.restart_requested = False  # guardião de memória pediu religar
        self.brightness = extra.BrightnessController()

    # ------------------------------------------------------------ comando/status
    def status(self) -> dict:
        config = core.load_config()
        return {
            "running": True,
            "pid": os.getpid(),
            "started_at": self.started_at,
            "events": self.events,
            "last_map": self.last_map,
            "console_log": str(self._console_path) if self._console_path else None,
            "auto_map_switch": bool(config.get("auto_map_switch", False)),
            "rss_kib": extra.read_process_rss_kib(),
        }

    def record_status(self) -> None:
        extra.write_daemon_status(self.status())

    def record_status_stopped(self) -> None:
        data = self.status()
        data["running"] = False
        extra.write_daemon_status(data)

    def handle_command(self, payload: object) -> dict:
        """Processa um comando JSON do socket; nunca levanta."""
        if not isinstance(payload, dict):
            return {"error": "comando não é um objeto JSON"}
        command = payload.get("cmd")
        if command == "status":
            return self.status()
        if command == "reload":
            self._sync_monitor_state()
            return {"ok": True, "message": "configuração recarregada"}
        if command == "stop":
            self.stop_requested = True
            return {"ok": True, "message": "encerrando"}
        if command == "apply":
            token = payload.get("token")
            if not isinstance(token, str) or not token.strip():
                return {"error": "informe o token do mapa"}
            applied = self.apply_map_token(token.strip(), simulated=True)
            if applied is None:
                return {"applied": False, "token": token}
            return {"applied": True, **applied}
        return {"error": f"comando desconhecido: {command!r}"}

    # ------------------------------------------------------------ shader alvo
    def resolve_shader(self) -> Path | None:
        candidates: list[Path] = []
        remembered = core.load_config().get("shader_path")
        if isinstance(remembered, str) and remembered.strip():
            candidates.append(Path(remembered).expanduser())
        candidates.extend(core.find_shader_candidates())
        candidates.append(core.default_shader_path())
        for candidate in candidates:
            try:
                if candidate.is_file():
                    valid, _ = core.validate_shader(candidate)
                    if valid:
                        return candidate
            except OSError:
                continue
        return None

    def apply_map_token(self, token: str, simulated: bool = False) -> dict | None:
        """Detectou o mapa: aplica o perfil dele se o piloto está ligado.

        Regras aprendidas (config["map_rules"], mapa exato → perfil) têm
        prioridade sobre o casamento por slug do pacote.
        """
        config = core.load_config()
        profile = core.match_map_profile(token, core.map_rules(config))
        if profile is None:
            return None
        if not bool(config.get("auto_map_switch", False)):
            return None
        self._apply_brightness(config, token)
        shader = self.resolve_shader()
        if shader is None:
            return None
        try:
            active = core.read_active_profile(shader)
        except (core.MultiLUTError, OSError, UnicodeError):
            return None
        if active == profile.id:
            return {"token": token, "profile_id": profile.id, "profile_name": profile.name, "changed": False}
        try:
            core.set_active_profile(shader, profile.id)
        except (OSError, UnicodeError, core.MultiLUTError) as exc:
            self._notify("MultiLUT: falha no piloto", str(exc))
            return None
        config["shader_path"] = str(shader)
        config["last_profile"] = profile.id
        core.save_config(config)
        core.append_history(
            {
                "profile_id": profile.id,
                "profile_name": profile.name,
                "origin": "daemon",
                "previous": active,
                "shader": str(shader),
                "detail": token,
            }
        )
        self.events += 1
        self.last_map = {
            "token": token,
            "profile_id": profile.id,
            "profile_name": profile.name,
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.record_status()
        previous_profile = core.PROFILE_BY_ID.get(active)
        old_name = previous_profile.name if previous_profile else f"{active:02d}"
        self._notify_change(
            "MultiLUT: piloto automático",
            f"{token}: {old_name} → {profile.name}",
            undo_profile_id=active,
        )
        return {"token": token, "profile_id": profile.id, "profile_name": profile.name, "changed": True}

    def _apply_brightness(self, config: dict, token: str) -> None:
        """Brilho físico do monitor por mapa (DDC/CI, opcional e silencioso)."""
        try:
            message = self.brightness.apply_for_map(config, token)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return
        if message:
            self._notify("MultiLUT: brilho do monitor", message)

    def _watch_game_for_brightness(self) -> bool:
        """Tique periódico: restaura o brilho quando o jogo fecha."""
        try:
            if self.brightness.modified and not core.is_game_running():
                message = self.brightness.restore(reason="jogo fechado")
                if message:
                    self._notify("MultiLUT: brilho do monitor", message)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
        return True  # continua ticando

    def apply_profile_id(self, profile_id: int, origin: str = "daemon") -> dict | None:
        """Aplica um perfil específico pelo id (usado pelo desfazer da notificação)."""
        profile = core.PROFILE_BY_ID.get(int(profile_id))
        if profile is None:
            return None
        shader = self.resolve_shader()
        if shader is None:
            return None
        try:
            active = core.read_active_profile(shader)
        except (core.MultiLUTError, OSError, UnicodeError):
            return None
        if active == profile.id:
            return None
        try:
            core.set_active_profile(shader, profile.id)
        except (OSError, UnicodeError, core.MultiLUTError) as exc:
            self._notify("MultiLUT: falha ao aplicar", str(exc))
            return None
        config = core.load_config()
        config["shader_path"] = str(shader)
        config["last_profile"] = profile.id
        core.save_config(config)
        core.append_history(
            {
                "profile_id": profile.id,
                "profile_name": profile.name,
                "origin": origin,
                "previous": active,
                "shader": str(shader),
                "detail": "desfazer da notificação" if origin == "undo" else "",
            }
        )
        self.events += 1
        self.record_status()
        self._notify("MultiLUT: perfil restaurado", f"{profile.id:02d} — {profile.name}")
        return {"profile_id": profile.id, "profile_name": profile.name, "changed": True}

    def _notify(self, title: str, body: str) -> None:
        self._notify_change(title, body, undo_profile_id=None)

    def _notify_change(
        self, title: str, body: str, undo_profile_id: int | None = None
    ) -> None:
        """Notificação do desktop; com botão “Desfazer” quando há perfil anterior.

        O notify-send roda com --action e --wait em thread própria: enquanto o
        usuário não interage (ou decai) o piloto segue livre; ao escolher
        “Desfazer”, o perfil anterior é reaplicado no loop principal.
        """
        if not bool(core.load_config().get("notify_changes", False)):
            return
        binary = shutil.which("notify-send")
        if not binary:
            return
        argv = [binary, *notify_send_args(title, body, undo_profile_id)[1:]]
        if undo_profile_id is None:
            try:
                subprocess.Popen(
                    argv,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError:
                pass
            return
        thread = threading.Thread(
            target=self._wait_undo, args=(argv, int(undo_profile_id)), daemon=True
        )
        thread.start()

    def _wait_undo(self, argv: list[str], undo_profile_id: int) -> None:
        try:
            outcome = subprocess.run(
                argv, capture_output=True, text=True, timeout=120
            )
        except (OSError, subprocess.TimeoutExpired):
            return
        if outcome.stdout is not None and outcome.stdout.strip() == "undo":
            GLib.idle_add(self._apply_undo_from_notification, undo_profile_id)

    def _apply_undo_from_notification(self, profile_id: int) -> bool:
        try:
            self.apply_profile_id(profile_id, origin="undo")
        except core.MultiLUTError as exc:
            self._notify("MultiLUT: desfazer falhou", str(exc))
        return GLib.SOURCE_REMOVE

    # ------------------------------------------------------------ monitor do console.log
    def start(self) -> None:
        self._ensure_monitor()
        if GLib is not None:
            # restaura o brilho DDC/CI quando o jogo fechar (checagem a 60s)
            GLib.timeout_add_seconds(60, self._watch_game_for_brightness)
        self.record_status()

    def _sync_monitor_state(self) -> None:
        """Ligado/desligado na interface ou CLI: rearma o monitor conforme o config."""
        if bool(core.load_config().get("auto_map_switch", False)):
            self._ensure_monitor()
        elif self._monitor is not None:
            self._cancel_monitor()

    def _cancel_monitor(self) -> None:
        if self._monitor is not None:
            try:
                self._monitor.cancel()
            except Exception:  # noqa: BLE001 - encerramento não pode falhar
                pass
        self._monitor = None
        self._console_path = None
        self._tail = None
        if self._debounce_id is not None and GLib is not None:
            GLib.source_remove(self._debounce_id)
        self._debounce_id = None

    def _ensure_monitor(self) -> None:
        if self._monitor is not None:
            return
        console = core.find_console_log()
        if console is None:
            return
        _require_glib()
        try:
            monitor_file = Gio.File.new_for_path(str(console))
            monitor = monitor_file.monitor_file(Gio.FileMonitorFlags.NONE, None)
            monitor.connect("changed", self._on_console_changed)
            self._monitor = monitor
            self._console_path = console
            tail = core.ConsoleTail()
            fresh = False
            try:
                stat = console.stat()
                tail.offset = stat.st_size  # ignora conteúdo antigo por padrão
                fresh = stat.st_size > 0 and (time.time() - stat.st_mtime) <= 120.0
            except OSError:
                tail.offset = 0
            self._tail = tail
        except GLib.Error:
            self._monitor = None
            self._console_path = None
            return
        self.record_status()
        if fresh:
            GLib.idle_add(self._apply_fresh_console)

    def _apply_fresh_console(self) -> bool:
        """Log (re)criado agora ou daemon iniciado com jogo rodando: pega o mapa atual."""
        path = self._console_path
        if path is None:
            return GLib.SOURCE_REMOVE
        try:
            size = path.stat().st_size
            with path.open("rb") as stream:
                stream.seek(max(0, size - core.CONSOLE_READ_BLOCK))
                data = stream.read(core.CONSOLE_READ_BLOCK)
        except OSError:
            return GLib.SOURCE_REMOVE
        parser = core.ConsoleTail()
        latest = None
        for token in parser.map_tokens(parser.feed(data)):
            latest = token
        if latest:
            self.apply_map_token(latest)
        return GLib.SOURCE_REMOVE

    def _on_console_changed(self, _monitor, _file, _other, event_type) -> None:
        if event_type in (
            Gio.FileMonitorEvent.DELETED,
            Gio.FileMonitorEvent.MOVED_OUT,
        ):
            # o jogo recria o console.log a cada boot: rearma com offset zero
            GLib.idle_add(self._rearm)
            return
        if event_type not in (
            Gio.FileMonitorEvent.CHANGES_DONE_HINT,
            Gio.FileMonitorEvent.CREATED,
            Gio.FileMonitorEvent.MOVED_IN,
            Gio.FileMonitorEvent.CHANGED,
        ):
            return
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
        self._debounce_id = GLib.timeout_add(400, self._drain_console_log)

    def _rearm(self) -> bool:
        self._cancel_monitor()
        self._ensure_monitor()
        return GLib.SOURCE_REMOVE

    def _drain_console_log(self) -> bool:
        self._debounce_id = None
        tail = self._tail
        path = self._console_path
        if tail is None or path is None:
            return GLib.SOURCE_REMOVE
        try:
            size = path.stat().st_size
            if size < tail.offset:
                tail.reset()  # truncado: o jogo recriou o arquivo
            # Orçamento de RAM por dreno: core.CONSOLE_DRAIN_BLOCKS x
            # core.CONSOLE_READ_BLOCK (16 x 256 KB = 4 MB). As linhas são
            # processadas bloco a bloco e só o último token sobrevive — nada
            # de acumular o log inteiro em memória enquanto o jogo roda.
            latest = None
            with path.open("rb") as stream:
                stream.seek(tail.offset)
                for _ in range(core.CONSOLE_DRAIN_BLOCKS):
                    data = stream.read(core.CONSOLE_READ_BLOCK)
                    if not data:
                        break
                    for token in tail.map_tokens(tail.feed(data)):
                        latest = token
        except OSError:
            return GLib.SOURCE_REMOVE
        if latest:
            self.apply_map_token(latest)
        return GLib.SOURCE_REMOVE


# ------------------------------------------------------------ guardião de memória
def memory_tick(pilot: DaemonPilot) -> str:
    """Um tique do guardião de RAM: "ok", "collect" ou "restart".

    Mantido como função de módulo para ser testável sem GLib. Com "restart"
    apenas marca o pedido; quem agenda o tique (main) faz o encerramento
    gracioso e sai com código de falha para o systemd religar o daemon.
    """
    rss = extra.read_process_rss_kib()
    action = extra.daemon_memory_policy(rss)
    if action == "collect":
        gc.collect()
    elif action == "restart":
        pilot.restart_requested = True
    return action


# ------------------------------------------------------------ verificador de atualizações
def update_tick(pilot: DaemonPilot) -> str:
    """Um tique do verificador de atualizações: "idle", "busy" ou "restart".

    O daemon roda 24/7: é ele quem garante que correções cheguem mesmo sem
    o aplicativo ser aberto. Aplica com o mesmo lock da janela e, com
    "restart", apenas marca o pedido — quem agenda o tique (main) faz o
    encerramento gracioso e sai com código de falha para o systemd religar
    o daemon já no código novo. Função de módulo para ser testável sem
    GLib nem rede.
    """
    if not bool(core.load_config().get("check_updates", True)):
        return "idle"
    if core.read_update_generation() != core.process_update_generation():
        # outro componente (janela ou install.sh) aplicou código novo:
        # religar já traz o código novo; rede nem é necessária
        pilot.restart_requested = True
        return "restart"
    result = core.check_for_updates()
    if result.get("status") != "available":
        return "idle"
    if not core.acquire_update_lock():
        return "busy"  # a janela está aplicando; a próxima verificação decide
    try:
        applied = core.apply_update()
    finally:
        core.release_update_lock()
    if applied.get("ok") and applied.get("new_head") != applied.get("old_head"):
        pilot.restart_requested = True
        return "restart"
    return "idle"


class ControlServer:
    """Socket UNIX JSON-por-linha; uma requisição por conexão."""

    def __init__(self, pilot: DaemonPilot, socket_path: Path | None = None) -> None:
        self.pilot = pilot
        self.socket_path = Path(socket_path) if socket_path else extra.daemon_socket_path()
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self.on_stop = None  # callback chamado quando chega {"cmd": "stop"}

    def start(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self.socket_path.exists():
                self.socket_path.unlink()  # socket órfão de execução anterior
        except OSError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        os.chmod(self.socket_path, 0o600)
        server.listen(4)
        self._server = server
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()

    def serve_forever(self) -> None:
        server = self._server
        if server is None:
            return
        while True:
            try:
                connection, _ = server.accept()
            except OSError:
                break  # socket fechado no encerramento
            with connection:
                try:
                    connection.settimeout(5.0)
                    raw = connection.recv(8192)
                    payload = json.loads(raw.decode("utf-8", errors="ignore").strip())
                    reply = self.pilot.handle_command(payload)
                except (ValueError, OSError) as exc:
                    reply = {"error": f"requisição inválida: {exc}"}
                try:
                    connection.sendall(
                        (json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8")
                    )
                except OSError:
                    pass
                if isinstance(reply, dict) and reply.get("ok") and reply.get("message") == "encerrando":
                    if self.on_stop is not None:
                        self.on_stop()
                    break

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None
        try:
            if self.socket_path.exists():
                self.socket_path.unlink()
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    _require_glib()
    argv = list(sys.argv[1:] if argv is None else argv)
    socket_override = None
    if "--socket" in argv:
        index = argv.index("--socket")
        if index + 1 < len(argv):
            socket_override = Path(argv[index + 1])

    if extra.query_daemon() is not None:
        print("MultiLUT daemon já está em execução; nada a fazer.", file=sys.stderr)
        return 1

    pilot = DaemonPilot()
    server = ControlServer(pilot, socket_override)
    loop = GLib.MainLoop()

    def request_stop(_signal_number=None) -> None:
        GLib.idle_add(shutdown)

    def shutdown() -> bool:
        pilot._cancel_monitor()
        try:
            pilot.brightness.restore(reason="daemon encerrado")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        pilot.record_status_stopped()
        server.stop()
        loop.quit()
        return GLib.SOURCE_REMOVE

    def watch_memory() -> bool:
        """Tique do guardião de RAM: sai com falha se o processo inflar.

        O systemd (Restart=on-failure) religa o daemon limpo em segundos;
        assim o monitor nunca chega a disputar RAM com o jogo.
        """
        if memory_tick(pilot) == "restart":
            GLib.idle_add(shutdown)
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def watch_updates() -> bool:
        """Verificação de atualizações com a rede fora do loop principal.

        Primeira checagem 2 min após o arranque e depois a cada
        core.UPDATE_RECHECK_SECONDS. Com "restart", encerra gracioso para
        o systemd religar o daemon no código novo — é assim que correções
        chegam sozinhas mesmo sem o aplicativo nunca ser aberto.
        """
        def worker() -> None:
            try:
                action = update_tick(pilot)
            except Exception:  # noqa: BLE001 - rede/trabalho nunca derruba o daemon
                return
            if action == "restart":
                GLib.idle_add(shutdown)

        threading.Thread(target=worker, daemon=True).start()
        GLib.timeout_add_seconds(core.UPDATE_RECHECK_SECONDS, watch_updates)
        return GLib.SOURCE_REMOVE

    server.on_stop = lambda: GLib.idle_add(shutdown)
    for signal_number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(signal_number, request_stop)
        except (ValueError, OSError):
            continue

    server.start()
    pilot.start()
    core.process_update_generation()  # fixa a geração do código no arranque
    GLib.timeout_add_seconds(60, watch_memory)
    GLib.timeout_add_seconds(120, watch_updates)
    print(
        f"MultiLUT daemon ativo (pid {os.getpid()}); socket: {server.socket_path}",
        flush=True,
    )
    try:
        loop.run()
    except KeyboardInterrupt:
        shutdown()
    return 1 if pilot.restart_requested else 0


def notify_send_args(
    title: str, body: str, undo_profile_id: int | None = None
) -> list[str]:
    """argv do notify-send (sem o binário); com --action/--wait quando há desfazer.

    Mantido como função de módulo para ser testável sem GLib nem notificações
    reais: o botão “Desfazer” usa a ação nomeada ``undo`` e o --wait faz o
    notify-send imprimir a ação escolhida (ou sair quando a notificação some).
    """
    argv = [
        "-a",
        "MultiLUT Controller",
        "-i",
        "com.felipesantiago.MultiLUTController",
    ]
    if undo_profile_id is not None:
        argv += ["--action=undo=Desfazer", "--wait"]
    argv += [title, body]
    return argv


if __name__ == "__main__":
    raise SystemExit(main())
