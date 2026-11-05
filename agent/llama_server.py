"""
Cliente do llama-server (llama.cpp nativo no Windows), que substitui o Ollama no Docker/WSL.

O agente sobe o llama-server como processo filho, com o GGUF escolhido, e o encerra ao sair:
um servidor = um modelo, e a VRAM volta ao sistema quando o agente termina.

  main.py ──CreateProcess──> llama-server.exe -m <gguf> -c NUM_CTX -ngl 99 ...
     │  HTTP 127.0.0.1:8080  (API compatível com OpenAI: /v1/chat/completions, /health, /props)
     └─ Job Object com KILL_ON_JOB_CLOSE: se o Python morrer de qualquer jeito (Ctrl+C, janela
        fechada, crash), o kernel do Windows fecha o handle do job e mata o servidor junto.
        Sem isso, um llama-server órfão seguraria ~7,8 GB de VRAM e a porta 8080.

Pastas (LLM_HOME, padrão C:\\Users\\<você>\\llm):
  llama.cpp\\rocm\\llama-server.exe     build ROCm (HIP), precisa do HIP SDK no PATH
  llama.cpp\\vulkan\\llama-server.exe   build Vulkan, só precisa do driver Adrenalin
  models\\<nome>.gguf                    um arquivo por modelo; <nome> é o que o menu mostra
"""

import os
import subprocess
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LLM_HOME = Path(os.environ.get("LLM_HOME", Path.home() / "llm"))
MODELS_DIR = LLM_HOME / "models"
LOG_FILE = PROJECT_ROOT / "logs" / "llama-server.log"

# Modelo oficial do projeto (decisão de 27/10/2026, pela bateria evals/prompt_traps.py: 18/18).
OFFICIAL_MODEL = "gemma4-12b"

# Backend do llama.cpp: "vulkan" (oficial, decidido em 05/11/2026) ou "rocm". Trocar com AGENT_BACKEND.
# Na bateria do agente o Vulkan fez 27/27 em 210 s de média contra 233 s do ROCm: o gemma4 pensa
# 100 a 300 tokens por chamada e a geração domina. O ROCm só ganha quando o cache do prefixo se perde.
BACKEND = os.environ.get("AGENT_BACKEND", "vulkan")
# O build ROCm carrega amdhip64/hipblas do HIP SDK; o instalador não põe a pasta no PATH.
HIP_BIN = Path(os.environ.get("HIP_PATH", r"C:\Program Files\AMD\ROCm\7.2")) / "bin"

# Janela de contexto, em tokens. Só o prompt de sistema mais o schema das ferramentas ocupam ~1.650.
# No gemma4 o KV cache custa ~8,5 KiB/token (só 8 das 48 camadas têm atenção global; as outras 40
# usam janela deslizante de 1024 e um cache fixo). 32768 tokens = ~272 MiB de KV.
# Trocar com AGENT_NUM_CTX; o valor vale para o servidor inteiro (o KV é alocado na subida).
NUM_CTX = int(os.environ.get("AGENT_NUM_CTX", "32768"))

HOST = "127.0.0.1"  # só o loopback: nada fora desta máquina fala com o modelo
PORT = int(os.environ.get("AGENT_PORT", "8080"))
BASE_URL = f"http://{HOST}:{PORT}"


def available_models() -> tuple[bool, list[str] | str]:
    """Nomes dos GGUF em MODELS_DIR (sem a extensão). mmproj-* são projetores de visão, não modelos."""
    if not MODELS_DIR.is_dir():
        return (False, f"Pasta de modelos não existe: {MODELS_DIR}")
    models = sorted(p.stem for p in MODELS_DIR.glob("*.gguf") if not p.name.startswith("mmproj"))
    if not models:
        return (False, f"Nenhum .gguf em {MODELS_DIR}")
    return (True, models)


def _server_command(model: str) -> tuple[list[str], dict]:
    exe = LLM_HOME / "llama.cpp" / BACKEND / "llama-server.exe"
    if not exe.is_file():
        raise FileNotFoundError(f"llama-server não encontrado em {exe} (AGENT_BACKEND={BACKEND})")
    argv = [
        str(exe),
        "-m", str(MODELS_DIR / f"{model}.gguf"),
        "-c", str(NUM_CTX),
        "-np", "1",          # um slot só: a janela inteira é desta conversa (com 4 slots, cada um teria 1/4)
        "-ngl", "99",        # todas as camadas na GPU
        "-fa", "on",         # flash attention: o KV não vira uma matriz NxN na VRAM
        "--jinja",           # usa o template de chat do próprio GGUF (é ele que sabe formatar tool calls)
        "--host", HOST, "--port", str(PORT),
        "--no-webui",
        "--offline",         # nunca baixa nada: tudo o que o servidor usa já está no disco
    ]
    env = dict(os.environ)
    if BACKEND == "rocm":
        env["PATH"] = f"{HIP_BIN};{env.get('PATH', '')}"
    else:
        # A camada implícita do Twitch Studio derruba o vkCreateDevice com ErrorDeviceLost.
        env["VK_LOADER_LAYERS_DISABLE"] = "VK_LAYER_Twitch_Overlay"
    return argv, env


def _kill_on_close_job():
    """Job Object que mata os membros quando o último handle fecha (o do processo Python)."""
    import win32job
    job = win32job.CreateJobObject(None, "")
    info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
    return job


