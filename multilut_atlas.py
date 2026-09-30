#!/usr/bin/env python3
"""Reindexação e override do atlas v1.8 (Lote 2).

Duas operações sobre o pacote MultiLUT instalado:

- Override de linha: substitui a LUT de uma das 17 linhas do atlas
  ``MultiLut_Insurgency_Optimized.png`` (1024x544, 32 fatias x 17 linhas de
  tiles 32x32) por uma LUT 3D de um arquivo ``.cube`` — interpretado,
  reamostrado para 32^3 por trilinear e codificado no mesmo layout do shader
  (fatia = azul, coluna = vermelho, linha vertical = verde). A gravação é
  atômica, com backup ``.bak`` do atlas anterior.

- Reindexação: altera o mapeamento perfil -> linha (P_LUT_ROW) dentro do
  shader .fx instalado, permitindo apontar qualquer perfil para qualquer
  linha sem editar o shader à mão. O bloco é reescrito de forma completa e
  verificada, com backup.

Dependências opcionais: numpy e Pillow (necessários só para as operações de
imagem; a reindexação é puramente textual). Sem elas nada quebra no import.
"""

from __future__ import annotations

from pathlib import Path
import os
import re
import shutil
import tempfile

import multilut_core as core

try:
    import numpy as np
    from PIL import Image
except ImportError:  # pragma: no cover - ambiente sem as dependências opcionais
    np = None
    Image = None

DEPENDENCIES_AVAILABLE = np is not None and Image is not None

ATLAS_TILE = core.ATLAS_TILE
ATLAS_SLICES = core.ATLAS_SLICES
ATLAS_ROWS = core.ATLAS_ROWS
ATLAS_SIZE = core.ATLAS_SIZE
STRIP_WIDTH = ATLAS_SLICES * ATLAS_TILE  # 1024

BUNDLE_TEXTURE = "Textures/MultiLut_Insurgency_Optimized.png"


class AtlasError(core.MultiLUTError):
    """Erro user-facing das operações de atlas e reindexação."""


# --------------------------------------------------------------------------
# Parser de .cube (LUT 3D)
# --------------------------------------------------------------------------
_SIZE_RE = re.compile(r"^\s*LUT_3D_SIZE\s+(\d+)\s*$", re.IGNORECASE)
_1D_SIZE_RE = re.compile(r"^\s*LUT_1D_SIZE\s+(\d+)\s*$", re.IGNORECASE)
_INPUT_RANGE_RE = re.compile(
    r"^\s*LUT_3D_INPUT_RANGE\s+(\S+)\s+(\S+)\s*$", re.IGNORECASE
)
_FLOAT_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
MAX_CUBE_SIZE = 256


