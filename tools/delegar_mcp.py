"""Servidor MCP de delegação: qualquer cliente MCP (Claude Code, Antigravity, ...) manda uma tarefa
de código para o modelo local (OpenCode + llama-server) sem gastar os próprios tokens de saída.

Genérico de propósito: o servidor não sabe nada do projeto. O cliente manda uma especificação, uma
pasta (repositório git) e um comando de verificação; recebe de volta o relatório para revisar.

Ferramentas
  delegar(...)          dispara a tarefa e devolve um job_id na hora (a execução leva minutos)
  status(job_id, ...)   estado do job; quando termina, o relatório (pode esperar até 4 min por chamada)
  cancelar(job_id)      mata o executor
  modelos()             modelos do roteador local e qual está carregado na VRAM
  antigravity(...)      manda um prompt a um agente do Antigravity (Gemini) — o caminho cruzado
  antigravity_conversa  metadados de uma conversa do Antigravity

Os jobs ficam em logs/delegar/jobs/<id>.json, então qualquer cópia do servidor enxerga os jobs das
outras (cada cliente MCP sobe a sua). A GPU é protegida por uma trava de arquivo entre processos.

Variáveis de ambiente
  DELEGAR_SEM_ANTIGRAVITY=1   esconde as ferramentas do Antigravity (use no registro DENTRO do
                              Antigravity, para ele não chamar a si mesmo em laço)
  DELEGAR_ROOTS               raízes permitidas como pasta de trabalho (padrão: a pasta do usuário)
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Annotated

from pydantic import Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
import delegar as core  # noqa: E402

from mcp.server.mcpserver import MCPServer  # noqa: E402

JOBS = core.LOG_DIR / "delegar" / "jobs"
MAX_WAIT = 240  # segundos por chamada de status; fica abaixo do timeout de ferramenta dos clientes
ANTIGRAVITY = os.environ.get("DELEGAR_SEM_ANTIGRAVITY") != "1"
AG_DIR = Path.home() / ".gemini" / "antigravity"
AG_AGENTAPI = AG_DIR / "bin" / "agentapi.bat"

mcp = MCPServer("delegar", instructions=(
    "Delegação de tarefas de código a um modelo local (Qwen 3.8 27B, ~35 t/s, contexto 64k). "
    "Use para trabalho MECÂNICO e VERIFICÁVEL: o executor não vê a sua conversa, então a especificação "
    "precisa ser autossuficiente (arquivos a ler, arquivos a criar/alterar, contrato exato, critério de "
    "pronto). Sempre passe um comando de verificação. Fluxo: delegar -> status(job_id, aguardar_segundos=240) "
    "até terminar -> revise o diff com git -> aprove, ou corrija com delegar(..., sessao=<sessão do relatório>). "
    "Depois de 2 voltas de correção sem acerto, escreva você mesmo."
))


# ---------------------------------------------------------------- jobs (em disco)

def _job_path(job_id: str) -> Path:
    if not job_id.isalnum():
        raise ValueError("job_id inválido")
    return JOBS / f"{job_id}.json"


def _save(job: dict) -> None:
    JOBS.mkdir(parents=True, exist_ok=True)
    tmp = _job_path(job["id"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, _job_path(job["id"]))


def _load(job_id: str) -> dict | None:
    p = _job_path(job_id)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _run_job(job: dict) -> None:
    def on_state(state: str, data: dict) -> None:
        job.update(state=state, updated=time.time(), **data)
        _save(job)

    try:
        r = core.delegate(job["spec"], job["workdir"], job["verify"], job["session"],
                          job["model"], job["title"], job["timeout"], on_state=on_state)
        job.update(state="concluido", result=r, report=core.format_report(r))
    except core.DelegarError as e:
        job.update(state="erro", error=str(e))
    except Exception as e:  # noqa: BLE001 — o job precisa terminar com estado, nunca sumir
        job.update(state="erro", error=f"{type(e).__name__}: {e}")
    job["updated"] = time.time()
    _save(job)


def _describe(job: dict) -> str:
    el = round(time.time() - job["created"])
    head = f"job {job['id']} · estado: {job['state']} · {el} s desde a criação · pasta: {job['workdir']}"
    if job["state"] == "concluido":
        return head + "\n\n" + job["report"]
    if job["state"] == "erro":
        return head + "\nERRO: " + job["error"]
    if job["state"] == "cancelado":
        return head + "\n(cancelado)"
    tip = {"fila": "outra delegação está usando a GPU; este job espera a vez.",
           "executando": "o modelo local está trabalhando.",
           "verificando": "o executor terminou; rodando o comando de verificação."}.get(job["state"], "")
    return f"{head}\n{tip}\nChame status de novo com aguardar_segundos para esperar sem gastar turnos."


# ---------------------------------------------------------------- ferramentas de delegação

@mcp.tool()
def delegar(
    especificacao: Annotated[str, Field(description=(
        "Especificação autossuficiente: contexto curto, arquivos a LER, arquivos a criar/alterar e a NÃO "
        "tocar, contrato exato (assinaturas, formatos, erros) e critério de pronto."))],
    pasta: Annotated[str, Field(description="Caminho absoluto do repositório git onde o executor trabalha.")],
    verificacao: Annotated[str | None, Field(description=(
        "Comando que prova que está pronto, rodado na pasta depois do executor "
        "(ex.: '.venv/Scripts/python -m unittest tests.test_x'). Fortemente recomendado."))] = None,
    sessao: Annotated[str | None, Field(description=(
        "ID de sessão (ses_...) de um relatório anterior, para uma volta de correção com o contexto mantido."))] = None,
    modelo: Annotated[str | None, Field(description=(
        "Modelo do roteador local, no formato llama-local/<id> (veja a ferramenta modelos). "
        f"Padrão: {core.DEFAULT_MODEL}."))] = None,
    titulo: Annotated[str | None, Field(description="Título curto da sessão no OpenCode.")] = None,
    timeout_segundos: Annotated[int, Field(ge=60, le=7200, description="Limite da execução.")] = 1800,
) -> str:
    """Delega uma tarefa de código ao modelo local. Devolve um job_id na hora; acompanhe com status."""
    try:
        workdir = str(core.check_workdir(pasta))
    except core.DelegarError as e:
        return f"ERRO: {e}"
    job = {"id": uuid.uuid4().hex[:10], "state": "criado", "created": time.time(), "updated": time.time(),
           "spec": especificacao, "workdir": workdir, "verify": verificacao, "session": sessao,
           "model": modelo or core.DEFAULT_MODEL, "title": titulo or "delegar-mcp",
           "timeout": timeout_segundos, "server_pid": os.getpid()}
    _save(job)
    threading.Thread(target=_run_job, args=(job,), daemon=True, name=f"job-{job['id']}").start()
    return (f"job_id: {job['id']}\nDisparado em {workdir} com {job['model']}. "
            f"Acompanhe com status(job_id='{job['id']}', aguardar_segundos={MAX_WAIT}).")


@mcp.tool()
async def status(
    job_id: Annotated[str, Field(description="O job_id devolvido por delegar.")],
    aguardar_segundos: Annotated[int, Field(ge=0, le=MAX_WAIT, description=(
        f"Espera até o job terminar, no máximo isso (0 = responde já; máx. {MAX_WAIT})."))] = 0,
) -> str:
    """Estado de um job de delegação. Quando concluído, devolve o relatório completo para revisão."""
    deadline = time.monotonic() + aguardar_segundos
    while True:
        job = _load(job_id)
        if job is None:
            return f"ERRO: job {job_id} não existe."
        if job["state"] in ("concluido", "erro", "cancelado") or time.monotonic() >= deadline:
            return _describe(job)
        await asyncio.sleep(3)


@mcp.tool()
def cancelar(job_id: Annotated[str, Field(description="O job_id a cancelar.")]) -> str:
    """Mata o executor de um job em andamento (a árvore de processos do opencode)."""
    job = _load(job_id)
    if job is None:
        return f"ERRO: job {job_id} não existe."
    if job["state"] in ("concluido", "erro", "cancelado"):
        return f"job {job_id} já terminou ({job['state']})."
    pid = job.get("pid")
    if pid:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
    job.update(state="cancelado", updated=time.time())
    _save(job)
    return (f"job {job_id} cancelado. Arquivos que ele já tinha alterado continuam alterados em "
            f"{job['workdir']}: confira com git status.")


@mcp.tool()
def modelos() -> str:
    """Lista os modelos do roteador local (llama-server) e qual está carregado na VRAM agora.
    Trocar de modelo leva de 10 a 30 s (um modelo por vez na GPU)."""
    try:
        with urllib.request.urlopen(f"{core.ROUTER_URL}/v1/models", timeout=5) as r:
            data = json.load(r)["data"]
    except OSError as e:
        return f"ERRO: roteador fora do ar em {core.ROUTER_URL} ({e})."
    lines = []
    for m in data:
        st = (m.get("status") or {}).get("value", "?")
        lines.append(f"llama-local/{m['id']}  [{st}]" + ("  (padrão)" if f"llama-local/{m['id']}" == core.DEFAULT_MODEL else ""))
    return "\n".join(lines)


# ---------------------------------------------------------------- Antigravity (caminho cruzado)

def _pid_alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                         capture_output=True, text=True, errors="replace").stdout
    return f'"{pid}"' in out


def _antigravity_env() -> dict[str, str]:
    """O agentapi só fala com um Antigravity aberto. O app grava a porta e o token CSRF do seu
    servidor de linguagem em ~/.gemini/antigravity/daemon/hub_<porta>.json; pegamos o vivo mais novo."""
    hubs = sorted((AG_DIR / "daemon").glob("hub_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for h in hubs:
        info = json.loads(h.read_text(encoding="utf-8"))
        if _pid_alive(int(info["pid"])):
            env = dict(os.environ)
            fmt = os.environ.get("DELEGAR_AG_ADDRESS", "127.0.0.1:{httpPort}")
            env["ANTIGRAVITY_LS_ADDRESS"] = fmt.format(**info)
            env["ANTIGRAVITY_CSRF_TOKEN"] = info["csrfToken"]
            return env
    raise RuntimeError("Antigravity não está aberto (nenhum hub vivo em ~/.gemini/antigravity/daemon). "
                       "Abra o Antigravity e tente de novo.")


def _agentapi(*args: str, timeout: int = 120) -> str:
    try:
        env = _antigravity_env()
    except RuntimeError as e:
        return f"ERRO: {e}"
    r = subprocess.run(["cmd", "/c", str(AG_AGENTAPI), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, timeout=timeout, stdin=subprocess.DEVNULL)
    return (r.stdout + r.stderr).strip() or f"(agentapi saiu com {r.returncode} sem texto)"


def _pb_strings(b: bytes, path: tuple = (), depth: int = 0) -> list[tuple[tuple, str]] | None:
    """Decodificador protobuf genérico (sem schema): devolve (caminho de campos, texto) de cada
    string. Devolve None se o blob não for protobuf válido (aí ele é tratado como string)."""
    def varint(i: int) -> tuple[int, int]:
        r = s = 0
        while True:
            x = b[i]; i += 1; r |= (x & 0x7F) << s; s += 7
            if x < 0x80:
                return r, i
    out, i = [], 0
    try:
        while i < len(b):
            key, i = varint(i)
            f, wt = key >> 3, key & 7
            if f == 0:
                return None
            if wt == 0:
                _, i = varint(i)
            elif wt == 1:
                i += 8
            elif wt == 5:
                i += 4
            elif wt == 2:
                n, i = varint(i)
                chunk = b[i:i + n]; i += n
                sub = _pb_strings(chunk, path + (f,), depth + 1) if depth < 12 else None
                if sub:
                    out.extend(sub)
                else:
                    try:
                        out.append((path + (f,), chunk.decode("utf-8")))
                    except UnicodeDecodeError:
                        pass
            else:
                return None
    except IndexError:
        return None
    return out


AG_USER_STEP, AG_REPLY_STEP, AG_STEP_DONE = 14, 15, 3


def _ag_reply(conversa: str) -> tuple[bool, list[str]]:
    """Lê as respostas do agente direto do SQLite da conversa (só leitura). O agentapi não devolve
    o texto; ele fica em ~/.gemini/antigravity/conversations/<id>.db, tabela steps, em protobuf:
    passo tipo 15 = resposta do agente, texto no campo 20.1. Formato interno, sem documentação:
    pode quebrar numa atualização do Antigravity. Devolve (terminou, respostas desde a última pergunta)."""
    import sqlite3
    db = AG_DIR / "conversations" / f"{conversa}.db"
    if not db.exists():
        return False, []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute("select step_type, status, step_payload from steps order by idx").fetchall()
    finally:
        con.close()
    last_user = max((i for i, r in enumerate(rows) if r[0] == AG_USER_STEP), default=-1)
    replies, done = [], False
    for st, status, payload in rows[last_user + 1:]:
        if st == AG_REPLY_STEP and payload:
            txt = [s for p, s in (_pb_strings(payload) or []) if p == (20, 1)]
            if txt:
                replies.append(txt[0])
                done = status == AG_STEP_DONE
    return done, replies


async def _ag_wait(conversa: str, wait: int) -> str:
    deadline = time.monotonic() + wait
    while True:
        done, replies = _ag_reply(conversa)
        if done or time.monotonic() >= deadline:
            state = "concluída" if done else "em andamento (chame antigravity_conversa para esperar mais)"
            body = "\n\n".join(replies) if replies else "(sem resposta ainda)"
            return f"conversa: {conversa} · {state}\n\n{body}"
        await asyncio.sleep(3)


if ANTIGRAVITY:
    @mcp.tool()
    async def antigravity(
        prompt: Annotated[str, Field(description="O pedido ao agente do Antigravity (Gemini).")],
        modelo: Annotated[str, Field(description="flash_lite, flash, pro ou um model_id.")] = "flash",
        conversa: Annotated[str | None, Field(description=(
            "ID de uma conversa existente para continuar; vazio cria uma nova."))] = None,
        titulo: Annotated[str | None, Field(description="Título da conversa nova.")] = None,
        aguardar_segundos: Annotated[int, Field(ge=0, le=MAX_WAIT, description=(
            "Espera a resposta por até isso; 0 devolve só o ID da conversa."))] = 120,
    ) -> str:
        """Manda um prompt a um agente do Antigravity (Gemini) e devolve a resposta. Precisa do app
        aberto; usa a cota Google do usuário, não a GPU local. A conversa não tem workspace aberto:
        cite caminhos absolutos se o pedido envolver arquivos."""
        if conversa:
            out = _agentapi("send-message", conversa, prompt)
        else:
            args = ["new-conversation", f"--model={modelo}"]
            if titulo:
                args.append(f"--title={titulo}")
            out = _agentapi(*args, prompt)
            try:
                conversa = json.loads(out)["response"]["newConversation"]["conversationId"]
            except (ValueError, KeyError, TypeError):
                return out  # erro do agentapi (ex.: app fechado): devolve como veio
        if out.startswith("ERRO"):
            return out
        if aguardar_segundos == 0:
            return f"conversa: {conversa} (disparada; leia com antigravity_conversa)"
        await asyncio.sleep(2)  # o agente leva um instante para registrar a pergunta nova
        return await _ag_wait(conversa, aguardar_segundos)

    @mcp.tool()
    async def antigravity_conversa(
        conversa: Annotated[str, Field(description="ID da conversa.")],
        aguardar_segundos: Annotated[int, Field(ge=0, le=MAX_WAIT)] = 0,
    ) -> str:
        """Respostas do agente do Antigravity desde a última pergunta (espera até terminar, se pedido)."""
        return await _ag_wait(conversa, aguardar_segundos)


if __name__ == "__main__":
    mcp.run(transport="stdio")
