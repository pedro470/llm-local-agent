import os
import time

import requests

# Modelo oficial do projeto (decisão de 27/10/2026, pela bateria evals/prompt_traps.py: 18/18).
OFFICIAL_MODEL = "gemma4:12b"

# Janela de contexto pedida ao Ollama, em tokens. Sem isso ele usa 4096, e só o prompt de sistema
# mais o schema das 7 ferramentas já ocupam ~1.650. No gemma4 o KV cache custa ~8,5 KiB/token
# (só 8 das 48 camadas têm atenção global; as outras 40 usam janela deslizante de 1024 e um cache
# fixo de ~255 MiB). 32768 tokens = ~272 MiB de KV: o modelo inteiro fica em ~7,8 GB dos 16 GB.
# Trocar com AGENT_NUM_CTX. Mudar o valor obriga o Ollama a recarregar o modelo (~10 s).
NUM_CTX = int(os.environ.get("AGENT_NUM_CTX", "32768"))


def get_available_models(base_url: str = "http://localhost:11434", require_tools: bool = True) -> tuple[bool, list[str] | str]:
    try:
        response = requests.get(f"{base_url}/api/tags", timeout=5)
    except requests.RequestException:
        return (False, "Ollama não está acessível na porta 11434")
    
    if response.status_code != 200:
        return (False, f"Ollama respondeu com status {response.status_code}")

    data = response.json().get("models", [])
    if require_tools:
        models = [m["name"] for m in data if "tools" in m.get("capabilities", [])]
    else:
        models = [m["name"] for m in data]
        
    if not models:
        return (False, "Nenhum modelo compatível encontrado")

    return (True, models)


def loaded_models(base_url: str = "http://localhost:11434") -> tuple[bool, list[dict] | str]:
    # GET /api/ps: o que está na VRAM agora, com size_vram (bytes) e context_length (num_ctx em uso).
    try:
        response = requests.get(f"{base_url}/api/ps", timeout=5)
    except requests.RequestException:
        return (False, "Ollama não está acessível na porta 11434")
    if response.status_code != 200:
        return (False, f"Ollama respondeu com status {response.status_code}")
    return (True, response.json().get("models", []))


def unload(model: str, base_url: str = "http://localhost:11434") -> tuple[bool, str]:
    # keep_alive=0 manda o Ollama liberar a VRAM do modelo assim que esta chamada termina.
    try:
        response = requests.post(f"{base_url}/api/generate", json={"model": model, "keep_alive": 0}, timeout=30)
    except requests.RequestException as e:
        return (False, f"Não foi possível descarregar {model}: {e}")
    if response.status_code != 200:
        return (False, f"Ollama respondeu {response.status_code} ao descarregar {model}")
    return (True, f"{model} descarregado da VRAM")


def warm_up(model: str, base_url: str = "http://localhost:11434", timeout: tuple[float, float] = (5, 300)) -> tuple[bool, str]:
    # /api/generate sem prompt só carrega o modelo na VRAM e responde quando ele está pronto.
    # Com OLLAMA_MAX_LOADED_MODELS=1, o Ollama descarrega o modelo anterior antes: nunca há dois na GPU.
    # O num_ctx tem de ser o mesmo do send_chat: o KV cache é alocado no carregamento, e um num_ctx
    # diferente na primeira mensagem faria o Ollama recarregar o modelo inteiro.
    start = time.perf_counter()
    try:
        response = requests.post(f"{base_url}/api/generate", json={"model": model, "options": {"num_ctx": NUM_CTX}}, timeout=timeout)
    except requests.exceptions.RequestException as e:
        return (False, f"Não foi possível carregar {model} na VRAM: {e}")
    if response.status_code != 200:
        return (False, f"Ollama respondeu {response.status_code} ao carregar {model}")
    return (True, f"{model} carregado na VRAM em {time.perf_counter() - start:.1f} s")


def send_chat(model: str, messages: list, tools: list | None = None, base_url: str = "http://localhost:11434", timeout: tuple[float, float] = (5, 300)) -> tuple[bool, dict | str]:
    # timeout = (conectar, ler): 5 s para abrir a conexão TCP; 300 s para a resposta,
    # que inclui carregar o modelo na VRAM na primeira chamada.
    # Devolve {"message", "prompt_tokens", "output_tokens"}. prompt_tokens é o prompt inteiro
    # (system + schema + histórico), mesmo quando o prefixo veio do cache: serve de medidor da janela.
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"num_ctx": NUM_CTX},
    }
    if tools:
        payload["tools"] = tools
    try:
        response = requests.post(f"{base_url}/api/chat", json=payload, stream=False, timeout=timeout)
    except requests.exceptions.Timeout:
        return (False, f"Ollama não respondeu dentro do limite de {timeout[1]:.0f} s (modelo travado ou ainda carregando)")
    except requests.exceptions.ConnectionError:
        return (False, "Ollama não está acessível na porta 11434")
    
    if response.status_code != 200:
        try:
            return (False, response.json().get('error', ''))
        except requests.exceptions.JSONDecodeError:
            return (False, response.text)
    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError:
        return (False, response.text)
    return (True, {
        "message": data.get("message"),
        "prompt_tokens": data.get("prompt_eval_count", 0),
        "output_tokens": data.get("eval_count", 0),
    })

    

if __name__ == "__main__":
    print(get_available_models())
    print(loaded_models())
    print(send_chat(OFFICIAL_MODEL, [{"role": "user", "content": "Olá!"}]))
