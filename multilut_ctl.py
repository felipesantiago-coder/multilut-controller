#!/usr/bin/env python3
"""CLI headless do MultiLUT Controller (sem GTK) — automação e atalhos.

Uso:
  multilut-ctl list                    Lista os perfis conhecidos
  multilut-ctl set <id|nome|slug>      Aplica um perfil (ex.: set buhriz)
  multilut-ctl active                  Mostra o perfil ativo
  multilut-ctl status                  Estado do shader, do perfil e do jogo

Opções comuns:
  --shader CAMINHO    Shader .fx alternativo (padrão: config ou candidato)
  --no-history        Não registrar a troca no histórico local
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import multilut_core as core


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

    status_parser = subparsers.add_parser(
        "status", parents=[common], help="diagnóstico rápido"
    )
    status_parser.set_defaults(func=cmd_status)
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
