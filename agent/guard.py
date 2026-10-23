"""
Cerca das ferramentas do agente (usada por tools.py e mcp_server.py).

1. Raízes permitidas: todo caminho é resolvido (resolve() segue symlinks e elimina '..')
   e só passa se cair dentro de uma raiz. Leitura: o projeto + as raízes de escrita.
   Escrita (criar, mover, copiar para, apagar): só as raízes de escrita.
   Padrão de escrita: <projeto>/teste_sandbox. Para trocar, defina AGENT_WRITE_ROOTS
   com caminhos separados por ':' (ex.: export AGENT_WRITE_ROOTS=~/Downloads:/tmp/agente).
2. Lista de programas do run_command: o comando é quebrado com shlex e executado sem shell,
   então pipe, redirecionamento, ';' e '$()' não têm efeito. Só programas de leitura e
   diagnóstico entram; os que recebem caminho têm cada caminho conferido contra as raízes.

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
# outros programas (rm, mv, cp, chmod, find -exec, xargs, bash, python, curl...).
ALLOWED_PROGRAMS = {
    "ls", "pwd", "cat", "head", "tail", "wc", "du", "df", "stat", "file", "grep",
    "uname", "whoami", "date", "uptime", "free", "ps", "which",
}
# Programas cujos argumentos não são arquivos a ler (df só mostra espaço do volume).
NO_PATH_CHECK = {"pwd", "df", "uname", "whoami", "date", "uptime", "free", "ps", "which"}


def check_path(path: str, write: bool = False) -> tuple[bool, Path | str]:
    """Devolve (True, caminho_resolvido) ou (False, mensagem de recusa)."""
    p = Path(path).expanduser().resolve()
    roots = WRITE_ROOTS if write else READ_ROOTS
    if any(p.is_relative_to(r) for r in roots):
        return True, p
    kind = "escrita" if write else "leitura"
    allowed = ", ".join(str(r) for r in roots)
    return False, f"🛑 Caminho '{path}' está fora das raízes de {kind} permitidas ({allowed}). Operação recusada."


def check_command(command: str) -> tuple[bool, list[str] | str]:
    """Devolve (True, argv) pronto para subprocess.run(shell=False) ou (False, mensagem de recusa)."""
    try:
        argv = shlex.split(command)
    except ValueError as e:
        return False, f"🛑 Comando mal formado: {e}"
    if not argv:
        return False, "🛑 Comando vazio."

    program = argv[0]
    if program not in ALLOWED_PROGRAMS:
        return False, f"🛑 Programa '{program}' não está na lista permitida: {', '.join(sorted(ALLOWED_PROGRAMS))}."

    if program not in NO_PATH_CHECK:
        for arg in argv[1:]:
            if arg.startswith("-"):
                continue
            if "/" in arg or arg.startswith(("~", ".")) or Path(arg).exists():
                ok, msg = check_path(arg)
                if not ok:
                    return False, msg
    return True, argv


def describe_roots() -> str:
    """Texto curto para o prompt de sistema."""
    return (
        f"Raízes de leitura: {', '.join(str(r) for r in READ_ROOTS)}. "
        f"Raízes de escrita (criar, mover, copiar, apagar): {', '.join(str(r) for r in WRITE_ROOTS)}. "
        f"run_command aceita só: {', '.join(sorted(ALLOWED_PROGRAMS))}, sem pipe nem redirecionamento."
    )
