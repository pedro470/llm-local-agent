"""
Rotinas: arquivos YAML em routines/ que este executor roda passo a passo, sem o modelo no meio.

O modelo só escolhe a rotina e os parâmetros (ferramenta run_routine do mcp_server.py). A ordem
dos passos, a expansão dos arquivos e as condições são decididas aqui, em Python: o mesmo pedido
produz sempre as mesmas ações, e um modelo de 12B não tem como pular passo nem inventar resultado.

Cada passo chama as mesmas funções das ferramentas, então a cerca (guard.py) vale igual.
Confirmação humana:
- Uma pergunta só, antes de começar, com a lista de tudo que escreve ou executa comando.
- delete_file continua perguntando arquivo por arquivo (ação destrutiva).

Formato de um arquivo (ver os exemplos em routines/):
  name, description
  params:   {nome: {description, default?}}           -> usados como {nome} nos textos
  steps:    lista de passos, cada um com UMA destas chaves:
    tool:     nome da ferramenta, com args: {...} e save: var (guarda a saída para condições)
    for_each: {dir, patterns}, com as: var, before: [passos], steps: [passos]
              (before roda uma vez, só se algum arquivo casou; ex.: criar a pasta de destino)
    say:      texto para o relatório final ({var} vale para parâmetros e saídas guardadas)
    stop:     true encerra a rotina
  Qualquer passo aceita when: {var, matches (regex), not_matches, gte, lt}. Com matches e um
  grupo de captura, gte/lt comparam o número capturado.
"""

import fnmatch
import re
from pathlib import Path

import yaml

from guard import PROJECT_ROOT, check_command, check_path

ROUTINES_DIR = PROJECT_ROOT / "routines"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")  # o nome vira caminho de arquivo: nada de "../"
VAR_RE = re.compile(r"\{(\w+)\}")
# Passos que passam pela pergunta única do começo da rotina.
NEEDS_APPROVAL = {"create_directory", "move_file", "copy_file", "delete_file", "run_command"}
STEP_KINDS = ("tool", "for_each", "say", "stop")


class RoutineError(Exception):
    pass


def _load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
        raise RoutineError(f"{path.name}: precisa de 'steps' (lista de passos)")
    return data


def list_routines() -> list[dict]:
    out = []
    for path in sorted(ROUTINES_DIR.glob("*.yaml")):
        try:
            data = _load(path)
        except (RoutineError, yaml.YAMLError) as e:
            out.append({"name": path.stem, "description": f"(arquivo inválido: {e})", "params": {}})
            continue
        out.append({"name": path.stem, "description": data.get("description", ""), "params": data.get("params") or {}})
    return out


def describe_catalog() -> str:
    """Uma linha por rotina, para o prompt de sistema: o modelo chama run_routine direto, sem um
    passo de consulta antes (com esse passo extra, ele anunciava a rotina e parava em 1 de 3 vezes)."""
    lines = []
    for r in list_routines():
        params = "; ".join(
            f"{name} ({(spec or {}).get('description', '')}"
            + (f", padrão: {spec['default']}" if isinstance(spec, dict) and "default" in spec else "") + ")"
            for name, spec in r["params"].items()
        )
        lines.append(f"- {r['name']}: {r['description']}" + (f" Parâmetros: {params}." if params else ""))
    return "\n".join(lines) or "- (nenhuma rotina em routines/)"


def load_routine(name: str) -> dict:
    if not NAME_RE.match(name):
        raise RoutineError(f"Nome de rotina inválido: '{name}'")
    path = ROUTINES_DIR / f"{name}.yaml"
    if not path.is_file():
        available = ", ".join(r["name"] for r in list_routines()) or "nenhuma"
        raise RoutineError(f"Rotina '{name}' não existe. Disponíveis: {available}.")
    try:
        return _load(path)
    except yaml.YAMLError as e:
        raise RoutineError(f"{path.name}: YAML inválido ({e})")


def fill(value, vars: dict):
    # Substituição própria em vez de str.format: format aceita {x.__class__} e {x[0]},
    # e o texto vem do YAML e dos parâmetros que o modelo mandou.
    if isinstance(value, str):
        def sub(m):
            if m.group(1) not in vars:
                raise RoutineError(f"Variável '{{{m.group(1)}}}' não definida")
            return str(vars[m.group(1)])
        return VAR_RE.sub(sub, value)
    if isinstance(value, list):
        return [fill(v, vars) for v in value]
    if isinstance(value, dict):
        return {k: fill(v, vars) for k, v in value.items()}
    return value


def check_when(cond: dict | None, vars: dict) -> bool:
    if not cond:
        return True
    text = str(vars.get(cond.get("var"), ""))
    value = text
    if "matches" in cond:
        m = re.search(cond["matches"], text, re.MULTILINE)
        if not m:
            return False
        value = m.group(1) if m.groups() else m.group(0)
    if "not_matches" in cond and re.search(cond["not_matches"], text, re.MULTILINE):
        return False
    try:
        if "gte" in cond and not float(value) >= cond["gte"]:
            return False
        if "lt" in cond and not float(value) < cond["lt"]:
            return False
    except ValueError:
        return False
    return True


