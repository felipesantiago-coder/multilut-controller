#!/usr/bin/env python3
"""CLI headless do MultiLUT Controller (sem GTK) — automação e atalhos.

Uso:
  multilut-ctl list                    Lista os perfis conhecidos
  multilut-ctl set <id|nome|slug>      Aplica um perfil (ex.: set buhriz)
  multilut-ctl next [--anterior]       Aplica o próximo (ou anterior) perfil
  multilut-ctl active                  Mostra o perfil ativo
  multilut-ctl status                  Estado do shader, do perfil e do jogo
  multilut-ctl doctor [--json] [--export CAMINHO]
                                       Diagnóstico completo (código 1 se falha);
                                       exportável em .txt ou .zip
  multilut-ctl history [--limit N]     Últimas trocas registradas
  multilut-ctl preview <id|nome|slug>  Simula o perfil sobre a foto de um mapa
  multilut-ctl rows                    Lista as linhas do atlas e quem as usa
  multilut-ctl atlas <linha> <arquivo> Substitui a linha do atlas por um .cube
  multilut-ctl reindex <perfil> <linha>  Aponta o perfil para outra linha
  multilut-ctl daemon status|start|stop|install|uninstall
                                       Piloto automático como serviço sem janela
  multilut-ctl autostart on|off|status Inicia o app com a sessão (janela oculta)
  multilut-ctl update check|apply      Verifica/aplica atualização via git

Opções comuns:
  --shader CAMINHO    Shader .fx alternativo (padrão: config ou candidato)
  --no-history        Não registrar a troca no histórico local (set/next)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _ensure_module_path() -> None:
    """Cópia instalada em ~/.local/bin: módulos irmãos ficam no diretório do app."""
    here = Path(__file__).resolve().parent
    candidates = (
        here,
        here.parent / "multilut-controller",
        here / "multilut-controller",
    )
    for candidate in candidates:
        if (candidate / "multilut_core.py").is_file():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            return


_ensure_module_path()

import multilut_core as core  # noqa: E402


def resolve_shader(explicit: str | None) -> Path:
    """Shader ativo: --shader, config, candidatos, padrão."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    remembered = core.load_config().get("shader_path")
    if isinstance(remembered, str) and remembered.strip():
        candidates.append(Path(remembered).expanduser())
    candidates.extend(core.find_shader_candidates())
    candidates.append(core.default_shader_path())
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file():
            valid, _ = core.validate_shader(candidate)
            if valid:
                return candidate
    raise core.MultiLUTError(
        "Shader do MultiLUT não encontrado ou inválido; informe --shader."
    )


def match_profile(token: str) -> core.Profile:
    """Casamento por id, nome exato (sem acentos) ou slug de mapa."""
    text = str(token).strip()
    if not text:
        raise core.MultiLUTError("Perfil vazio.")
    if text.isdigit():
        profile_id = int(text)
        if profile_id in core.PROFILE_BY_ID:
            return core.PROFILE_BY_ID[profile_id]
        raise core.MultiLUTError(f"Perfil inexistente: {profile_id}")
    decomposed = core.unicodedata.normalize("NFKD", text)
    flat = "".join(ch for ch in decomposed if not core.unicodedata.combining(ch))
    folded = flat.casefold()
    slug = core.re.sub(r"[^a-z0-9]", "", folded)
    for profile in core.PROFILES:
        if profile.name.casefold() == folded:
            return profile
    for profile in core.PROFILES:
        if core.map_image_slug(profile) == slug and slug:
            return profile
    raise core.MultiLUTError(
        f"Perfil não reconhecido: {token!r}; use 'list' para ver os nomes."
    )


def cmd_list(args: argparse.Namespace) -> int:
    for profile in core.profiles_alphabetical():
        marker = "*" if profile.id == core.read_active_profile(
            resolve_shader(args.shader)
        ) else " "
        print(f"{marker} {profile.id:02d}  [{profile.category}] {profile.name}")
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    profile = match_profile(args.target)
    shader = resolve_shader(args.shader)
    previous = core.set_active_profile(shader, profile.id)
    if previous != profile.id:
        if not args.no_history:
            core.append_history(
                {
                    "profile_id": profile.id,
                    "profile_name": profile.name,
                    "origin": "cli",
                    "previous": previous,
                    "shader": str(shader),
                }
            )
    print(f"Perfil ativo {profile.id:02d} — {profile.name} ({shader})")
    return 0


