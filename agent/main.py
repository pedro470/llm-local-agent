from pathlib import Path
from tools import AVAILABLE_TOOLS, TOOLS_SCHEMA
from ollama_client import get_available_models, send_chat
from guard import describe_roots
import inspect

def select_model() -> tuple[bool, str]:
  status, models = get_available_models()
  if not status:
    return (False, models)
  print("Modelos disponíveis:")
  for idx, model in enumerate(models):
    print(f"{idx}: {model}")
  while True:
    choice = input("Escolha um modelo: ").strip()
    if choice.isdigit() and int(choice) < len(models):
      return (True, models[int(choice)])
    print(f"Opção inválida. Digite um número de 0 a {len(models) - 1}.")


def chat_turn(messages: list, model: str, max_turns: int = 10) -> str:
  for turn in range(max_turns):
    status, message = send_chat(model, messages, tools=TOOLS_SCHEMA)
    if not status:
      return message

    messages.append(message)
    if message.get("tool_calls"):
      for tool_call in message["tool_calls"]:
        fn_name = tool_call["function"]["name"]
        fn_args = tool_call["function"]["arguments"]

        print(f"  ⚙️ [Agente executando]: {fn_name}({fn_args})")

        if fn_name in AVAILABLE_TOOLS:

          try:
            result = AVAILABLE_TOOLS[fn_name](**fn_args)
          except TypeError:
            sig = inspect.signature(AVAILABLE_TOOLS[fn_name])
            result = f"Erro: os argumentos fornecidos para a ferramenta '{fn_name}' são inválidos. Parametro esperados: {sig}. Parametros enviados: {fn_args}"
        else:
          result = f"Erro: ferramenta '{fn_name}' não existe."

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


if __name__ == "__main__":
  current_dir = Path.cwd()

  # AQUI: O histórico começa fora do while e persiste!
  conversation_history = [{
      "role": "system",
      "content": (
          "Você é um assistente pessoal inteligente rodando localmente na máquina do usuário.\n"
          f"DIRETÓRIO DE TRABALHO ATUAL: {current_dir}. Você está dentro de uma máquina virtual WSL2, na distribuição Ubuntu 24.04. O /mnt/c é o volume c: do Windows e df / indica espaço virtual. Para espaço livre real, use df -h /mnt/c\n"
          "DIRETRIZES DE COMPORTAMENTO:\n"
          "1. Para saudações, conversas casuais ou perguntas teóricas, responda diretamente em texto em português SEM chamar ferramentas.\n"
          "2. Se o usuário perguntar quais ferramentas você tem, apenas liste os nomes e descrições delas em texto puro.\n"
          "3. Quando o usuário solicitar explicitamente alguma inspeção ou ação real no sistema operacional, aja em etapas usando as ferramentas disponíveis para chegar ao resultado final.\n"
          "4. Quando o resultado final for ambíguo ou necessitar de ferramentas destrutivas, comunique ao usuário o que você entendeu e aguarde a confirmação.\n"
          "5. Ao receber o retorno de uma ferramenta, SEMPRE apresente e resuma os dados obtidos na sua resposta final ao usuário.\n"
          "6. Ao referenciar pastas locais, prefira sempre caminhos relativos ao diretório de trabalho atual (ex: '.', 'agent').\n"
          f"7. LIMITES DAS FERRAMENTAS: {describe_roots()} Se uma ferramenta recusar um caminho ou comando, explique o limite ao usuário em vez de tentar contornar."
      ),
  }]

  print(
      "🤖 Agente Local pronto (com memória ativa)! Digite sua instrução ou"
      " 'sair'.\n"
  )


  ok, model = select_model()
  if not ok:
    print(f"Erro: {model}")
    exit(1)
  
  while True:
    prompt = input("Você: ")
    if prompt.lower() in ["sair", "exit", "quit"]:
      break
    if not prompt.strip():
      continue

    # Anexa a mensagem do usuário no histórico persistente
    conversation_history.append({"role": "user", "content": prompt})

    resposta = chat_turn(conversation_history, model)
    print(f"\nAgente:\n{resposta}\n")