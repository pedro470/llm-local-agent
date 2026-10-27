from datetime import datetime
import subprocess
from pathlib import Path
import shutil
from guard import check_path, check_command

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRASH_DIR = PROJECT_ROOT / ".trash"

def validade_path(path: Path, is_dir: bool = False, is_file: bool = False):
    if path is None:
        return False, "Path não definido"
    if not path.exists():
        return False, "Path não existe"
    if is_dir and not path.is_dir():
        return False, "Path não é um diretório"
    if is_file and not path.is_file():
        return False, "Path não é um arquivo"
    return True, None

def read_file(filepath: str, max_chars: int = 2000) -> str:
    # O Ollama repassa os argumentos como o modelo os escreveu, sem validar o schema:
    # o llama3.1:8b manda max_chars como texto ('1000'). Converte antes de usar.
    try:
        max_chars = int(max_chars)
    except (TypeError, ValueError):
        return f"Erro: max_chars precisa ser um número inteiro, mas veio {max_chars!r}."
    try:
        allowed, p = check_path(filepath)
        if not allowed:
            return p
        is_valid, message = validade_path(p, is_file=True)
        if not is_valid:
            return message
        with open(p, 'r', encoding='utf-8') as f:
            content = f.read(max_chars + 1)
            if len(content) > max_chars:
                size = p.stat().st_size
                return f"O conteúdo do arquivo '{filepath}' foi truncado. O arquivo tem {size} bytes no disco, mas apenas os primeiros {max_chars} caracteres foram exibidos.\n\nInício do conteúdo:\n{content[:max_chars]}...\n\nFim do conteúdo truncado."
        return content
    except UnicodeDecodeError:
        return f"Não foi possível ler o arquivo '{filepath}', provavelmente é um arquivo binário."
    except FileNotFoundError:
        return f"Arquivo '{filepath}' não encontrado"
    except Exception as e:
        return f"Erro ao ler arquivo: {e}"

def list_files(directory: str) -> str:
    """Lista os arquivos e diretórios do caminho especificado"""
    try:
        allowed, p = check_path(directory)
        if not allowed:
            return p
        is_valid, message = validade_path(p, is_dir=True)
        if not is_valid:
            return message
        files = [
            f"{'DIR' if item.is_dir() else 'FILE'} | {item.name}"
            for item in p.iterdir()
        ]
        return ", ".join(files)
    except FileNotFoundError:
        return f"Diretório '{directory}' não encontrado"
    except Exception as e:
        return f"Erro ao listar arquivos: {e}"

def create_directory(directory_path: str) -> str:
    try:
        allowed, p = check_path(directory_path, write=True)
        if not allowed:
            return p
        if p.is_file():
            return f"Erro: '{directory_path}' já existe e é um arquivo."
        if p.is_dir():
            return f"Diretório '{directory_path}' já existe."
            
        p.mkdir(parents=True, exist_ok=True)
        return f"Diretório '{directory_path}' criado com sucesso."
    except Exception as e:
        return f"Erro ao criar diretório: {e}"

def move_file(source_path: str, dest_path: str) -> str:
    try:
        # Mover tira o arquivo da origem: origem e destino precisam estar em raiz de escrita.
        allowed, src_path = check_path(source_path, write=True)
        if not allowed:
            return src_path
        allowed, dst_path = check_path(dest_path, write=True)
        if not allowed:
            return dst_path

        if not src_path.is_file():
            return f"Erro: Origem '{source_path}' não existe ou não é um arquivo."

        if not dst_path.is_dir():
            return f"Erro: O destino '{dest_path}' não é um diretório. Crie o diretório antes de mover o arquivo."
        
        target_file = dst_path / src_path.name

        if target_file.exists():
            return f"Erro: O destino '{target_file}' já existe. Sobrescrita bloqueada."

        shutil.move(src_path, target_file)
        return f"Arquivo '{source_path}' movido com sucesso para '{dest_path}'."
    except Exception as e:
        return f"Erro ao mover arquivo ou diretório: {e}"


def copy_file(source_path: str, dest_path: str) -> str:
    try:
        # Copiar só lê a origem; o destino recebe um arquivo novo e precisa ser raiz de escrita.
        allowed, src_path = check_path(source_path)
        if not allowed:
            return src_path
        allowed, dst_path = check_path(dest_path, write=True)
        if not allowed:
            return dst_path

        if not src_path.is_file():
            return f"Erro: Origem '{source_path}' não existe ou não é um arquivo."

        if not dst_path.is_dir():
            return f"Erro: O destino '{dest_path}' não é um diretório. Crie o diretório antes de copiar o arquivo."
        
        target_file = dst_path / src_path.name

        if target_file.exists():
            return f"Erro: O destino '{target_file}' já existe. Sobrescrita bloqueada."

        shutil.copy2(src_path, target_file)
        return f"Arquivo '{source_path}' foi copiado com sucesso para '{dest_path}'."
    except Exception as e:
        return f"Erro ao copiar arquivo ou diretório: {e}"