def _matching_files(spec: dict, vars: dict) -> list[str]:
    directory = fill(spec.get("dir", "."), vars)
    allowed, p = check_path(directory)
    if not allowed:
        raise RoutineError(p)
    if not p.is_dir():
        raise RoutineError(f"'{directory}' não é um diretório existente")
    patterns = [pat.lower() for pat in spec.get("patterns", ["*"])]
    # Só o primeiro nível e só arquivos; ordenado para o plano sair igual a cada vez.
    names = sorted(f.name for f in p.iterdir() if f.is_file())
    return [f"{directory.rstrip('/')}/{n}" for n in names if any(fnmatch.fnmatch(n.lower(), pat) for pat in patterns)]


def compile_steps(steps: list, vars: dict) -> list[dict]:
    """Achata a rotina numa lista de operações concretas: for_each vira um passo por arquivo.

    Os arquivos são expandidos aqui, uma vez: a lista que o humano aprova é a que roda.
    Os args já saem preenchidos; say e when ficam para a execução (dependem de saídas guardadas).
    """
    ops = []
    for step in steps:
        kinds = [k for k in STEP_KINDS if k in step]
        if len(kinds) != 1:
            raise RoutineError(f"Cada passo precisa de exatamente uma chave entre {STEP_KINDS}: {step}")
        kind = kinds[0]
        if kind == "for_each":
            files = _matching_files(step["for_each"], vars)
            if files:
                ops += compile_steps(step.get("before", []), vars)
            for f in files:
                ops += compile_steps(step.get("steps", []), {**vars, step.get("as", "item"): f})
        elif kind == "tool":
            ops.append({"tool": step["tool"], "args": fill(step.get("args", {}), vars),
                        "save": step.get("save"), "when": step.get("when")})
        else:
            ops.append({kind: step[kind], "when": step.get("when")})
    return ops


def resolve_params(routine: dict, given: dict) -> dict:
    declared = routine.get("params") or {}
    unknown = set(given) - set(declared)
    if unknown:
        raise RoutineError(f"Parâmetros desconhecidos: {', '.join(sorted(unknown))}. Aceitos: {', '.join(declared) or 'nenhum'}.")
    vars = {}
    for name, spec in declared.items():
        if name in given:
            vars[name] = str(given[name])
        elif isinstance(spec, dict) and "default" in spec:
            vars[name] = str(spec["default"])
        else:
            raise RoutineError(f"Falta o parâmetro '{name}': {(spec or {}).get('description', '')}")
    return vars


def describe(op: dict) -> str:
    args = ", ".join(str(v) for v in op["args"].values())
    return f"{op['tool']}({args})"


def _failed(first_line: str) -> bool:
    # Pela 1ª linha: a saída de um cat pode conter "Erro" no meio sem o passo ter falhado.
    return first_line.startswith(("Erro", "🛑", "Exit code", "Path ")) or "não existe" in first_line


async def run(name: str, params: dict, call, confirm) -> str:
    """Executa a rotina. call(tool, args) -> str roda uma ferramenta; confirm(texto) -> (ok, motivo)."""
    try:
        routine = load_routine(name)
        vars = resolve_params(routine, params or {})
        ops = compile_steps(routine["steps"], vars)
    except RoutineError as e:
        return f"Erro na rotina: {e}"

    # A cerca recusa antes da pergunta, como nas ferramentas: não se aprova comando que não vai rodar.
    for op in ops:
        if op.get("tool") == "run_command":
            allowed, msg = check_command(op["args"].get("command", ""))
            if not allowed:
                return f"Erro na rotina: {msg}"
        elif op.get("tool") in NEEDS_APPROVAL:
            # Os args das ferramentas que escrevem são todos caminhos (origem, destino, pasta).
            for value in op["args"].values():
                allowed, msg = check_path(str(value), write=True)
                if not allowed:
                    return f"Erro na rotina: {msg}"

    actions = [describe(op) for op in ops if op.get("tool") in NEEDS_APPROVAL]
    if actions:
        shown = actions[:20] + ([f"... e mais {len(actions) - 20}"] if len(actions) > 20 else [])
        text = f"Rotina '{name}': até {len(actions)} ação(ões) que escrevem ou executam comandos:\n  " + "\n  ".join(shown)
        ok, reason = await confirm(text)
        if not ok:
            return f"🛑 Rotina '{name}' não executada. {reason}"

    log, said, skipped, failures = [], [], 0, 0
    for op in ops:
        if not check_when(op.get("when"), vars):
            skipped += 1
            continue
        if op.get("stop"):
            break
        if "say" in op:
            said.append(fill(op["say"], vars))
            continue
        result = await call(op["tool"], op["args"])
        if op.get("save"):
            vars[op["save"]] = result
        first_line = result.strip().splitlines()[0] if result.strip() else "(sem saída)"
        failures += _failed(first_line)
        log.append(f"{'✗' if _failed(first_line) else '✓'} {describe(op)}: {first_line}")

    report = [f"Rotina '{name}' concluída: {len(log)} passo(s) executado(s), {failures} com erro, {skipped} pulado(s) por condição."]
    if log:
        report += ["Passos:"] + log
    if said:
        report += ["Conclusões:"] + [f"- {s}" for s in said]
    return "\n".join(report)
