"""Publicação do site no GitHub Pages (SPEC V3 12.6): `site/` → branch `gh-pages`.

O build acontece ao lado do banco (VPS ou máquina do autor com o túnel); o GitHub recebe só o
resultado estático. Nenhuma credencial de banco vai para o GitHub.

- Clona o repositório uma vez em `data/gh-pages-worktree/` (fora do Git do projeto).
- Com `deploy_key` (VPS, M6) usa `GIT_SSH_COMMAND`; sem ela usa as credenciais Git da máquina.
- Substitui o conteúdo pelo de `out_dir`, cria `.nojekyll`, faz commit e push só se algo mudou.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from radar.config import RAIZ_PROJETO, get_settings
from radar.dashboard.build import carregar_config

log = logging.getLogger("radar.dashboard.publish")
WORKTREE = RAIZ_PROJETO / "data" / "gh-pages-worktree"


def _git(*args: str, cwd: Path, env: dict | None = None, check: bool = True) -> str:
    r = subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=False
    )
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:500]}")
    return r.stdout.strip()


def validar_site(out_dir: Path) -> None:
    """Recusa publicar um build incompleto (SPEC 12.6, passo 1)."""
    paginas = [p["slug"] for p in carregar_config()["paginas"]]
    faltando = [p for p in paginas if not (out_dir / f"{p}.html").exists()]
    if faltando or not (out_dir / "data" / "meta.json").exists():
        raise RuntimeError(f"site incompleto em {out_dir}: faltam {faltando or ['data/meta.json']}")


def _remote_padrao() -> str:
    """GH_PAGES_REMOTE (VPS, com deploy key) ou, se vazio/placeholder, o `origin` do repositório."""
    configurado = get_settings().gh_pages_remote
    if configurado and "<" not in configurado:
        return configurado
    return _git("remote", "get-url", "origin", cwd=RAIZ_PROJETO)


def _preparar_worktree(remote: str, branch: str, env: dict) -> None:
    if (WORKTREE / ".git").exists():
        _git("fetch", "--quiet", "origin", cwd=WORKTREE, env=env, check=False)
        if _git("ls-remote", "--heads", "origin", branch, cwd=WORKTREE, env=env):
            _git("checkout", "--quiet", "-B", branch, f"origin/{branch}", cwd=WORKTREE, env=env)
        return
    WORKTREE.parent.mkdir(parents=True, exist_ok=True)
    existe = bool(_git("ls-remote", "--heads", remote, branch, cwd=RAIZ_PROJETO, env=env))
    if existe:
        _git(
            "clone",
            "--quiet",
            "--branch",
            branch,
            "--single-branch",
            "--depth",
            "1",
            remote,
            str(WORKTREE),
            cwd=RAIZ_PROJETO,
            env=env,
        )
    else:  # primeira publicação: branch órfã, sem o histórico do main
        WORKTREE.mkdir(parents=True, exist_ok=True)
        _git("init", "--quiet", cwd=WORKTREE)
        _git("checkout", "--quiet", "--orphan", branch, cwd=WORKTREE)
        _git("remote", "add", "origin", remote, cwd=WORKTREE)
    for chave in (
        "user.name",
        "user.email",
    ):  # mesmo autor (e-mail noreply) do repositório principal
        valor = _git("config", chave, cwd=RAIZ_PROJETO, check=False)
        if valor:
            _git("config", chave, valor, cwd=WORKTREE)


def _copiar(out_dir: Path) -> None:
    for item in WORKTREE.iterdir():
        if item.name == ".git":
            continue
        shutil.rmtree(item) if item.is_dir() else item.unlink()
    shutil.copytree(out_dir, WORKTREE, dirs_exist_ok=True)
    (WORKTREE / ".nojekyll").write_text("", encoding="utf-8")


def publish(out_dir: Path, *, remote: str | None = None, branch: str | None = None,
            deploy_key: Path | None = None, dry_run: bool = False) -> dict:  # fmt: skip
    """Publica `out_dir` no branch do Pages. Devolve {commit, arquivos, bytes, duracao_s, mudancas}."""
    t0 = time.monotonic()
    s = get_settings()
    branch = branch or s.gh_pages_branch
    remote = remote or _remote_padrao()
    validar_site(out_dir)
    env = dict(os.environ)
    chave = deploy_key or (s.gh_deploy_key_path if s.gh_deploy_key_path.exists() else None)
    if chave:
        env["GIT_SSH_COMMAND"] = f"ssh -i {chave} -o IdentitiesOnly=yes"
    _preparar_worktree(remote, branch, env)
    _copiar(out_dir)
    _git("add", "-A", cwd=WORKTREE)
    mudancas = [
        linha for linha in _git("status", "--porcelain", cwd=WORKTREE).splitlines() if linha
    ]
    arquivos = [p for p in WORKTREE.rglob("*") if p.is_file() and ".git" not in p.parts]
    r = {"commit": None, "arquivos": len(arquivos), "bytes": sum(p.stat().st_size for p in arquivos),
         "mudancas": len(mudancas), "branch": branch, "dry_run": dry_run}  # fmt: skip
    if dry_run or not mudancas:
        if dry_run:
            _git("reset", "--quiet", cwd=WORKTREE, check=False)
        log.info(
            "publish %s: %d arquivo(s) mudariam",
            "simulado" if dry_run else "sem mudanças",
            len(mudancas),
        )
        r["duracao_s"] = round(time.monotonic() - t0, 1)
        return r
    meta = json.loads((out_dir / "data" / "meta.json").read_text(encoding="utf-8"))["dados"]
    execucao = (meta.get("execucao") or {}).get("id", "?")
    _git("commit", "--quiet", "-m", f"chore(pages): dashboards de {datetime.now():%d/%m/%Y %H:%M} (execução {execucao})",
         cwd=WORKTREE)  # fmt: skip
    tem_remoto = bool(_git("ls-remote", "--heads", "origin", branch, cwd=WORKTREE, env=env))
    if tem_remoto:
        _git(
            "push",
            "--quiet",
            "--force-with-lease",
            "origin",
            f"HEAD:{branch}",
            cwd=WORKTREE,
            env=env,
        )
    else:
        _git("push", "--quiet", "-u", "origin", f"HEAD:{branch}", cwd=WORKTREE, env=env)
    r["commit"] = _git("rev-parse", "--short", "HEAD", cwd=WORKTREE)
    r["duracao_s"] = round(time.monotonic() - t0, 1)
    log.info(
        "publicado no %s: commit %s, %d arquivos, %.1f MB",
        branch,
        r["commit"],
        r["arquivos"],
        r["bytes"] / 1e6,
    )
    return r
