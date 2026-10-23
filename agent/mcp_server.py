"""
Servidor MCP (Model Context Protocol) Local de Sistema de Arquivos
Implementado com o SDK oficial da Anthropic (mcp v2 - MCPServer)
Transporte: STDIO (JSON-RPC sobre standard input/output)

Blindagem de Segurança (Defense-in-Depth):
1. Sem flags de bypass no schema (o LLM não pode enviar force=True).
2. Human-in-the-Loop (HITL) via /dev/tty direto no kernel Linux (sem corromper o pipe stdio).
   Se não houver terminal interativo (/dev/tty indisponível), opera em Fail-Closed (bloqueia).
3. Soft-Delete (Quarentena): arquivos "deletados" são movidos para a pasta .trash/ com timestamp,
   nunca destruídos permanentemente via unlink().
"""

from datetime import datetime
from pathlib import Path
import shutil
import subprocess
from mcp.server.mcpserver import MCPServer

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


def _ask_tty_confirmation(action_description: str) -> tuple[bool, str]:
    """
    Solicita confirmação humana diretamente no terminal físico (/dev/tty),
    isolado dos pipes sys.stdin e sys.stdout usados pelo JSON-RPC do MCP.
    Opera em modo Fail-Closed: se não houver terminal acessível, nega a ação.
    """
    try:
        with open("/dev/tty", "r+", encoding="utf-8") as tty:
            tty.write(f"\n⚠️  [SEGURANÇA HITL - MCP SERVER] {action_description}\n")
            tty.write("👉 Digite 's' para autorizar ou qualquer outra tecla para bloquear: ")
            tty.flush()
            resposta = tty.readline().strip().lower()
            if resposta == "s":
                return True, "Autorizado pelo usuário no terminal."
            return False, "Operação bloqueada pelo usuário no terminal."
    except OSError:
        # Fail-Closed: se rodar em background sem TTY humano conectado, bloqueia!
        return (
            False,
            "Operação bloqueada automaticamente (Fail-Closed): Nenhum terminal humano (/dev/tty) disponível para confirmar a ação.",
        )


@mcp.tool()
def list_files(directory: str = ".") -> str:
    """Lista os arquivos e subpastas de um diretório especificado, indicando se cada item é DIR ou FILE."""
    try:
        p = Path(directory).expanduser().resolve()
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
def read_file(filepath: str, max_chars: int = 2000) -> str:
    """Lê o conteúdo textual de um arquivo até o limite de caracteres especificado."""
    try:
        p = Path(filepath).expanduser().resolve()
        is_valid, msg = _validate_path(p, is_file=True)
        if not is_valid:
            return msg
        with open(p, "r", encoding="utf-8") as f:
            content = f.read(max_chars + 1)
            if len(content) > max_chars:
                return (
                    f"Aviso: Conteúdo truncado em {max_chars} caracteres.\n\n"
                    f"{content[:max_chars]}...\n[Fim do trecho truncado]"
                )
            return content
    except UnicodeDecodeError:
        return f"Erro: O arquivo '{filepath}' é binário ou não está em UTF-8."
    except Exception as e:
        return f"Erro ao ler arquivo: {e}"


@mcp.tool()
def create_directory(directory_path: str) -> str:
    """Cria um novo diretório (e diretórios pais intermediários se necessário)."""
    try:
        p = Path(directory_path).expanduser().resolve()
        if p.is_file():
            return f"Erro: '{directory_path}' já existe e é um arquivo."
        if p.is_dir():
            return f"Diretório '{directory_path}' já existe."
        p.mkdir(parents=True, exist_ok=True)
        return f"Diretório '{p}' criado com sucesso."
    except Exception as e:
        return f"Erro ao criar diretório: {e}"


@mcp.tool()
def move_file(source_path: str, dest_path: str) -> str:
    """Move um arquivo da origem para o diretório de destino."""
    try:
        src = Path(source_path).expanduser().resolve()
        dst = Path(dest_path).expanduser().resolve()

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
def copy_file(source_path: str, dest_path: str) -> str:
    """Copia um arquivo da origem para o diretório de destino preservando metadados."""
    try:
        src = Path(source_path).expanduser().resolve()
        dst = Path(dest_path).expanduser().resolve()

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
def delete_file(source_path: str) -> str:
    """Remove um arquivo movendo-o para a quarentena (.trash) após confirmação humana obrigatória no terminal."""
    try:
        p = Path(source_path).expanduser().resolve()
        if not p.is_file():
            return f"Erro: '{source_path}' não existe ou não é um arquivo."

        # 1. Trava física no terminal (/dev/tty) - O LLM NÃO tem como contornar
        authorized, reason = _ask_tty_confirmation(
            f"O agente solicitou DELETAR o arquivo: '{p}'"
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
def run_command(command: str) -> str:
    """Executa um comando bash no ambiente Linux WSL2 com timeout de 30s após confirmação humana obrigatória."""
    try:
        # 1. Filtro estático de comandos catastróficos
        prohibited = ["rm -rf /", "mkfs", "dd if=", ":(){ :|:& };:"]
        if any(p in command for p in prohibited):
            return f"🛑 Comando '{command}' bloqueado permanentemente por política de segurança."

        # 2. Trava física no terminal (/dev/tty) - O LLM NÃO tem como contornar
        authorized, reason = _ask_tty_confirmation(
            f"O agente solicitou EXECUTAR O COMANDO BASH: `{command}`"
        )
        if not authorized:
            return f"🛑 {reason}"

        result = subprocess.run(
            command,
            shell=True,
            executable="/bin/bash",
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


if __name__ == "__main__":
    # Inicia o servidor escutando em STDIO (padrão do protocolo MCP)
    # Comunicação ocorre via JSON-RPC 2.0 através do pipe sys.stdin e sys.stdout
    mcp.run(transport="stdio")
