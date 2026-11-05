"""Delega uma tarefa de código ao modelo local (OpenCode + llama-server) e devolve um relatório curto.

Núcleo usado por dois clientes:
  - a skill /delegar do Claude Code, pela linha de comando (main);
  - o servidor MCP tools/delegar_mcp.py (Claude Code, Antigravity, qualquer cliente MCP), por delegate().

Fluxo: o arquiteto escreve a especificação; delegate() a entrega ao agente `delegado` do OpenCode
(~/.config/opencode/agents/delegado.md, com a cerca de permissões), espera, roda a verificação por
conta própria (não confia no relatório do modelo) e devolve o necessário para a revisão: arquivos
mexidos, diff --stat, resultado do teste e o relatório final do executor.

Uso (da raiz do projeto):
    .venv/Scripts/python tools/delegar.py SPEC.md --verify ".venv/Scripts/python -m unittest ..."
    .venv/Scripts/python tools/delegar.py SPEC.md --session ses_xxx      # volta de correção
    .venv/Scripts/python tools/delegar.py SPEC.md --workdir C:/outro/repo

Cada execução grava o fluxo bruto em logs/delegar/<carimbo>.jsonl e uma linha de métrica em
logs/delegar.jsonl (deste repositório, qualquer que seja a pasta de trabalho).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import msvcrt
import os
import shlex
import subprocess
import sys
import threading
import time
import urllib.request
from collections import Counter
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path

HOME_REPO = Path(__file__).resolve().parent.parent
LOG_DIR = HOME_REPO / "logs"
DEFAULT_CLI = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/ai.opencode.desktop/resources/opencode-cli.exe"
OPENCODE_CLI = Path(os.environ.get("OPENCODE_CLI", DEFAULT_CLI))
ROUTER_URL = os.environ.get("DELEGAR_ROUTER_URL", "http://127.0.0.1:8080")
DEFAULT_MODEL = "llama-local/qwen3.8-27b-normal"
ARGV_LIMIT = 20_000  # acima disso a especificação vai como anexo (--file), longe do limite de 32k do Windows
# Raízes onde a delegação pode escrever (separadas por ;). Padrão: a pasta do usuário.
ALLOWED_ROOTS = [Path(p).resolve() for p in
                 os.environ.get("DELEGAR_ROOTS", os.environ.get("USERPROFILE", str(Path.home()))).split(";") if p]


class DelegarError(Exception):
    """Pré-condição não atendida (pasta, roteador, CLI). A mensagem vai direto ao arquiteto."""


# ---------------------------------------------------------------- pré-condições

def router_ok() -> bool:
    try:
        with urllib.request.urlopen(f"{ROUTER_URL}/health", timeout=5) as r:
            return r.status == 200
    except OSError:
        return False


def git(workdir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=workdir, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)


def check_workdir(path: str | Path) -> Path:
    """A pasta precisa estar dentro de uma raiz permitida e ser um repositório git:
    o git é a rede de segurança (tudo o que o executor fizer é revisável e reversível)."""
    p = Path(path).resolve()
    if not p.is_dir():
        raise DelegarError(f"pasta não existe: {p}")
    if not any(p == r or r in p.parents for r in ALLOWED_ROOTS):
        raise DelegarError(f"pasta fora das raízes permitidas ({'; '.join(map(str, ALLOWED_ROOTS))}): {p}")
    if p in ALLOWED_ROOTS:
        raise DelegarError(f"a raiz inteira não pode ser pasta de trabalho, aponte para o repositório: {p}")
    r = git(p, "rev-parse", "--show-toplevel")
    if r.returncode != 0:
        raise DelegarError(f"não é um repositório git (sem git não há como revisar nem reverter): {p}")
    return Path(r.stdout.strip()).resolve()


def preflight(workdir: str | Path) -> Path:
    if not OPENCODE_CLI.exists():
        raise DelegarError(f"opencode-cli não encontrado em {OPENCODE_CLI} (defina OPENCODE_CLI).")
    root = check_workdir(workdir)
    if not router_ok():
        raise DelegarError(f"llama-server não responde em {ROUTER_URL}/health. Suba o roteador: "
                           r"C:\Users\plepl\llm\start-opencode-router.cmd (e feche o agent/main.py, "
                           "que usa a mesma porta).")
    return root


# ---------------------------------------------------------------- trava da GPU

@contextlib.contextmanager
def gpu_lock(on_wait: Callable[[], None] | None = None) -> Iterator[None]:
    """Uma delegação por vez na máquina inteira, mesmo entre processos (cada cliente MCP sobe o
    seu servidor). Trava de arquivo do Windows (msvcrt): o SO solta sozinha se o processo morrer."""
    (LOG_DIR / "delegar").mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / "delegar" / "gpu.lock", "a+b") as fh:
        warned = False
        while True:
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if on_wait and not warned:
                    on_wait()
                    warned = True
                time.sleep(2)
        try:
            yield
        finally:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)


# ---------------------------------------------------------------- git: o que o executor mexeu

def snapshot(workdir: Path) -> dict[str, str]:
    """Arquivo sujo -> hash do conteúdo. Separa o que o executor mexeu do que já estava sujo."""
    snap = {}
    for line in git(workdir, "status", "--porcelain", "--untracked-files=all").stdout.splitlines():
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        p = workdir / path
        snap[path] = hashlib.sha1(p.read_bytes()).hexdigest() if p.is_file() else "<ausente>"
    return snap


def changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(p for p, h in after.items() if before.get(p) != h) + \
        sorted(p for p in before if p not in after)  # sujo antes e limpo depois = executor reverteu


# ---------------------------------------------------------------- execução

def run_executor(message: str, workdir: Path, model: str, title: str, session: str | None,
                 timeout: int, raw_log: Path, on_start: Callable[[int], None] | None = None) -> dict:
    cmd = [str(OPENCODE_CLI), "run", "--agent", "delegado", "-m", model,
           "--format", "json", "--auto", "--title", title]
    if session:
        cmd += ["--session", session]
    if len(message) > ARGV_LIMIT:
        spec_file = raw_log.with_suffix(".spec.md")
        spec_file.write_text(message, encoding="utf-8")
        cmd += ["--file", str(spec_file), "Execute a especificação do arquivo anexo."]
    else:
        cmd.append(message)

    info = {"session": session, "texts": [], "events": Counter(), "tools": Counter(),
            "tokens": Counter(), "steps": 0, "timeout": False, "exit": None}
    t0 = time.monotonic()
    with raw_log.open("w", encoding="utf-8") as raw:
        # stdin fechado: com stdin que não é TTY, o `opencode run` lê dele e espera EOF (travou assim).
        proc = subprocess.Popen(cmd, cwd=workdir, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        if on_start:
            on_start(proc.pid)

        def _kill() -> None:  # cão de guarda: mata mesmo se o executor travar sem emitir nada
            info["timeout"] = True
            proc.kill()

        watchdog = threading.Timer(timeout, _kill)
        watchdog.start()
        try:
            for line in proc.stdout:
                raw.write(line)
                raw.flush()
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = ev.get("type", "?")
                info["events"][kind] += 1
                info["session"] = ev.get("sessionID", info["session"])
                part = ev.get("part") or {}
                if kind == "text" and part.get("text"):
                    info["texts"].append(part["text"])
                if part.get("tool"):
                    info["tools"][part["tool"]] += 1
                if kind == "step_finish":
                    info["steps"] += 1
                    tok = part.get("tokens") or {}
                    for k in ("input", "output", "reasoning"):
                        info["tokens"][k] += tok.get(k, 0)
            proc.wait(timeout=30)
        finally:
            watchdog.cancel()
            if proc.poll() is None:
                proc.kill()
    info["exit"] = proc.returncode
    info["seconds"] = round(time.monotonic() - t0, 1)
    return info


def run_verify(cmd: str, workdir: Path) -> dict:
    """Roda sem shell quando dá: o cmd.exe não entende `.venv/Scripts/python` (barra normal).
    Com pipe ou redirecionamento, cai no shell e o caminho precisa vir no formato do Windows."""
    t0 = time.monotonic()
    if any(c in cmd for c in "|&<>"):
        argv, shell = cmd, True
    else:
        argv, shell = shlex.split(cmd), False
        exe = workdir / argv[0]
        if exe.exists() or exe.with_suffix(".exe").exists():
            argv[0] = str(exe)
    try:
        r = subprocess.run(argv, cwd=workdir, shell=shell, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, timeout=600)
        out, code = (r.stdout + r.stderr).strip().splitlines(), r.returncode
    except (OSError, subprocess.TimeoutExpired) as e:
        out, code = [f"{type(e).__name__}: {e}"], -1
    return {"cmd": cmd, "exit": code, "tail": out[-25:], "seconds": round(time.monotonic() - t0, 1)}


def parse_status(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip().upper().startswith("STATUS:"):
            return line.split(":", 1)[1].strip()
    return "SEM RELATÓRIO"


def delegate(spec: str, workdir: str | Path = HOME_REPO, verify: str | None = None,
             session: str | None = None, model: str = DEFAULT_MODEL, title: str = "delegar",
             timeout: int = 1800, on_state: Callable[[str, dict], None] | None = None) -> dict:
    """Executa uma delegação inteira e devolve o resultado estruturado (ver format_report).
    on_state(estado, dados) é chamado em 'fila', 'executando' e 'verificando' (usado pelo MCP)."""
    root = preflight(workdir)
    message = spec.strip()
    if verify:
        message += f"\n\nComando de verificação (rode no fim): {verify}"

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (LOG_DIR / "delegar").mkdir(parents=True, exist_ok=True)
    raw_log = LOG_DIR / "delegar" / f"{stamp}-{os.getpid()}.jsonl"
    notify = on_state or (lambda *_: None)

    with gpu_lock(on_wait=lambda: notify("fila", {})):
        before = snapshot(root)
        notify("executando", {})
        info = run_executor(message, root, model, title, session, timeout, raw_log,
                            on_start=lambda pid: notify("executando", {"pid": pid}))
    after = snapshot(root)
    files = changed_files(before, after)
    notify("verificando", {})
    vres = run_verify(verify, root) if verify else None

    final = info["texts"][-1].strip() if info["texts"] else ""
    tracked = [f for f in files if git(root, "ls-files", "--", f).stdout.strip()]
    new = []
    for f in files:
        if f in tracked:
            continue
        p = root / f
        n = len(p.read_text(encoding="utf-8", errors="replace").splitlines()) if p.is_file() else 0
        new.append({"path": f, "lines": n})
    result = {
        "when": stamp, "workdir": str(root), "model": model, "retry": bool(session),
        "session": info["session"], "status": "TIMEOUT" if info["timeout"] else parse_status(final),
        "seconds": info["seconds"], "steps": info["steps"], "opencode_exit": info["exit"],
        "tokens": dict(info["tokens"]), "tools": dict(info["tools"]),
        "files": files, "new_files": new,
        "diff_stat": git(root, "diff", "--stat", "--", *tracked).stdout.strip() if tracked else "",
        "verify": vres, "verify_exit": vres["exit"] if vres else None,
        "executor_report": final, "raw_log": str(raw_log), "spec_chars": len(spec),
    }
    with (LOG_DIR / "delegar.jsonl").open("a", encoding="utf-8") as m:
        keep = ("when", "workdir", "session", "model", "retry", "status", "seconds", "steps",
                "tokens", "tools", "files", "spec_chars", "verify_exit")
        m.write(json.dumps({k: result[k] for k in keep}, ensure_ascii=False) + "\n")
    return result


def format_report(r: dict) -> str:
    tok = r["tokens"]
    lines = [
        f"== DELEGAR · status do executor: {r['status']}",
        f"pasta: {r['workdir']}",
        f"sessão: {r['session']}   tempo: {r['seconds']} s   passos: {r['steps']}   "
        f"saída do opencode: {r['opencode_exit']}",
        f"tokens do executor: entrada {tok.get('input', 0)}, saída {tok.get('output', 0)}, "
        f"raciocínio {tok.get('reasoning', 0)}",
        "ferramentas: " + (", ".join(f"{k}×{v}" for k, v in
                                     sorted(r["tools"].items(), key=lambda kv: -kv[1])) or "nenhuma"),
        "",
        "-- arquivos mexidos" + ("" if r["files"] else ": nenhum"),
    ]
    if r["diff_stat"]:
        lines.append(r["diff_stat"])
    lines += [f" {n['path']} (novo, {n['lines']} linhas)" for n in r["new_files"]]
    if r["verify"]:
        v = r["verify"]
        lines += ["", f"-- verificação (rodada pelo delegar, não pelo executor): exit {v['exit']} em {v['seconds']} s"]
        lines += ["   " + x for x in v["tail"]]
    lines += ["", "-- relatório do executor", r["executor_report"] or "(o executor não devolveu texto)",
              "", f"log bruto: {r['raw_log']}"]
    return "\n".join(lines)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", help="arquivo com a especificação, ou - para ler do stdin")
    ap.add_argument("--verify", help="comando que prova que está pronto (rodado depois do executor)")
    ap.add_argument("--session", help="ID de sessão do OpenCode para uma volta de correção")
    ap.add_argument("--workdir", default=str(HOME_REPO), help="repositório onde o executor trabalha")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--title", default="delegar")
    ap.add_argument("--timeout", type=int, default=1800, help="segundos (padrão 1800)")
    args = ap.parse_args()

    spec = sys.stdin.read() if args.spec == "-" else Path(args.spec).read_text(encoding="utf-8")
    try:
        r = delegate(spec, args.workdir, args.verify, args.session, args.model, args.title, args.timeout,
                     on_state=lambda s, _: s == "fila" and print("outra delegação está usando a GPU; na fila..."))
    except DelegarError as e:
        print(f"ERRO: {e}")
        return 2
    print(format_report(r))
    if r["status"] == "TIMEOUT" or r["opencode_exit"] not in (0, None):
        return 3
    return 1 if r["verify_exit"] not in (None, 0) else 0


if __name__ == "__main__":
    sys.exit(main())