def cmd_active(args: argparse.Namespace) -> int:
    shader = resolve_shader(args.shader)
    profile_id = core.read_active_profile(shader)
    profile = core.PROFILE_BY_ID[profile_id]
    print(f"{profile.id:02d} — {profile.name} ({shader})")
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    """Aplica o próximo (ou anterior) perfil, ciclando 0..24 — igual ao atalho."""
    shader = resolve_shader(args.shader)
    current = core.read_active_profile(shader)
    target = core.next_profile_id(current, -1 if args.anterior else 1)
    profile = core.PROFILE_BY_ID[target]
    previous = core.set_active_profile(shader, profile.id)
    if previous != profile.id and not args.no_history:
        core.append_history(
            {
                "profile_id": profile.id,
                "profile_name": profile.name,
                "origin": "cli",
                "previous": previous,
                "shader": str(shader),
            }
        )
    print(f"Perfil ativo {profile.id:02d} — {profile.name} ({shader})")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    limit = max(1, min(args.limit, 1000))
    entries = core.read_history(limit=limit)
    if not entries:
        print("Histórico vazio.")
        return 0
    for entry in entries:
        ts = str(entry.get("ts") or "?")
        profile_id = entry.get("profile_id")
        name = str(entry.get("profile_name") or "?")
        origin = str(entry.get("origin") or "?")
        if isinstance(profile_id, int):
            head = f"{profile_id:02d} — {name}"
        else:
            head = f"{profile_id} — {name}"
        print(f"{ts}  {head}  [{origin}]")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Checklist de diagnóstico completo no terminal (mesma fonte da página Sistema)."""
    import multilut_extra as extra

    report = extra.diagnostic_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        labels = {"ok": "ok   ", "warn": "aviso", "fail": "FALHA", "info": "info "}
        for item in report:
            state = str(item.get("state") or "?")
            title = str(item.get("title") or "?")
            detail = str(item.get("detail") or "")
            print(f"[{labels.get(state, state)}] {title}: {detail}")
        has_fail = any(item.get("state") == "fail" for item in report)
        print(
            "\nDiagnóstico concluído com "
            + ("FALHAS — revise os itens acima." if has_fail else "nenhuma falha.")
        )
    if args.export:
        try:
            summary = extra.export_diagnostic_report(Path(args.export).expanduser())
        except OSError as exc:
            print(f"Erro ao exportar o relatório: {exc}", file=sys.stderr)
            return 2
        kind = "zip" if summary["zip"] else "texto"
        print(f"Relatório de diagnóstico ({kind}) salvo em: {summary['path']}")
    return 1 if any(item.get("state") == "fail" for item in report) else 0


def cmd_daemon(args: argparse.Namespace) -> int:
    """Controla o piloto automático como serviço de usuário (sem janela)."""
    import multilut_extra as extra

    action = args.acao
    if action == "status":
        status = extra.daemon_status()
        alive = bool(status.get("alive"))
        print(f"daemon: {'ativo' if alive else 'parado'}")
        for key in (
            "pid",
            "started_at",
            "auto_map_switch",
            "console_log",
            "events",
        ):
            if status.get(key) is not None:
                print(f"{key}: {status[key]}")
        last = status.get("last_map")
        if isinstance(last, dict) and last.get("token"):
            print(
                f"last_map: {last.get('token')} -> "
                f"{last.get('profile_id')} — {last.get('profile_name')} ({last.get('ts')})"
            )
        if not alive and extra.daemon_unit_installed():
            print("serviço: instalado; inicie com multilut-ctl daemon start")
        elif not alive:
            print("serviço: não instalado (multilut-ctl daemon install)")
        return 0 if alive else 1
    if action == "start":
        ok, message = extra.daemon_start()
        print(message)
        return 0 if ok else 1
    if action == "stop":
        ok, message = extra.daemon_stop()
        print(message)
        return 0 if ok else 1
    if action == "install":
        unit = extra.daemon_install_unit()
        print(f"Serviço instalado: {unit}")
        ok, message = extra.daemon_start()
        print(message)
        return 0 if ok else 1
    if action == "uninstall":
        if extra.daemon_uninstall_unit():
            print("Serviço removido e daemon parado.")
        else:
            print("O serviço não estava instalado.")
        return 0
    raise core.MultiLUTError(f"Ação de daemon desconhecida: {action!r}")


def cmd_autostart(args: argparse.Namespace) -> int:
    """Inicia o aplicativo com a sessão (XDG autostart, janela oculta)."""
    import multilut_extra as extra

    action = args.acao
    if action == "status":
        if extra.autostart_installed():
            print(f"autostart: ativado ({extra.autostart_path()})")
        else:
            print("autostart: desativado; ligue com multilut-ctl autostart on")
        return 0
    if action == "on":
        target = extra.autostart_install(minimized=True)
        config = core.load_config()
        config["autostart_minimized"] = True
        core.save_config(config)
        print(f"Autostart ativado: {target} (inicia oculto; use autostart off para desligar)")
        return 0
    if action == "off":
        removed = extra.autostart_remove()
        config = core.load_config()
        config["autostart_minimized"] = False
        core.save_config(config)
        print("Autostart desativado." if removed else "Autostart já estava desativado.")
        return 0
    raise core.MultiLUTError(f"Ação de autostart desconhecida: {action!r}")


def cmd_update(args: argparse.Namespace) -> int:
    """Verifica ou aplica a atualização do aplicativo (instalação via git)."""
    if args.acao == "check":
        local = core.local_git_head() or "sem git"
        print(f"versão instalada: v{core.APP_VERSION} ({local})")
        release = core.fetch_latest_release()
        if release is None:
            remote = core.git_remote_head()
            if remote is None:
                print("Não foi possível consultar o GitHub agora.")
                return 2
            print("Sem release publicada; comparando commit do main...")
            print(f"main remoto: {remote[:7]}")
            if core.local_git_head() and remote.startswith(core.local_git_head()):
                print("Você já está no main mais recente.")
            else:
                print("Há commits novos no main; use multilut-ctl update apply.")
            return 0
        if core.compare_versions(release["tag"], core.APP_VERSION):
            print(f"Atualização disponível: {release['tag']} — {release['url']}")
            print("Aplique com multilut-ctl update apply.")
            return 1
        print("Você já está na versão mais recente.")
        return 0
    result = core.apply_update()
    print(result["message"])
    return 0 if result["ok"] else 1


def cmd_status(args: argparse.Namespace) -> int:
    shader = resolve_shader(args.shader)
    valid, message = core.validate_shader(shader)
    print(f"shader: {shader}")
    print(f"shader_ok: {str(valid).lower()}")
    print(f"detail: {message}")
    print(f"game_running: {str(core.is_game_running()).lower()}")
    console = core.find_console_log()
    print(f"console_log: {console if console is not None else 'ausente (-condebug?)'}")
    return 0 if valid else 1


def resolve_atlas(explicit: str | None) -> Path:
    """Atlas v1.8: --atlas, textura instalada válida ou pacote do app."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    installed = core.default_texture_path()
    if installed.is_file():
        candidates.append(installed)
    module_dir = Path(core.__file__).resolve().parent
    candidates.append(
        module_dir / "bundle/Textures/MultiLut_Insurgency_Optimized.png"
    )
    for candidate in candidates:
        if candidate.is_file():
            valid, _ = core.validate_texture(candidate)
            if valid:
                return candidate
    raise core.MultiLUTError(
        "Atlas do MultiLUT não encontrado; use --atlas ou instale o pacote v1.8."
    )