def delete_file(source_path: str) -> str:
    try:
        allowed, p = check_path(source_path, write=True)
        if not allowed:
            return p
        if not p.is_file():
            return f"Erro: Origem '{source_path}' não existe ou não é um arquivo."

        confirm = input(f"⚠️ [SEGURANÇA] O agente solicitou DELETAR o arquivo '{source_path}'. Confirma mover para quarentena (.trash)? (s/n): ")
        if confirm.lower() != 's':
            return f"Deletar arquivo '{source_path}' cancelado pelo usuário."

        TRASH_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        quarantine_target = TRASH_DIR / f"{timestamp}_{p.name}"
        shutil.move(p, quarantine_target)
        return f"Arquivo '{source_path}' movido com segurança para a quarentena em '{quarantine_target}'."
    except Exception as e:
        return f"Erro ao deletar arquivo: {e}"

def run_command(command: str) -> str:
    try:
        allowed, argv = check_command(command)
        if not allowed:
            return argv

        authorizarion = input(f"⚠️ [SEGURANÇA] O agente solicitou executar o comando '{command}'. Confirma executar? (s/n): ")
        if authorizarion.lower() != 's':
            return f"Comando '{command}' cancelado pelo usuário."

        # shell=False: argv vai direto para execve(); não há bash para interpretar | > ; $()
        result = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=30
            )
        if result.returncode != 0:
            return f"Erro: {result.stderr}"
        output = result.stdout.strip()
        if not output:
            return f"Comando '{command}' executado com sucesso, mas não retornou saída."
        return f"Output: {output}"
    except subprocess.TimeoutExpired:
        return f"Erro: Comando '{command}' excedeu o tempo limite de 30 segundos."
    except Exception as e:
        return f"Erro ao executar comando: {e}"

AVAILABLE_TOOLS = {
    "list_files": list_files,
    "read_file": read_file,
    "create_directory": create_directory,
    "move_file": move_file,
    "copy_file": copy_file,
    "delete_file": delete_file,
    "run_command": run_command,
}

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "Lista os arquivos e subpastas de um diretório especificado, indicando se cada item é DIR ou FILE.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "O caminho do diretório a ser listado. Use caminhos relativos ao diretório atual (ex: '.' ou 'agent') ou caminhos absolutos existentes.",
                    }
                },
                "required": ["directory"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Lê o conteúdo de um arquivo especificado, limitando o tamanho da leitura.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "O caminho do arquivo a ser lido. Use caminhos relativos ao diretório atual (ex: '.' ou 'agent') ou caminhos absolutos existentes.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "O número máximo de caracteres a serem lidos do arquivo. Se o arquivo for maior, o conteúdo será truncado.",
                        "default": 2000
                    }
                },
                "required": ["filepath"]
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_directory",
            "description": "Cria um diretório especificado",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory_path": {
                        "type": "string",
                        "description": "O caminho do diretório a ser criado. Use caminhos relativos ao diretório atual (ex: '.' ou 'agent') ou caminhos absolutos existentes.",
                    }
                },
                "required": ["directory_path"]
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_file",
            "description": "Move um arquivo para um diretório de destino",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_path": {
                        "type": "string",
                        "description": "O caminho do arquivo a ser movido. Use caminhos relativos ao diretório atual (ex: '.' ou 'agent') ou caminhos absolutos existentes.",
                    },
                    "dest_path": {
                        "type": "string",
                        "description": "O caminho do diretório existente de destino. Use caminhos relativos ao diretório atual (ex: '.' ou 'agent') ou caminhos absolutos existentes.",
                    }
                },
                "required": ["source_path", "dest_path"]
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "copy_file",
            "description": "Copia um arquivo para um diretório de destino",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_path": {
                        "type": "string",
                        "description": "O caminho do arquivo a ser copiado. Use caminhos relativos ao diretório atual (ex: '.' ou 'agent') ou caminhos absolutos existentes.",
                    },
                    "dest_path": {
                        "type": "string",
                        "description": "O caminho do diretório existente de destino. Use caminhos relativos ao diretório atual (ex: '.' ou 'agent') ou caminhos absolutos existentes.",
                    }
                },
                "required": ["source_path", "dest_path"]
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Remove um arquivo movendo-o para a quarentena (.trash) após confirmação humana.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_path": {
                        "type": "string",
                        "description": "O caminho do arquivo a ser deletado. Use caminhos relativos ao diretório atual (ex: '.' ou 'agent') ou caminhos absolutos existentes.",
                    }
                },
                "required": ["source_path"]
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Executa um comando de leitura ou diagnóstico no Linux (WSL2), sem shell: pipe, redirecionamento e ';' não funcionam. Programas permitidos: ls, pwd, cat, head, tail, wc, du, df, stat, file, grep, uname, whoami, date, uptime, free, ps, which.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "O comando a ser executado. Use caminhos relativos ao diretório atual (ex: '.' ou 'agent') ou caminhos absolutos existentes.",
                    }
                },
                "required": ["command"]
            },
        },
    }
]
