"""
Agente local: laço de conversa com o Ollama + ferramentas servidas pelo mcp_server.py.

Arquitetura (cliente MCP por stdio):
  main.py ──fork/exec──> python mcp_server.py   (o SDK usa start_new_session: o filho não tem terminal)
     │  stdin/stdout do filho = canal JSON-RPC 2.0 (initialize, tools/list, tools/call)
     │  stderr do filho       = logs do servidor, direto no terminal
     └─ elicitation/create    = o servidor pede a confirmação (s/n) pelo mesmo canal;
                                ask_human() pergunta a você aqui, no terminal do main
As ferramentas rodam no processo do servidor; este arquivo só traduz entre o formato
do Ollama (tool_calls) e o do MCP (call_tool) e faz a ponte da confirmação humana.
"""

import asyncio
import json
import re
import sys
from pathlib import Path

from ollama_client import NUM_CTX, OFFICIAL_MODEL, get_available_models, loaded_models, send_chat, unload, warm_up
from system_prompt import build_system_prompt

# Tokens reservados para a resposta do modelo (texto + tool_calls) dentro da janela NUM_CTX.
RESPONSE_RESERVE = 4096
# Nota que a janela acrescenta ao prompt de sistema depois de cortar o histórico.
# A frase sobre o "primeiro pedido" é o que faz efeito: sem ela o gemma4 ignorou a nota em 4 de 5 rodadas.
TRIM_NOTE = ("\n\nMemória curta: os {} pedidos mais antigos desta conversa saíram do histórico por falta "
             "de espaço. O primeiro pedido que você ainda vê NÃO é o primeiro da conversa. Se o usuário "
             "perguntar sobre algo anterior, diga que esse trecho saiu da sua memória.")
TRIM_NOTE_RE = r"\n\nMemória curta: os (\d+) pedidos"

# O SDK do MCP (pydantic, starlette, uvicorn, cryptography...) leva ~0,8 s para importar no
# disco Linux e ~4 s em /mnt/c. Por isso ele é importado dentro das funções que o usam:
# a checagem do Ollama e a lista de modelos aparecem antes desse custo.

SERVER_SCRIPT = Path(__file__).resolve().parent / "mcp_server.py"


def select_model() -> tuple[bool, str]:
  status, models = get_available_models()
  if not status:
    return (False, models)
  official = next((m for m in models if m.split(":latest")[0] == OFFICIAL_MODEL), None)
  print("Modelos disponíveis:")
  for idx, model in enumerate(models):
    print(f"{idx}: {model}{'  (oficial)' if model == official else ''}")
  while True:
    hint = f" [Enter = {official}]" if official else ""
    choice = input(f"Escolha um modelo{hint}: ").strip()
    if not choice and official:
      return (True, official)
    if choice.isdigit() and int(choice) < len(models):
      return (True, models[int(choice)])
    print(f"Opção inválida. Digite um número de 0 a {len(models) - 1}.")


def mcp_tool_to_ollama(tool) -> dict:
  # tools/list do MCP -> formato "function" que o /api/chat do Ollama espera.
  # O input_schema já é JSON Schema, gerado pelo servidor a partir das anotações de tipo.
  return {
      "type": "function",
      "function": {
          "name": tool.name,
          "description": tool.description or "",
          "parameters": tool.input_schema,
      },
  }


def tool_result_text(result) -> str:
  text = "\n".join(c.text for c in result.content if getattr(c, "text", None) is not None)
  if getattr(result, "is_error", False):
    return f"Erro: {text}"
  return text


async def ask_human(context, params):
  # Esta função É o humano no circuito: nunca repassar a pergunta ao modelo.
  # Só "s" autoriza; qualquer outra resposta vira "decline" e o servidor bloqueia.
  import mcp_types
  print(f"\n⚠️  {params.message}")
  resposta = await asyncio.to_thread(input, "👉 Digite 's' para autorizar ou qualquer outra tecla para bloquear: ")
  if resposta.strip().lower() == "s":
    return mcp_types.ElicitResult(action="accept", content={"autorizar": True})
  return mcp_types.ElicitResult(action="decline")


def server_params(cwd: Path):
  from mcp import StdioServerParameters
  # sys.executable = o Python do .venv que está rodando o main: o servidor herda o mesmo ambiente.
  # cwd igual ao do main: caminhos relativos do modelo resolvem no mesmo lugar dos dois lados.
  return StdioServerParameters(command=sys.executable, args=[str(SERVER_SCRIPT)], cwd=str(cwd))


def estimate_tokens(obj) -> int:
  # ~3,6 caracteres por token em português (medido: prompt de sistema de 2.928 caracteres = 806 tokens).
  # Dividir por 3 erra para o lado seguro: a janela corta um pouco antes do necessário.
  return len(json.dumps(obj, ensure_ascii=False)) // 3


def trim_history(messages: list, tools_schema: list, num_ctx: int = NUM_CTX) -> int:
  # Se o prompt passa do num_ctx, o Ollama descarta mensagens antigas sem avisar (medido:
  # 2.298 tokens viraram 1.903 com num_ctx=2048, sem erro). Aqui o corte é nosso e visível.
  # Corta rodadas inteiras, do pedido do usuário até antes do próximo: uma resposta de ferramenta
  # sem o tool_call que a pediu confunde o modelo. O system (índice 0) e a rodada atual ficam sempre.
  budget = num_ctx - RESPONSE_RESERVE - estimate_tokens(tools_schema)
  user_idx = [i for i, m in enumerate(messages) if i > 0 and m["role"] == "user"]
  removed = 0
  while len(user_idx) > 1 and estimate_tokens(messages) > budget:
    cut = user_idx[1]
    del messages[1:cut]
    user_idx = [i - (cut - 1) for i in user_idx[1:]]
    removed += 1
  if removed:
    # Sem a nota, o modelo responde sobre o que sobrou como se fosse a conversa inteira
    # (no teste, disse com certeza que o 1º arquivo lido era o 3º).
    system = messages[0]["content"]
    match = re.search(TRIM_NOTE_RE, system)
    total = removed + (int(match.group(1)) if match else 0)
    base = system[:match.start()] if match else system
    messages[0] = {**messages[0], "content": base + TRIM_NOTE.format(total)}
  return removed


