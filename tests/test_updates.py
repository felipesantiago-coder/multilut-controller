#!/usr/bin/env python3
"""Verificação e aplicação de atualizações direto do repositório (sem release)."""

import io
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import multilut_core as core


class FetchTests(unittest.TestCase):
    """Parsing das respostas do GitHub (todas via _http_get simulado)."""

    def test_fetch_latest_commit_parseia_json(self):
        payload = (
            b'{"sha": "abc1234def5678", "commit": {"message": "feat: algo\\n'
            b'corpo", "committer": {"date": "2026-10-30T12:00:00Z"}}}'
        )
        with mock.patch.object(core, "_http_get", return_value=payload):
            commit = core.fetch_latest_commit()
        self.assertEqual(commit["sha"], "abc1234def5678")
        self.assertEqual(commit["message"], "feat: algo")
        self.assertEqual(commit["date"], "2026-10-30T12:00:00Z")

    def test_fetch_latest_commit_sem_rede_retorna_none(self):
        with mock.patch.object(core, "_http_get", return_value=None):
            self.assertIsNone(core.fetch_latest_commit())

    def test_fetch_latest_commit_json_invalido_retorna_none(self):
        with mock.patch.object(core, "_http_get", return_value=b"nao-json"):
            self.assertIsNone(core.fetch_latest_commit())

    def test_fetch_remote_app_version_le_constante(self):
        source = b'import re\nAPP_VERSION = "9.9.9"\nRESTO = 1\n'
        with mock.patch.object(core, "_http_get", return_value=source):
            self.assertEqual(core.fetch_remote_app_version(), "9.9.9")

    def test_fetch_remote_app_version_sem_arquivo_retorna_none(self):
        with mock.patch.object(core, "_http_get", return_value=None):
            self.assertIsNone(core.fetch_remote_app_version())

    def test_fetch_latest_release_via_http_get(self):
        payload = b'{"tag_name": "v2.0.0", "name": "Nova", "html_url": "u"}'
        with mock.patch.object(core, "_http_get", return_value=payload):
            release = core.fetch_latest_release()
        self.assertEqual(release["tag"], "v2.0.0")


class InstalledCommitTests(unittest.TestCase):
    def test_source_commit_marker_e_lido(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "source_commit").write_text("abc1234def5678\n", encoding="utf-8")
            self.assertEqual(core.installed_commit(repo), "abc1234def5678")

    def test_sem_git_e_sem_marker_retorna_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(core.installed_commit(Path(tmp)))

    def test_git_head_tem_prioridade_sobre_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "source_commit").write_text("abc1234def5678\n", encoding="utf-8")
            with mock.patch.object(core, "local_git_head", return_value="fffe"):
                self.assertEqual(core.installed_commit(repo), "fffe")