def parse_cube_text(text: str, source: str = "") -> dict:
    """Lê uma LUT 3D em formato .cube e devolve a tabela em [0, 1].

    O formato oficial armazena a tabela com o vermelho variando mais rápido;
    a tabela é devolvida como ndarray (N, N, N, 3) indexado [b, g, r].
    ``LUT_3D_INPUT_RANGE`` remapeia os valores de entrada; ``DOMAIN_MIN/MAX``
    de saída é aceito e ignorado (assumido 0-1), comportamento comum das
    ferramentas que exportam .cube.
    """
    if np is None:
        raise AtlasError(
            "Override com .cube requer numpy e Pillow "
            "(no Solus: sudo eopkg it python3-numpy python3-pillow)."
        )
    label = f" ({source})" if source else ""
    size: int | None = None
    title: str | None = None
    input_lo, input_hi = 0.0, 1.0
    values: list[tuple[float, float, float]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lowered = line.lower()
        if lowered.startswith("title"):
            title = line[5:].strip().strip('"')
            continue
        if lowered.startswith("domain_min") or lowered.startswith("domain_max"):
            continue
        one_d = _1D_SIZE_RE.match(line)
        if one_d:
            raise AtlasError(
                f"O arquivo .cube{label} contém uma LUT 1D (LUT_1D_SIZE); "
                "o atlas v1.8 usa LUTs 3D."
            )
        size_match = _SIZE_RE.match(line)
        if size_match:
            size = int(size_match.group(1))
            continue
        range_match = _INPUT_RANGE_RE.match(line)
        if range_match:
            try:
                input_lo = float(_FLOAT_RE.match(range_match.group(1)).group(0))
                input_hi = float(_FLOAT_RE.match(range_match.group(2)).group(0))
            except (AttributeError, ValueError) as exc:
                raise AtlasError(
                    f"LUT_3D_INPUT_RANGE inválida no arquivo .cube{label}."
                ) from exc
            continue
        numbers = _FLOAT_RE.findall(line)
        if len(numbers) != 3:
            raise AtlasError(f"Linha não reconhecida no .cube{label}: {line!r}")
        try:
            values.append(tuple(float(item) for item in numbers))
        except ValueError as exc:
            raise AtlasError(f"Valor inválido no .cube{label}: {line!r}") from exc

    if size is None:
        raise AtlasError(
            f"O arquivo .cube{label} não declara LUT_3D_SIZE."
        )
    if not 2 <= size <= MAX_CUBE_SIZE:
        raise AtlasError(
            f"LUT_3D_SIZE fora do intervalo suportado (2 a {MAX_CUBE_SIZE}): {size}."
        )
    expected = size ** 3
    if len(values) != expected:
        raise AtlasError(
            f"Tabela do .cube{label} incompleta: {len(values)} de "
            f"{expected} entradas (LUT_3D_SIZE {size})."
        )
    table = np.asarray(values, dtype=np.float32).reshape(size, size, size, 3)
    if input_hi <= input_lo:
        raise AtlasError(f"LUT_3D_INPUT_RANGE inválida no .cube{label}.")
    if (input_lo, input_hi) != (0.0, 1.0):
        table = (table - input_lo) / (input_hi - input_lo)
    return {
        "size": size,
        "table": np.clip(table, 0.0, 1.0).astype(np.float32),
        "title": title,
        "input_range": (input_lo, input_hi),
    }


def parse_cube_file(path: Path | str) -> dict:
    """Lê o arquivo .cube do disco (texto em UTF-8 tolerante)."""
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise AtlasError(f"Não foi possível abrir o .cube: {target}") from exc
    return parse_cube_text(text, source=target.name)


# --------------------------------------------------------------------------
# Reamostragem e codificação no layout do atlas
# --------------------------------------------------------------------------
def _trilinear(table: "np.ndarray", r: "np.ndarray", g: "np.ndarray", b: "np.ndarray"):
    """Amostragem trilinear da tabela (b, g, r) em coordenadas de grade."""
    last = table.shape[0] - 1

    def axis(value: "np.ndarray"):
        base = np.floor(value)
        i0 = np.clip(base.astype(np.intp), 0, last)
        i1 = np.clip(i0 + 1, 0, last)
        return i0, i1, (value - base)[..., None]

    r0, r1, fr = axis(r)
    g0, g1, fg = axis(g)
    b0, b1, fb = axis(b)

    c000 = table[b0, g0, r0]
    c100 = table[b1, g0, r0]
    c010 = table[b0, g1, r0]
    c110 = table[b1, g1, r0]
    c001 = table[b0, g0, r1]
    c101 = table[b1, g0, r1]
    c011 = table[b0, g1, r1]
    c111 = table[b1, g1, r1]

    c00 = c000 + (c001 - c000) * fr
    c10 = c010 + (c011 - c010) * fr
    c01 = c100 + (c101 - c100) * fr
    c11 = c110 + (c111 - c110) * fr
    c0 = c00 + (c10 - c00) * fg
    c1 = c01 + (c11 - c01) * fg
    return c0 + (c1 - c0) * fb


def resample_lut(table: "np.ndarray", target_size: int = ATLAS_TILE) -> "np.ndarray":
    """Reamostra a LUT (N, N, N, 3) para o grid alvo (32^3) por trilinear.

    O índice i do grid alvo corresponde à cor de entrada i/(alvo-1), a mesma
    convenção do shader (color * (N-1)); na tabela de origem isso cai em
    i/(alvo-1) * (N-1).
    """
    if np is None:
        raise AtlasError(
            "Reamostragem requer numpy e Pillow "
            "(no Solus: sudo eopkg it python3-numpy python3-pillow)."
        )
    source_size = table.shape[0]
    if table.ndim != 4 or table.shape[1] != source_size or table.shape[2] != source_size:
        raise AtlasError("Tabela da LUT com formato inesperado.")
    if source_size == target_size:
        return table.astype(np.float32, copy=True)
    axis = np.arange(target_size, dtype=np.float32) / (target_size - 1)
    coords = axis * (source_size - 1)
    r = coords[None, None, :]
    g = coords[None, :, None]
    b = coords[:, None, None]
    return _trilinear(
        table.astype(np.float32), np.broadcast_to(r, (target_size,) * 3),
        np.broadcast_to(g, (target_size,) * 3),
        np.broadcast_to(b, (target_size,) * 3),
    ).astype(np.float32)


def strip_image_from_cube(cube: dict) -> "Image.Image":
    """Codifica a LUT do .cube (reamostrada para 32^3) na faixa do atlas.

    Layout confirmado no shader: a linha vertical do tile é o verde, a coluna
    dentro da fatia é o vermelho e a fatia horizontal é o azul —
    strip[y, x] = lut[b, g, r] com x = b * 32 + r.
    """
    lut = resample_lut(cube["table"], ATLAS_TILE)
    tiles = np.transpose(lut, (1, 0, 2, 3))  # (b, g, r) -> (g, b, r)
    strip = tiles.reshape(ATLAS_TILE, STRIP_WIDTH, 3)
    pixels = (np.clip(strip, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    return Image.fromarray(pixels, "RGB")


# --------------------------------------------------------------------------
# Cirurgia do atlas PNG
# --------------------------------------------------------------------------
def load_atlas_image(path: Path | str) -> "Image.Image":
    """Abre o atlas validando a geometria v1.8 (1024x544)."""
    valid, message = core.validate_texture(path)
    if not valid:
        raise AtlasError(message)
    try:
        return Image.open(path).convert("RGB")
    except (OSError, ValueError) as exc:
        raise AtlasError(f"Não foi possível abrir o atlas: {path}") from exc


def validate_row(row: int) -> int:
    """Aceita apenas linhas existentes do atlas v1.8 (0 a 16)."""
    try:
        row = int(row)
    except (TypeError, ValueError) as exc:
        raise AtlasError(f"Linha inválida: {row!r}.") from exc
    if not 0 <= row < ATLAS_ROWS:
        raise AtlasError(
            f"Linha fora do atlas v1.8 (0 a {ATLAS_ROWS - 1}): {row}."
        )
    return row


def atlas_with_replaced_row(
    atlas: "Image.Image", row: int, strip: "Image.Image"
) -> "Image.Image":
    """Cópia do atlas com a linha substituída pela faixa 1024x32."""
    row = validate_row(row)
    if strip.size != (STRIP_WIDTH, ATLAS_TILE):
        raise AtlasError(
            f"Faixa com geometria inesperada: {strip.size[0]}x{strip.size[1]} "
            f"(esperado {STRIP_WIDTH}x{ATLAS_TILE})."
        )
    replaced = atlas.copy()
    replaced.paste(strip, (0, row * ATLAS_TILE))
    return replaced


def save_atlas_atomic(
    atlas: "Image.Image", target: Path | str, make_backup: bool = True
) -> None:
    """Grava o atlas em PNG com escrita atômica e backup ``.bak``."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = target.stat().st_mode & 0o777 if target.exists() else 0o644
    if make_backup and target.exists():
        shutil.copy2(target, core.backup_path(target))
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".png.tmp", dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        atlas.save(temporary, format="PNG")
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def override_row_with_cube(
    atlas_path: Path | str,
    row: int,
    cube_path: Path | str,
    make_backup: bool = True,
) -> dict:
    """Substitui a linha do atlas pela LUT do .cube (com backup e verificação)."""
    row = validate_row(row)
    cube = parse_cube_file(cube_path)
    atlas = load_atlas_image(atlas_path)
    strip = strip_image_from_cube(cube)
    replaced = atlas_with_replaced_row(atlas, row, strip)
    save_atlas_atomic(replaced, atlas_path, make_backup=make_backup)
    valid, message = core.validate_texture(atlas_path)
    if not valid:
        raise AtlasError(f"Atlas gravado falhou na verificação: {message}")
    return {
        "row": row,
        "atlas": str(atlas_path),
        "cube": str(cube_path),
        "cube_size": cube["size"],
        "cube_title": cube["title"],
        "backup": str(core.backup_path(atlas_path))
        if make_backup and Path(atlas_path).exists()
        else None,
    }


def restore_row_from_bundle(
    atlas_path: Path | str,
    row: int,
    bundle_root: Path | str,
    make_backup: bool = True,
) -> dict:
    """Restaura UMA linha do atlas a partir do pacote interno do aplicativo."""
    row = validate_row(row)
    bundle_atlas = Path(bundle_root) / BUNDLE_TEXTURE
    source = load_atlas_image(bundle_atlas)
    target = load_atlas_image(atlas_path)
    strip = source.crop((0, row * ATLAS_TILE, STRIP_WIDTH, (row + 1) * ATLAS_TILE))
    replaced = atlas_with_replaced_row(target, row, strip)
    save_atlas_atomic(replaced, atlas_path, make_backup=make_backup)
    return {"row": row, "atlas": str(atlas_path), "source": str(bundle_atlas)}


def restore_atlas_backup(atlas_path: Path | str) -> Path:
    """Copia o backup ``.bak`` de volta para o atlas instalado."""
    target = Path(atlas_path)
    backup = core.backup_path(target)
    if not backup.is_file():
        raise AtlasError(f"Nenhum backup do atlas disponível: {backup}")
    valid, message = core.validate_texture(backup)
    if not valid:
        raise AtlasError(f"O backup do atlas não é válido: {message}")
    mode = backup.stat().st_mode & 0o777
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".png.tmp", dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(backup, temporary)
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return backup


# --------------------------------------------------------------------------
# Reindexação: mapeamento perfil -> linha (P_LUT_ROW) no shader
# --------------------------------------------------------------------------
_ROW_BRANCH_RE = re.compile(r"#(?:if|elif)\s+ACTIVE_LUT_PROFILE\s*==\s*(\d+)\b")
_ROW_DEFINE_RE = re.compile(
    r"^(\s*)#define\s+P_LUT_ROW\s+(ACTIVE_LUT_PROFILE|\d+)\s*(?://.*)?$"
)


def parse_lut_row_map(shader_text: str) -> dict[int, int]:
    """Extrai o mapeamento perfil -> linha do bloco P_LUT_ROW do shader.

    Perfis sem ramo próprio herdam o ``#else`` (``P_LUT_ROW ACTIVE_LUT_PROFILE``
    significa identidade). Linhas fora do atlas 0..16 levantam erro.
    """
    active: int | None = None
    else_value: int | None = None  # None = sem else; -1 = identidade
    explicit: dict[int, int] = {}
    in_lut_block = False
    for raw_line in shader_text.splitlines():
        line = raw_line.split("//", 1)[0].rstrip()
        stripped = line.strip()
        define = _ROW_DEFINE_RE.match(line)
        if define:
            in_lut_block = True
            value = define.group(2)
            if active is None:
                raise AtlasError("P_LUT_ROW definido fora de um ramo do perfil.")
            if value == "ACTIVE_LUT_PROFILE":
                if active == -1:
                    else_value = -1
                else:
                    explicit[active] = active
            else:
                if active == -1:
                    else_value = int(value)
                else:
                    explicit[active] = int(value)
            continue
        branch = _ROW_BRANCH_RE.search(stripped)
        if branch and stripped.startswith("#"):
            active = int(branch.group(1))
            continue
        if stripped.startswith("#else") and in_lut_block:
            active = -1
            continue
        if stripped.startswith("#endif") and in_lut_block:
            break
    mapping: dict[int, int] = dict(explicit)
    if else_value is not None:
        for profile_id in range(len(core.PROFILES)):
            mapping.setdefault(
                profile_id, profile_id if else_value == -1 else else_value
            )
    for profile_id, row in mapping.items():
        if not 0 <= row < ATLAS_ROWS:
            raise AtlasError(
                f"O perfil {profile_id} aponta para a linha {row}, "
                f"fora do atlas v1.8 (0 a {ATLAS_ROWS - 1})."
            )
    return mapping


def _lut_row_block_text(mapping: dict[int, int]) -> str:
    """Gera o bloco #if/#elif completo com P_LUT_ROW explícito por perfil."""
    lines = ["// Mapeamento perfil -> linha do atlas gerado pelo MultiLUT Controller."]
    for index in range(len(core.PROFILES)):
        row = mapping.get(index, index)
        keyword = "#if" if index == 0 else "#elif"
        lines.append(f"{keyword} ACTIVE_LUT_PROFILE == {index}")
        lines.append(f"    #define P_LUT_ROW {validate_row(row)}")
    lines.append("#else")
    lines.append("    #define P_LUT_ROW ACTIVE_LUT_PROFILE")
    lines.append("#endif")
    return "\n".join(lines)


def write_lut_row_map(shader_text: str, mapping: dict[int, int]) -> str:
    """Substitui o bloco P_LUT_ROW existente pelo mapeamento informado."""
    lines = shader_text.splitlines()
    define_index = next(
        (i for i, line in enumerate(lines) if _ROW_DEFINE_RE.match(line)),
        None,
    )
    if define_index is None:
        raise AtlasError(
            "Bloco P_LUT_ROW não encontrado no shader; instale o pacote v1.8."
        )
    start = next(
        (
            i
            for i in range(define_index, -1, -1)
            if lines[i].strip().startswith("#if ACTIVE_LUT_PROFILE")
        ),
        None,
    )
    if start is None:
        raise AtlasError("Não foi possível localizar o início do bloco P_LUT_ROW.")
    depth = 0
    end = None
    for index in range(start, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("#if"):
            depth += 1
        elif stripped.startswith("#endif"):
            depth -= 1
            if depth == 0:
                end = index
                break
    if end is None:
        raise AtlasError("Bloco P_LUT_ROW sem #endif correspondente.")
    replacement = _lut_row_block_text(mapping).splitlines()
    updated = lines[:start] + replacement + lines[end + 1 :]
    return "\n".join(updated) + ("\n" if shader_text.endswith("\n") else "")


def reindex_profile(
    shader_path: Path | str, profile_id: int, row: int, make_backup: bool = True
) -> dict:
    """Aponta o perfil para a linha do atlas (reescreve o bloco P_LUT_ROW)."""
    if profile_id not in core.PROFILE_BY_ID:
        raise core.MultiLUTError(f"Perfil fora do intervalo permitido: {profile_id}")
    row = validate_row(row)
    target = Path(shader_path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise AtlasError(f"Não foi possível ler o shader: {target}") from exc
    mapping = parse_lut_row_map(text)
    previous = mapping.get(profile_id, profile_id)
    if previous == row:
        return {
            "profile": profile_id,
            "row": row,
            "previous_row": previous,
            "changed": False,
            "shader": str(target),
        }
    mapping[profile_id] = row
    updated = write_lut_row_map(text, mapping)
    mode = target.stat().st_mode & 0o777
    if make_backup:
        shutil.copy2(target, core.backup_path(target))
    core._atomic_write(target, updated, mode)
    confirmed = parse_lut_row_map(target.read_text(encoding="utf-8"))
    if confirmed.get(profile_id) != row:
        raise AtlasError("A verificação após a gravação não confirmou a reindexação.")
    return {
        "profile": profile_id,
        "row": row,
        "previous_row": previous,
        "changed": True,
        "backup": str(core.backup_path(target)) if make_backup else None,
        "shader": str(target),
    }


def reset_lut_row_map(shader_path: Path | str, make_backup: bool = True) -> dict:
    """Restaura o mapeamento padrão do shader v1.8 (identidade + overrides)."""
    target = Path(shader_path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise AtlasError(f"Não foi possível ler o shader: {target}") from exc
    mapping = {profile_id: profile_id for profile_id in range(len(core.PROFILES))}
    mapping.update(core.LUT_ROW_BY_PROFILE)
    current = parse_lut_row_map(text)
    if current == mapping:
        return {"shader": str(target), "changed": False}
    updated = write_lut_row_map(text, mapping)
    mode = target.stat().st_mode & 0o777
    if make_backup:
        shutil.copy2(target, core.backup_path(target))
    core._atomic_write(target, updated, mode)
    confirmed = parse_lut_row_map(target.read_text(encoding="utf-8"))
    if confirmed != mapping:
        raise AtlasError("A verificação após a gravação não confirmou o padrão.")
    return {"shader": str(target), "changed": True}


def row_owner_profiles(mapping: dict[int, int]) -> dict[int, list[int]]:
    """Inverte o mapeamento: linha -> perfis que a utilizam."""
    owners: dict[int, list[int]] = {row: [] for row in range(ATLAS_ROWS)}
    for profile_id, row in sorted(mapping.items()):
        if 0 <= row < ATLAS_ROWS:
            owners[row].append(profile_id)
    return owners