async def chat_turn(messages: list, model: str, tools_schema: list, call_tool, max_turns: int = 10, stats: dict | None = None) -> str:
  for turn in range(max_turns):
    # A janela é conferida antes de cada chamada: dentro de um pedido, as respostas das
    # ferramentas também fazem o histórico crescer.
    removed = trim_history(messages, tools_schema)
    if removed:
      print(f"  🧹 [Janela]: {removed} rodada(s) antiga(s) saíram do histórico para caber em {NUM_CTX} tokens")
    # send_chat é bloqueante (requests); roda numa thread para não travar o laço de eventos
    # que lê o pipe do servidor MCP.
    status, reply = await asyncio.to_thread(send_chat, model, messages, tools_schema)
    if not status:
      return reply
    if stats is not None:
      stats["prompt_tokens"] = reply["prompt_tokens"]
      stats["output_tokens"] = reply["output_tokens"]

    message = reply["message"]
    # O template do gemma4 não reenvia o raciocínio das respostas antigas (medido: o prompt tem o mesmo
    # tamanho com ou sem ele). Guardá-lo só faria a estimativa da janela contar texto que o modelo não vê.
    message.pop("thinking", None)
    messages.append(message)
    if message.get("tool_calls"):
      for tool_call in message["tool_calls"]:
        fn_name = tool_call["function"]["name"]
        fn_args = tool_call["function"]["arguments"]
        if isinstance(fn_args, str):
          try:
            fn_args = json.loads(fn_args)
          except json.JSONDecodeError:
            fn_args = {}

        print(f"  ⚙️ [Agente executando]: {fn_name}({fn_args})")
        result = await call_tool(fn_name, fn_args)
        print(f"  📥 [Retorno da Tool]: {result}\n")

        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.get("id"),
            "name": fn_name,
            "content": str(result),
        })
    else:
      return message["content"]

  return "⚠️ Limite máximo de iterações atingido."


async def run_agent(model: str) -> None:
  from mcp import ClientSession
  from mcp.client.stdio import stdio_client

  current_dir = Path.cwd()
  # O container já troca sozinho (OLLAMA_MAX_LOADED_MODELS=1), mas descarregar aqui deixa a troca
  # explícita e libera a VRAM antes de o novo modelo começar a carregar.
  ok, loaded = loaded_models()
  if ok:
    for m in loaded:
      if m["name"] != model:
        print(f"⏏️  {unload(m['name'])[1]}")
  # Aquecimento: pede ao Ollama para carregar o modelo na VRAM enquanto o servidor MCP sobe.
  # As duas esperas correm em paralelo, e a primeira mensagem não paga o carregamento.
  warming = asyncio.create_task(asyncio.to_thread(warm_up, model))
  async with stdio_client(server_params(current_dir)) as (read, write):
    # elicitation_callback anuncia ao servidor, no initialize, que este cliente sabe pedir confirmação.
    async with ClientSession(read, write, elicitation_callback=ask_human) as session:
      await session.initialize()
      listed = await session.list_tools()
      ok, msg = await warming
      print(f"🔥 {msg}")
      ok, loaded = loaded_models()
      for m in loaded if ok else []:
        print(f"🧠 VRAM: {m['name']} ocupa {m['size_vram'] / 2**30:.1f} GiB, contexto de {m['context_length']} tokens")
      tools_schema = [mcp_tool_to_ollama(t) for t in listed.tools]
      names = {t.name for t in listed.tools}

      async def call_tool(name: str, args: dict) -> str:
        if name not in names:
          return f"Erro: ferramenta '{name}' não existe. Disponíveis: {', '.join(sorted(names))}."
        try:
          result = await session.call_tool(name, arguments=args)
        except Exception as e:
          # Ex.: argumento com nome errado; o servidor valida pelo schema e recusa.
          return f"Erro ao chamar '{name}' com {args}: {e}"
        return tool_result_text(result)

      # O histórico começa fora do while e persiste entre pedidos.
      conversation_history = [{"role": "system", "content": build_system_prompt(str(current_dir))}]
      print(f"🔌 Servidor MCP conectado ({len(names)} ferramentas: {', '.join(sorted(names))}).")
      print("🤖 Agente Local pronto (com memória ativa)! Digite sua instrução ou 'sair'.\n")

      while True:
        prompt = await asyncio.to_thread(input, "Você: ")
        if prompt.lower() in ["sair", "exit", "quit"]:
          break
        if not prompt.strip():
          continue

        conversation_history.append({"role": "user", "content": prompt})
        stats = {}
        resposta = await chat_turn(conversation_history, model, tools_schema, call_tool, stats=stats)
        print(f"\nAgente:\n{resposta}\n")
        if stats:
          used = stats["prompt_tokens"] + stats["output_tokens"]
          print(f"📊 contexto: {used} de {NUM_CTX} tokens ({used / NUM_CTX:.0%})\n")


if __name__ == "__main__":
  ok, model = select_model()
  if not ok:
    print(f"Erro: {model}")
    exit(1)
  try:
    asyncio.run(run_agent(model))
  except (KeyboardInterrupt, EOFError):
    print("\nAté mais.")
