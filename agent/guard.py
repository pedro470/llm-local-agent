"""
Cerca das ferramentas do agente (usada por mcp_server.py).

1. Raízes permitidas: todo caminho é resolvido (resolve() segue symlinks e junctions e elimina '..')
   e só passa se cair dentro de uma raiz. Leitura: o projeto + as raízes de escrita.
   Escrita (criar, mover, copiar para, apagar): só as raízes de escrita.
   Padrão de escrita: <projeto>\\teste_sandbox. Para trocar, defina AGENT_WRITE_ROOTS com caminhos
   separados por ';' (ex.: set AGENT_WRITE_ROOTS=C:\\Users\\plepl\\Downloads;D:\\agente).
2. Lista de programas do run_command: o comando é quebrado com shlex e executado sem shell,
   então pipe, redirecionamento, ';' e '$()' não têm efeito. Só programas de leitura e
   diagnóstico entram; os que recebem caminho têm cada caminho conferido contra as raízes.
   Cada nome aponta para um .exe com caminho absoluto: o CreateProcess do Windows procura um
   programa sem caminho também na pasta atual, e um ls.exe plantado lá seria executado.

A recusa acontece antes da pergunta ao usuário: o humano só é chamado para o que já é permitido.
"""

import os
import shlex
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _roots_from_env(var: str, default: list[Path]) -> list[Path]:
    raw = os.environ.get(var)
    if not raw:
        return default
    return [Path(p).expanduser().resolve() for p in raw.split(os.pathsep) if p]


WRITE_ROOTS = _roots_from_env("AGENT_WRITE_ROOTS", [PROJECT_ROOT / "teste_sandbox"])
READ_ROOTS = [PROJECT_ROOT] + [r for r in WRITE_ROOTS if not r.is_relative_to(PROJECT_ROOT)]

# Programas só de leitura/diagnóstico. Ficam de fora os que escrevem, apagam ou executam
# outros programas (rm, mv, cp, find -exec, xargs, bash, cmd, powershell, python, curl...).
# Os utilitários GNU vêm do Git for Windows (usr\bin); os de sistema, do System32.
GIT_BIN = Path(os.environ.get("AGENT_GIT_BIN", r"C:\Program Files\Git\usr\bin"))
SYSTEM32 = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32"
ALLOWED_PROGRAMS = {
    **{name: GIT_BIN / f"{name}.exe" for name in (
        "ls", "pwd", "cat", "head", "tail", "wc", "du", "df", "stat", "file", "grep", "uname", "date", "which")},
    **{name: SYSTEM32 / f"{name}.exe" for name in ("whoami", "hostname", "tasklist", "systeminfo")},
}
# Programas cujos argumentos não são arquivos a ler (df só mostra espaço do volume; os do Windows
# usam opções com '/', como tasklist /FI, que pareceriam caminhos).
NO_PATH_CHECK = {"pwd", "df", "uname", "date", "which", "whoami", "hostname", "tasklist", "systeminfo"}


def check_path(path: str, write: bool = False) -> tuple[bool, Path | str]:
    """Devolve (True, caminho_resolvido) ou (False, mensagem de recusa)."""
    p = Path(path).expanduser().resolve()
    roots = WRITE_ROOTS if write else READ_ROOTS
    if any(p.is_relative_to(r) for r in roots):
        return True, p
    kind = "escrita" if write else "leitura"
    allowed = ", ".join(str(r) for r in roots)
    return False, f"🛑 Caminho '{path}' está fora das raízes de {kind} permitidas ({allowed}). Operação recusada."


def _looks_like_path(arg: str) -> bool:
    # '/' e '\' (separadores), ':' (unidade, C:), '~' e '.' (relativos). Um caminho no estilo do
    # Git, como /c/Windows, resolve aqui para C:\c\Windows: fora das raízes, então recusado.
    return any(ch in arg for ch in "/\\:") or arg.startswith(("~", ".")) or Path(arg).exists()


def check_command(command: str) -> tuple[bool, list[str] | str]:
    """Devolve (True, argv) pronto para subprocess.run(shell=False) ou (False, mensagem de recusa)."""
    try:
        # posix=True de propósito: aspas e espaços como no bash; a barra invertida vira escape,
        # então caminhos do Windows vão com '/' (C:/Users/...), que os dois lados entendem.
        argv = shlex.split(command)
    except ValueError as e:
        return False, f"🛑 Comando mal formado: {e}"
    if not argv:
        return False, "🛑 Comando vazio."

    program = argv[0].removesuffix(".exe")
    if program not in ALLOWED_PROGRAMS:
        return False, f"🛑 Programa '{argv[0]}' não está na lista permitida: {', '.join(sorted(ALLOWED_PROGRAMS))}."

    if program not in NO_PATH_CHECK:
        for arg in argv[1:]:
            if arg.startswith("-"):
                # Opção com valor colado (--file=C:/x): o valor é conferido como caminho.
                arg = arg.partition("=")[2]
                if not arg:
                    continue
            if _looks_like_path(arg):
                ok, msg = check_path(arg)
                if not ok:
                    return False, msg
    return True, [str(ALLOWED_PROGRAMS[program])] + argv[1:]


def describe_roots() -> str:
    """Texto curto para o prompt de sistema."""
    return (
        f"Raízes de leitura: {', '.join(str(r) for r in READ_ROOTS)}. "
        f"Raízes de escrita (criar, mover, copiar, apagar): {', '.join(str(r) for r in WRITE_ROOTS)}. "
        f"run_command aceita só: {', '.join(sorted(ALLOWED_PROGRAMS))}, sem pipe nem redirecionamento."
    )
