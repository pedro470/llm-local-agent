"""
Servidor MCP (Model Context Protocol) Local de Sistema de Arquivos
Implementado com o SDK oficial da Anthropic (mcp v2 - MCPServer)
Transporte: STDIO (JSON-RPC sobre standard input/output)

Blindagem de Segurança (Defense-in-Depth):
1. Sem flags de bypass no schema (o LLM não pode enviar force=True).
2. Human-in-the-Loop (HITL) por elicitation do MCP: o servidor manda um elicitation/create
   pelo próprio canal JSON-RPC e o cliente pergunta ao humano. Fail-Closed: se o cliente não
   suportar elicitation, recusar, cancelar ou der erro, a ação é bloqueada.
   (O /dev/tty não serve: o SDK cria o servidor com start_new_session=True, então o processo
   filho não tem terminal de controle e open("/dev/tty") falha sempre.)
3. Soft-Delete (Quarentena): arquivos "deletados" são movidos para a pasta .trash/ com timestamp,
   nunca destruídos permanentemente via unlink().
4. Cerca (guard.py): caminhos só dentro das raízes permitidas e run_command só com programas
   da lista, executados sem shell. A recusa vem antes da pergunta ao humano.
"""

import asyncio
from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess
from typing import Annotated
from pydantic import BaseModel, Field
from mcp.server.mcpserver import Context, MCPServer
from guard import check_path, check_command
import routines

# Descrições que entram no JSON Schema de cada parâmetro (o modelo lê pelo tools/list).
# Exemplos neutros ('.', 'agent') de propósito: exemplo concreto o modelo copia (example poisoning).
_REL = "Use caminhos relativos ao diretório atual (ex: '.' ou 'agent') ou caminhos absolutos existentes."
Dir = Annotated[str, Field(description=f"Caminho de um diretório existente. {_REL}")]
File = Annotated[str, Field(description=f"Caminho de um arquivo existente. {_REL}")]

# Inicializa o servidor MCP
mcp = MCPServer("LocalFilesystem")

# Diretório de quarentena (Soft-Delete) na raiz do projeto
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRASH_DIR = PROJECT_ROOT / ".trash"


def _validate_path(path: Path, is_dir: bool = False, is_file: bool = False):
    if path is None:
        return False, "Path não definido"
    if not path.exists():
        return False, f"Path '{path}' não existe"
    if is_dir and not path.is_dir():
        return False, f"Path '{path}' não é um diretório"
    if is_file and not path.is_file():
        return False, f"Path '{path}' não é um arquivo"
    return True, None


class Confirmacao(BaseModel):
    """Formulário da elicitation: um único campo booleano."""
    autorizar: bool = Field(description="true para autorizar a ação, false para bloquear")


async def _ask_confirmation(ctx: Context, action_description: str) -> tuple[bool, str]:
    """
    Pede a confirmação humana pelo cliente MCP (elicitation/create).
    Só autoriza com action == "accept" E autorizar == true. Qualquer outra coisa bloqueia.
    """
    try:
        result = await ctx.elicit(message=f"[SEGURANÇA] {action_description}", schema=Confirmacao)
    except Exception as e:
        # Cliente sem suporte a elicitation, sem humano ou erro de transporte: Fail-Closed.
        return False, f"Operação bloqueada automaticamente (Fail-Closed): não foi possível pedir confirmação ao humano ({e})."
    if result.action == "accept" and result.data.autorizar:
        return True, "Autorizado pelo usuário no terminal."
    # A regra 7 do system_prompt.py reconhece "cancelada pelo usuário": mudar os dois juntos.
    return False, "Operação cancelada pelo usuário no terminal. Nada foi alterado."


@mcp.tool()
def list_files(directory: Dir = ".") -> str:
    """Lista os arquivos e subpastas de um diretório especificado, indicando se cada item é DIR ou FILE."""
    try:
        allowed, p = check_path(directory)
        if not allowed:
            return p
        is_valid, msg = _validate_path(p, is_dir=True)
        if not is_valid:
            return msg
        items = []
        for item in p.iterdir():
            prefix = "DIR" if item.is_dir() else "FILE"
            items.append(f"{prefix} | {item.name}")
        return "\n".join(items) if items else "(Diretório vazio)"
    except Exception as e:
        return f"Erro ao listar arquivos: {e}"