class CheckForUpdatesTests(unittest.TestCase):
    """A decisão central, com o GitHub todo simulado."""

    def setUp(self):
        patchers = [
            mock.patch.object(core, "fetch_latest_release", return_value=None),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_clone_atualizado(self):
        with mock.patch.object(core, "installed_commit", return_value="abc1234"), \
             mock.patch.object(core, "local_git_head", return_value="abc1234"), \
             mock.patch.object(
                 core, "git_remote_head", return_value="abc1234abcdef5678"
             ):
            result = core.check_for_updates()
        self.assertEqual(result["status"], "current")

    def test_clone_atrasado_detecta_commits_novos(self):
        with mock.patch.object(core, "installed_commit", return_value="abc1234"), \
             mock.patch.object(core, "local_git_head", return_value="abc1234"), \
             mock.patch.object(
                 core, "git_remote_head", return_value="def5678abcdef123"
             ):
            result = core.check_for_updates()
        self.assertEqual(result["status"], "available")
        self.assertIn("def5678", result["message"])

    def test_release_nova_vence(self):
        release = {"tag": "v9.0.0", "name": "Grande", "url": "u"}
        with mock.patch.object(core, "installed_commit", return_value="abc1234"), \
             mock.patch.object(core, "local_git_head", return_value="abc1234"), \
             mock.patch.object(
                 core, "git_remote_head", return_value="abc1234abcdef5678"
             ), \
             mock.patch.object(core, "fetch_latest_release", return_value=release):
            result = core.check_for_updates()
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["release"]["tag"], "v9.0.0")

    def test_instalacao_com_marker_e_commit_remoto_diferente(self):
        commit = {"sha": "def5678abcdef1", "date": "d", "message": "feat: x"}
        with mock.patch.object(core, "installed_commit", return_value="abc1234"), \
             mock.patch.object(core, "local_git_head", return_value=None), \
             mock.patch.object(core, "fetch_latest_commit", return_value=commit):
            result = core.check_for_updates()
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["commit_message"], "feat: x")

    def test_instalacao_sem_commit_compara_versao_remota_maior(self):
        with mock.patch.object(core, "installed_commit", return_value=None), \
             mock.patch.object(core, "local_git_head", return_value=None), \
             mock.patch.object(
                 core, "fetch_latest_commit", return_value={"sha": "a" * 40}
             ), \
             mock.patch.object(
                 core, "fetch_remote_app_version", return_value="99.0.0"
             ):
            result = core.check_for_updates()
        self.assertEqual(result["status"], "available")
        self.assertIn("99.0.0", result["message"])

    def test_instalacao_sem_commit_versao_remota_igual(self):
        with mock.patch.object(core, "installed_commit", return_value=None), \
             mock.patch.object(core, "local_git_head", return_value=None), \
             mock.patch.object(
                 core, "fetch_latest_commit", return_value={"sha": "a" * 40}
             ), \
             mock.patch.object(
                 core, "fetch_remote_app_version", return_value=core.APP_VERSION
             ):
            result = core.check_for_updates()
        self.assertEqual(result["status"], "current")

    def test_rede_indisponivel_retorna_unknown(self):
        with mock.patch.object(core, "installed_commit", return_value=None), \
             mock.patch.object(core, "local_git_head", return_value=None), \
             mock.patch.object(core, "fetch_latest_commit", return_value=None), \
             mock.patch.object(core, "fetch_remote_app_version", return_value=None):
            result = core.check_for_updates()
        self.assertEqual(result["status"], "unknown")
        self.assertTrue(result["message"])

    def test_api_de_commits_fora_versao_remota_maior_detecta(self):
        commit = {"sha": "a" * 40, "date": "d", "message": "m"}
        with mock.patch.object(core, "installed_commit", return_value="abc1234"), \
             mock.patch.object(core, "local_git_head", return_value=None), \
             mock.patch.object(core, "fetch_latest_commit", return_value=commit), \
             mock.patch.object(
                 core, "fetch_remote_app_version", return_value="99.0.0"
             ), \
             mock.patch.object(core, "_http_get", return_value=None), \
             mock.patch.object(core, "git_remote_head", return_value=None):
            result = core.check_for_updates()
        self.assertEqual(result["status"], "available")

    def test_api_fora_versao_igual_sem_marker_considera_em_dia(self):
        with mock.patch.object(core, "installed_commit", return_value=None), \
             mock.patch.object(core, "local_git_head", return_value=None), \
             mock.patch.object(core, "fetch_latest_commit", return_value=None), \
             mock.patch.object(
                 core, "fetch_remote_app_version", return_value=core.APP_VERSION
             ):
            result = core.check_for_updates()
        self.assertEqual(result["status"], "current")

    def test_api_fora_versao_igual_com_marker_fica_unknown(self):
        with mock.patch.object(core, "installed_commit", return_value="abc1234"), \
             mock.patch.object(core, "local_git_head", return_value=None), \
             mock.patch.object(core, "fetch_latest_commit", return_value=None), \
             mock.patch.object(
                 core, "fetch_remote_app_version", return_value=core.APP_VERSION
             ):
            result = core.check_for_updates()
        self.assertEqual(result["status"], "unknown")