def cmd_preview(args: argparse.Namespace) -> int:
    try:
        import multilut_preview as preview
    except ImportError as exc:  # pragma: no cover - instalação incompleta
        print(f"Erro: módulo de simulação ausente ({exc}).", file=sys.stderr)
        return 1
    if not preview.DEPENDENCIES_AVAILABLE:
        print(
            "Erro: a simulação requer numpy e Pillow "
            "(no Solus: sudo eopkg it numpy python-pillow).",
            file=sys.stderr,
        )
        return 1
    resolution = args.resolucao
    if resolution is None:  # configuração do aplicativo, quando válida
        config = core.load_config()
        try:
            resolution = (
                int(config.get("game_width")),
                int(config.get("game_height")),
            )
        except (TypeError, ValueError):
            resolution = None
    profile = match_profile(args.target)
    shader = resolve_shader(args.shader)
    atlas = resolve_atlas(args.atlas)
    slug = args.mapa or core.map_image_slug(profile)
    if not slug:
        raise core.MultiLUTError(
            "Perfil sem mapa próprio; informe --mapa (ex.: --mapa sinjar)."
        )
    module_dir = Path(core.__file__).resolve().parent
    source = module_dir / "assets/maps" / f"{slug}.jpg"
    if not source.is_file():
        raise core.MultiLUTError(f"Foto do mapa não encontrada: {source}")
    result = preview.render_preview(
        profile.id, source, atlas, shader, game_resolution=resolution
    )
    composed = preview.compose_side_by_side(result["original"], result["simulated"])
    output = Path(args.saida).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(preview.png_bytes(composed))
    resolved_w, resolved_h = result["game_resolution"]
    print(f"Perfil {profile.id:02d} — {profile.name}")
    print(f"  base: {source.name}  atlas: {atlas}")
    print(
        f"  resolução do jogo: {resolved_w}x{resolved_h} "
        "(raio do contraste local escalado)"
    )
    print(f"  simulado em {result['elapsed_ms']:.0f} ms -> {output}")
    return 0


