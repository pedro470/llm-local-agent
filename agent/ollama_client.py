import requests


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

def send_chat(model: str, messages: list, tools: list | None = None, base_url: str = "http://localhost:11434", timeout: tuple[float, float] = (5, 300)) -> tuple[bool, dict | str]:
    # timeout = (conectar, ler): 5 s para abrir a conexão TCP; 300 s para a resposta,
    # que inclui carregar o modelo na VRAM na primeira chamada.
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
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
        return (True, response.json().get('message'))
    except requests.exceptions.JSONDecodeError:
        return (False, response.text)

    

if __name__ == "__main__":
    print(get_available_models())
    print(send_chat("qwen3.5:9b", [{"role": "user", "content": "Olá!"}]))