@mcp.tool()
def read_file(
    filepath: File,
    max_chars: Annotated[int, Field(description="Máximo de caracteres a ler; acima disso o conteúdo é truncado.")] = 2000,
) -> str:
    """Lê o conteúdo textual de um arquivo até o limite de caracteres especificado."""
    try:
        allowed, p = check_path(filepath)
        if not allowed:
            return p
        is_valid, msg = _validate_path(p, is_file=True)
        if not is_valid:
            return msg
        with open(p, "r", encoding="utf-8") as f:
            content = f.read(max_chars + 1)
            if len(content) > max_chars:
                return (
                    f"Aviso: Conteúdo truncado em {max_chars} caracteres. O arquivo tem {p.stat().st_size} bytes no disco.\n\n"
                    f"{content[:max_chars]}...\n[Fim do trecho truncado]"
                )
            return content
    except UnicodeDecodeError:
        return f"Erro: O arquivo '{filepath}' é binário ou não está em UTF-8."
    except Exception as e:
        return f"Erro ao ler arquivo: {e}"


@mcp.tool()
def create_directory(
    directory_path: Annotated[str, Field(description=f"Caminho do diretório a criar. {_REL}")],
) -> str:
    """Cria um novo diretório (e diretórios pais intermediários se necessário)."""
    try:
        allowed, p = check_path(directory_path, write=True)
        if not allowed:
            return p
        if p.is_file():
            return f"Erro: '{directory_path}' já existe e é um arquivo."
        if p.is_dir():
            return f"Diretório '{directory_path}' já existe."
        p.mkdir(parents=True, exist_ok=True)
        return f"Diretório '{p}' criado com sucesso."
    except Exception as e:
        return f"Erro ao criar diretório: {e}"


@mcp.tool()
def move_file(source_path: File, dest_path: Dir) -> str:
    """Move um arquivo da origem para o diretório de destino."""
    try:
        allowed, src = check_path(source_path, write=True)
        if not allowed:
            return src
        allowed, dst = check_path(dest_path, write=True)
        if not allowed:
            return dst

        if not src.is_file():
            return f"Erro: Origem '{source_path}' não existe ou não é um arquivo."
        if not dst.is_dir():
            return f"Erro: Destino '{dest_path}' não é um diretório existente."

        target = dst / src.name
        if target.exists():
            return f"Erro: O destino '{target}' já existe. Sobrescrita bloqueada."

        shutil.move(src, target)
        return f"Arquivo '{src.name}' movido com sucesso para '{dst}'."
    except Exception as e:
        return f"Erro ao mover arquivo: {e}"


@mcp.tool()
def copy_file(source_path: File, dest_path: Dir) -> str:
    """Copia um arquivo da origem para o diretório de destino preservando metadados."""
    try:
        allowed, src = check_path(source_path)
        if not allowed:
            return src
        allowed, dst = check_path(dest_path, write=True)
        if not allowed:
            return dst

        if not src.is_file():
            return f"Erro: Origem '{source_path}' não existe ou não é um arquivo."
        if not dst.is_dir():
            return f"Erro: Destino '{dest_path}' não é um diretório existente."

        target = dst / src.name
        if target.exists():
            return f"Erro: O destino '{target}' já existe. Sobrescrita bloqueada."

        shutil.copy2(src, target)
        return f"Arquivo '{src.name}' copiado com sucesso para '{dst}'."
    except Exception as e:
        return f"Erro ao copiar arquivo: {e}"


@mcp.tool()
async def delete_file(source_path: File, ctx: Context) -> str:
    """Remove um arquivo movendo-o para a quarentena (.trash) após confirmação humana obrigatória no terminal."""
    # ctx é injetado pelo MCPServer (não aparece no schema que o modelo vê).
    try:
        allowed, p = check_path(source_path, write=True)
        if not allowed:
            return p
        if not p.is_file():
            return f"Erro: '{source_path}' não existe ou não é um arquivo."

        # 1. Confirmação humana pelo cliente (elicitation) - o LLM não tem como responder por você
        authorized, reason = await _ask_confirmation(
            ctx, f"O agente solicitou DELETAR o arquivo: '{p}'"
        )
        if not authorized:
            return f"🛑 {reason}"

        # 2. Soft-Delete (Quarentena em .trash/ em vez de unlink destrutivo)
        TRASH_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        quarantine_target = TRASH_DIR / f"{timestamp}_{p.name}"

        shutil.move(p, quarantine_target)
        return (
            f"Arquivo '{p.name}' removido do local original e movido com segurança "
            f"para a quarentena em '{quarantine_target}'."
        )
    except Exception as e:
        return f"Erro ao deletar arquivo: {e}"