def cmd_rows(args: argparse.Namespace) -> int:
    import multilut_atlas as atlas_mod

    shader = resolve_shader(args.shader)
    mapping = atlas_mod.parse_lut_row_map(shader.read_text(encoding="utf-8"))
    owners = atlas_mod.row_owner_profiles(mapping)
    print(f"Atlas v1.8: {core.ATLAS_SLICES} fatias x {core.ATLAS_ROWS} linhas ({shader})")
    for row in range(core.ATLAS_ROWS):
        used = ", ".join(f"{owner:02d}" for owner in owners[row]) or "-"
        print(
            f"linha {row:2d}  {core.PROFILE_BY_ID[row].name:34s} perfis: {used}"
        )
    return 0


def cmd_atlas(args: argparse.Namespace) -> int:
    import multilut_atlas as atlas_mod

    if not atlas_mod.DEPENDENCIES_AVAILABLE:
        print(
            "Erro: o override com .cube requer numpy e Pillow "
            "(no Solus: sudo eopkg it numpy python-pillow).",
            file=sys.stderr,
        )
        return 1
    target = (
        Path(args.atlas).expanduser() if args.atlas else core.default_texture_path()
    )
    info = atlas_mod.override_row_with_cube(target, args.linha, args.cube)
    print(
        f"Linha {info['row']} do atlas {target} substituída por "
        f"{args.cube} ({info['cube_size']}³ reamostrada para 32³)"
    )
    if info["backup"]:
        print(f"  backup: {info['backup']}")
    return 0