class LlamaServer:
    def __init__(self, model: str):
        self.model = model
        self.proc: subprocess.Popen | None = None
        self._job = None
        self._log = None

    def start(self) -> None:
        # Porta já respondendo = outro servidor (provavelmente órfão de uma versão sem Job Object).
        try:
            requests.get(f"{BASE_URL}/health", timeout=1)
            raise RuntimeError(f"A porta {PORT} já está em uso. Feche o outro llama-server "
                               "(tasklist /FI \"IMAGENAME eq llama-server.exe\") ou mude AGENT_PORT.")
        except requests.ConnectionError:
            pass
        argv, env = _server_command(self.model)
        LOG_FILE.parent.mkdir(exist_ok=True)
        self._log = open(LOG_FILE, "w", encoding="utf-8", errors="replace")
        # CREATE_NEW_PROCESS_GROUP: o Ctrl+C do terminal vai só para o Python, que encerra o servidor
        # na ordem certa (stop). CREATE_NO_WINDOW: sem console próprio; a saída vai para o log.
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        self.proc = subprocess.Popen(argv, env=env, stdout=self._log, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, creationflags=flags)
        try:
            import win32api, win32con
            self._job = _kill_on_close_job()
            handle = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, self.proc.pid)
            import win32job
            win32job.AssignProcessToJobObject(self._job, handle)
            win32api.CloseHandle(handle)
        except Exception:
            self._job = None  # sem job, o stop() do finally ainda encerra o servidor no caminho normal

    def wait_ready(self, timeout: float = 120) -> tuple[bool, str]:
        # /health devolve 503 enquanto carrega os tensores na VRAM e 200 quando aceita pedidos.
        start = time.perf_counter()
        while time.perf_counter() - start < timeout:
            if self.proc.poll() is not None:
                return (False, f"llama-server saiu com código {self.proc.returncode}. Fim do log:\n{self.log_tail()}")
            try:
                if requests.get(f"{BASE_URL}/health", timeout=2).status_code == 200:
                    return (True, f"{self.model} carregado na VRAM ({BACKEND}) em {time.perf_counter() - start:.1f} s")
            except requests.RequestException:
                pass
            time.sleep(0.25)
        return (False, f"llama-server não ficou pronto em {timeout:.0f} s. Fim do log:\n{self.log_tail()}")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()  # TerminateProcess: a VRAM é liberada quando o driver fecha o contexto
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        if self._log:
            self._log.close()
        self._job = None  # fecha o handle do job; com o processo já morto, não faz mais nada

    def log_tail(self, lines: int = 15) -> str:
        try:
            return "\n".join(LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
        except OSError:
            return "(sem log)"

    def vram_report(self) -> str:
        # O WDDM (o gerenciador de memória de vídeo do Windows) conta a VRAM dedicada por processo e
        # expõe no contador "GPU Process Memory", o mesmo que o Gerenciador de Tarefas mostra.
        # Medido em 05/11/2026 com o gemma4 e 32768 tokens: 8,26 GiB (pesos 6,86 + KV 0,97 + compute
        # 0,15 + driver). A tabela de embeddings (787 MiB) fica na RAM, mapeada do arquivo.
        try:
            import win32pdh
            paths = win32pdh.ExpandCounterPath(rf"\GPU Process Memory(pid_{self.proc.pid}_*)\Dedicated Usage")
            query = win32pdh.OpenQuery()
            counters = [win32pdh.AddCounter(query, p) for p in paths]
            win32pdh.CollectQueryData(query)
            used = sum(win32pdh.GetFormattedCounterValue(c, win32pdh.PDH_FMT_LARGE)[1] for c in counters)
            win32pdh.CloseQuery(query)
        except Exception as e:
            return f"VRAM: não consegui ler o contador do Windows ({e})"
        return f"VRAM: {self.model} ocupa {used / 2**30:.1f} GiB, contexto de {NUM_CTX} tokens"


def send_chat(messages: list, tools: list | None = None, timeout: tuple[float, float] = (5, 300)) -> tuple[bool, dict | str]:
    # timeout = (conectar, ler). Devolve {"message", "prompt_tokens", "output_tokens"}.
    # prompt_tokens é o prompt inteiro (system + schema + histórico), mesmo quando o prefixo veio do
    # cache do slot: serve de medidor da janela.
    payload = {
        "messages": messages,
        "stream": False,
        # O template do gemma4 só abre o canal de pensamento com enable_thinking. O servidor separa o
        # pensamento em message.reasoning_content, e o template o reenvia nas chamadas da rodada atual.
        "chat_template_kwargs": {"enable_thinking": True},
    }
    if tools:
        payload["tools"] = tools
    try:
        response = requests.post(f"{BASE_URL}/v1/chat/completions", json=payload, timeout=timeout)
    except requests.exceptions.Timeout:
        return (False, f"llama-server não respondeu dentro do limite de {timeout[1]:.0f} s")
    except requests.exceptions.ConnectionError:
        return (False, f"llama-server não está acessível em {BASE_URL}")

    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError:
        return (False, f"llama-server respondeu {response.status_code}: {response.text[:300]}")
    if response.status_code != 200:
        return (False, f"llama-server respondeu {response.status_code}: {data.get('error', {}).get('message', data)}")
    # Campos nulos fora: o histórico volta inteiro ao servidor em toda chamada.
    message = {k: v for k, v in data["choices"][0]["message"].items() if v not in (None, "", [])}
    message.setdefault("content", "")
    usage = data.get("usage", {})
    return (True, {
        "message": message,
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
    })


if __name__ == "__main__":
    ok, models = available_models()
    print(models)
    server = LlamaServer(OFFICIAL_MODEL)
    server.start()
    try:
        print(server.wait_ready())
        print(server.vram_report())
        print(send_chat([{"role": "user", "content": "Olá!"}]))
    finally:
        server.stop()