@mcp.tool()
async def run_command(
    command: Annotated[str, Field(description="Linha de comando com um programa da lista permitida e seus argumentos.")],
    ctx: Context,
) -> str:
    """Executa um comando de leitura ou diagnóstico no Linux WSL2, sem shell, com timeout de 30s após confirmação humana obrigatória. Programas permitidos: ls, pwd, cat, head, tail, wc, du, df, stat, file, grep, uname, whoami, date, uptime, free, ps, which."""
    try:
        # 1. Lista de programas permitidos + caminhos dentro das raízes (guard.py)
        allowed, argv = check_command(command)
        if not allowed:
            return argv

        # 2. Confirmação humana pelo cliente (elicitation) - o LLM não tem como responder por você
        authorized, reason = await _ask_confirmation(
            ctx, f"O agente solicitou EXECUTAR O COMANDO: `{command}`"
        )
        if not authorized:
            return f"🛑 {reason}"
        return await _execute(argv, command)
    except Exception as e:
        return f"Erro ao executar comando: {e}"


async def _execute(argv: list[str], command: str) -> str:
    """Roda um argv já aprovado pela cerca e pelo humano (pelo run_command ou pela rotina)."""
    try:
        # shell=False: argv vai direto para execve(); não há bash para interpretar | > ; $()
        # to_thread: o comando pode levar até 30 s e não deve travar o laço de eventos do servidor.
        result = await asyncio.to_thread(
            subprocess.run,
            argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return f"Exit code {result.returncode}. Erro:\n{result.stderr.strip()}"
        out = result.stdout.strip()
        return out if out else "(Comando executado com sucesso sem saída)"
    except subprocess.TimeoutExpired:
        return f"Erro: Timeout de 30s excedido ao executar '{command}'."
    except Exception as e:
        return f"Erro ao executar comando: {e}"


# Ferramentas que uma rotina pode chamar direto; run_command e delete_file têm tratamento próprio.
ROUTINE_TOOLS = {f.__name__: f for f in (list_files, read_file, create_directory, move_file, copy_file)}


@mcp.tool()
async def run_routine(
    name: Annotated[str, Field(description="Nome exato de uma rotina da seção ROTINAS do prompt de sistema.")],
    ctx: Context,
    params: Annotated[dict[str, str] | None, Field(description="Parâmetros da rotina, com os nomes que a seção ROTINAS mostra.")] = None,
) -> str:
    """Executa uma rotina pronta do início ao fim e devolve o relatório. Pede uma confirmação ao usuário no terminal antes de qualquer passo que escreva ou execute comando."""

    async def call(tool: str, args: dict) -> str:
        if tool == "run_command":
            # A cerca já conferiu o comando em routines.run, antes da pergunta; confere de novo aqui
            # porque é este código que executa. A aprovação do humano veio na pergunta da rotina.
            allowed, argv = check_command(args.get("command", ""))
            return await _execute(argv, args["command"]) if allowed else argv
        try:
            if tool == "delete_file":
                return await delete_file(ctx=ctx, **args)  # pergunta de novo, arquivo por arquivo
            if tool not in ROUTINE_TOOLS:
                return f"Erro: a ferramenta '{tool}' não pode ser usada em rotina."
            return ROUTINE_TOOLS[tool](**args)
        except TypeError as e:
            return f"Erro: argumentos inválidos para {tool}: {e}"

    async def confirm(text: str) -> tuple[bool, str]:
        return await _ask_confirmation(ctx, text)

    if isinstance(params, str):  # modelos às vezes mandam o objeto como texto JSON
        try:
            params = json.loads(params)
        except json.JSONDecodeError:
            return f"Erro: params deve ser um objeto, recebi {params!r}."
    return await routines.run(name, params or {}, call, confirm)


if __name__ == "__main__":
    # Inicia o servidor escutando em STDIO (padrão do protocolo MCP)
    # Comunicação ocorre via JSON-RPC 2.0 através do pipe sys.stdin e sys.stdout
    mcp.run(transport="stdio")