def cmd_reindex(args: argparse.Namespace) -> int:
    import multilut_atlas as atlas_mod

    shader = resolve_shader(args.shader)
    if args.reset:
        info = atlas_mod.reset_lut_row_map(shader)
        if not info["changed"]:
            print("O mapeamento já está no padrão do shader v1.8.")
        else:
            print(f"Mapeamento perfil -> linha restaurado ao padrão ({shader}).")
        return 0
    if args.perfil is None or args.linha is None:
        raise core.MultiLUTError(
            "Informe o perfil e a linha de destino (0 a 16), ou use --reset."
        )
    profile = match_profile(args.perfil)
    info = atlas_mod.reindex_profile(shader, profile.id, args.linha)
    if not info["changed"]:
        print(f"Perfil {profile.id:02d} — {profile.name} já usa a linha {args.linha}.")
    else:
        print(
            f"Perfil {profile.id:02d} — {profile.name}: linha "
            f"{info['previous_row']} -> {args.linha} ({shader})"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--shader", help="caminho do shader .fx alternativo")
    parser = argparse.ArgumentParser(
        prog="multilut-ctl",
        description="Controla o MultiLUT Insurgency sem abrir a interface.",
        parents=[common],
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser(
        "list", parents=[common], help="lista os perfis"
    )
    list_parser.set_defaults(func=cmd_list)

    set_parser = subparsers.add_parser("set", parents=[common], help="aplica um perfil")
    set_parser.add_argument("target", help="id, nome ou slug (ex.: 14, buhriz)")
    set_parser.add_argument(
        "--no-history", action="store_true", help="não registrar no histórico"
    )
    set_parser.set_defaults(func=cmd_set)

    active_parser = subparsers.add_parser(
        "active", parents=[common], help="mostra o perfil ativo"
    )
    active_parser.set_defaults(func=cmd_active)

    next_parser = subparsers.add_parser(
        "next",
        parents=[common],
        help="aplica o próximo perfil (ciclo 0 a 24; --anterior volta)",
    )
    next_parser.add_argument(
        "--anterior",
        action="store_true",
        help="aplica o perfil anterior em vez do próximo",
    )
    next_parser.add_argument(
        "--no-history", action="store_true", help="não registrar no histórico"
    )
    next_parser.set_defaults(func=cmd_next)

    doctor_parser = subparsers.add_parser(
        "doctor",
        parents=[common],
        help="checklist de diagnóstico completo (código 1 quando há falha)",
    )
    doctor_parser.add_argument(
        "--json", action="store_true", help="saída em JSON para automação"
    )
    doctor_parser.add_argument(
        "--export",
        metavar="CAMINHO",
        help="salva o relatório completo (.txt) ou pacote (.zip) para uma issue",
    )
    doctor_parser.set_defaults(func=cmd_doctor)

    history_parser = subparsers.add_parser(
        "history",
        parents=[common],
        help="mostra as últimas trocas registradas",
    )
    history_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="quantidade de entradas (padrão: 20)",
    )
    history_parser.set_defaults(func=cmd_history)

    status_parser = subparsers.add_parser(
        "status", parents=[common], help="diagnóstico rápido"
    )
    status_parser.set_defaults(func=cmd_status)

    preview_parser = subparsers.add_parser(
        "preview",
        parents=[common],
        help="simula o perfil sobre a foto de um mapa",
    )
    preview_parser.add_argument("target", help="id, nome ou slug (ex.: 14, buhriz)")
    preview_parser.add_argument(
        "--mapa", help="slug do mapa para a foto (padrão: mapa do próprio perfil)"
    )
    preview_parser.add_argument(
        "--atlas", help="PNG do atlas v1.8 alternativo (padrão: instalado ou pacote)"
    )
    preview_parser.add_argument(
        "--resolucao",
        help="resolução de render do jogo (ex.: 1366x768); escala o contraste local",
    )
    preview_parser.add_argument(
        "--saida", "-o", default="multilut_preview.png", help="PNG de saída"
    )
    preview_parser.set_defaults(func=cmd_preview)

    rows_parser = subparsers.add_parser(
        "rows", parents=[common], help="lista as linhas do atlas e quem as usa"
    )
    rows_parser.set_defaults(func=cmd_rows)

    atlas_parser = subparsers.add_parser(
        "atlas",
        parents=[common],
        help="substitui a linha do atlas por uma LUT .cube",
    )
    atlas_parser.add_argument("linha", type=int, help="linha do atlas (0 a 16)")
    atlas_parser.add_argument("cube", help="arquivo .cube com a LUT 3D")
    atlas_parser.add_argument(
        "--atlas", help="PNG do atlas alvo (padrão: instalado ou pacote)"
    )
    atlas_parser.set_defaults(func=cmd_atlas)

    reindex_parser = subparsers.add_parser(
        "reindex",
        parents=[common],
        help="aponta um perfil para outra linha do atlas (P_LUT_ROW)",
    )
    reindex_parser.add_argument(
        "perfil", nargs="?", default=None, help="id, nome ou slug do perfil"
    )
    reindex_parser.add_argument(
        "linha", nargs="?", type=int, default=None, help="linha de destino (0 a 16)"
    )
    reindex_parser.add_argument(
        "--reset", action="store_true", help="restaura o mapeamento padrão v1.8"
    )
    reindex_parser.set_defaults(func=cmd_reindex)

    daemon_parser = subparsers.add_parser(
        "daemon",
        parents=[common],
        help="piloto automático como serviço de usuário (sem janela)",
    )
    daemon_parser.add_argument(
        "acao",
        choices=("status", "start", "stop", "install", "uninstall"),
        help="status | start | stop | install (serviço systemd) | uninstall",
    )
    daemon_parser.set_defaults(func=cmd_daemon)

    autostart_parser = subparsers.add_parser(
        "autostart",
        parents=[common],
        help="inicia o app com a sessão (janela oculta)",
    )
    autostart_parser.add_argument(
        "acao", choices=("on", "off", "status"), help="liga, desliga ou mostra"
    )
    autostart_parser.set_defaults(func=cmd_autostart)

    update_parser = subparsers.add_parser(
        "update",
        parents=[common],
        help="verifica ou aplica atualização do aplicativo via git",
    )
    update_parser.add_argument(
        "acao", choices=("check", "apply"), help="check consulta; apply atualiza"
    )
    update_parser.set_defaults(func=cmd_update)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except core.MultiLUTError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        # Broken pipe (ex.: multilut-ctl list | head) não é falha real
        if isinstance(exc, BrokenPipeError):
            return 0
        print(f"Erro de sistema: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