class ApplyUpdateTarballTests(unittest.TestCase):
    """O caminho de instalações sem git, com tarball fabricado em disco."""

    FAKE_INSTALL_SH = """#!/usr/bin/env bash
set -eu
SOURCE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
mkdir -p "$MULTILUT_TEST_APP_DIR"
cp -a "$SOURCE_DIR/." "$MULTILUT_TEST_APP_DIR/"
date -u +%s > "$MULTILUT_TEST_APP_DIR/install_stamp"
"""

    def make_tarball(self, root: Path) -> bytes:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            for path in sorted(root.rglob("*")):
                arcname = "multilut-controller-main/" + path.relative_to(root).as_posix()
                tar.add(path, arcname=arcname)
        return buffer.getvalue()

    def build_fake_repo(self, base: Path) -> Path:
        root = base / "repo"
        root.mkdir()
        (root / "multilut_core.py").write_text("APP_VERSION = '9.9.9'\n", encoding="utf-8")
        (root / "run.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        (root / "install.sh").write_text(self.FAKE_INSTALL_SH, encoding="utf-8")
        return root

    def test_tarball_baixado_instalado_e_marcado(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            app_dir = base / "app"
            repo = self.build_fake_repo(base)
            tar_bytes = self.make_tarball(repo)
            sha = "deadbeef" + "0123456789abcdef" * 2  # 40 hex
            with mock.patch.object(core, "installed_commit", return_value=None), \
                 mock.patch.object(
                     core, "fetch_latest_commit",
                     return_value={"sha": sha, "date": "d", "message": "m"},
                 ), \
                 mock.patch.object(core, "_http_get", return_value=tar_bytes), \
                 mock.patch.dict(
                     os.environ,
                     {
                         "MULTILUT_TEST_APP_DIR": str(app_dir),
                         "SOURCE_DIR": str(repo),
                     },
                 ):
                result = core.apply_update_tarball(timeout=30.0)
            self.assertTrue(result["ok"], result["message"])
            self.assertEqual(result["new_head"], "deadbee")
            self.assertTrue((app_dir / "multilut_core.py").is_file())
            self.assertTrue((app_dir / "install_stamp").is_file())
            self.assertEqual(
                (app_dir / "source_commit").read_text(encoding="utf-8").strip(), sha
            )

    def test_download_falho_reporta_erro(self):
        with mock.patch.object(core, "installed_commit", return_value="abc"), \
             mock.patch.object(
                 core, "fetch_latest_commit",
                 return_value={"sha": "a" * 40, "date": "d", "message": "m"},
             ), \
             mock.patch.object(core, "_http_get", return_value=None):
            result = core.apply_update_tarball(timeout=5.0)
        self.assertFalse(result["ok"])
        self.assertIn("baixar", result["message"])

    def test_extracao_rejeita_caminho_suspeito(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            archive = base / "mau.tar.gz"
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
                info = tarfile.TarInfo("../fora.txt")
                payload = b"conteudo"
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
            archive.write_bytes(buffer.getvalue())
            destination = base / "dest"
            destination.mkdir()
            with self.assertRaises(ValueError):
                core._extract_tarball_safe(archive, destination)
            self.assertFalse((base / "fora.txt").exists())


class InstallShMarkerTests(unittest.TestCase):
    """install.sh grava source_commit e install_stamp na instalação."""

    def test_install_grava_marcacoes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            data_root = base / "data"
            env = dict(os.environ)
            env.update(
                {
                    "HOME": str(base),
                    "XDG_DATA_HOME": str(data_root),
                }
            )
            repo = Path(__file__).resolve().parent.parent
            head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            out = subprocess.run(
                ["bash", "install.sh"],
                cwd=repo,
                capture_output=True,
                text=True,
                env=env,
                timeout=120,
            )
            self.assertEqual(out.returncode, 0, out.stderr or out.stdout)
            app_dir = data_root / "multilut-controller"
            self.assertTrue((app_dir / "multilut_core.py").is_file())
            self.assertTrue((app_dir / "install_stamp").is_file())
            self.assertEqual(
                (app_dir / "source_commit").read_text(encoding="utf-8").strip(), head
            )


if __name__ == "__main__":
    unittest.main()
