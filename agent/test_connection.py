"""
Checagem manual da camada do modelo: lista os GGUF, sobe o llama-server com o oficial,
manda um "Olá" e encerra. Uso: .venv\\Scripts\\python agent\\test_connection.py
"""

import sys

from llama_server import BACKEND, LLM_HOME, OFFICIAL_MODEL, LlamaServer, available_models, send_chat


def test_connection() -> bool:
    ok, models = available_models()
    if not ok:
        print(f"Erro: {models}")
        return False
    print(f"Modelos em {LLM_HOME / 'models'}: {', '.join(models)}")
    if OFFICIAL_MODEL not in models:
        print(f"Erro: o modelo oficial {OFFICIAL_MODEL}.gguf não está lá.")
        return False

    server = LlamaServer(OFFICIAL_MODEL)
    try:
        server.start()
        ok, msg = server.wait_ready()
        print(msg)
        if not ok:
            return False
        print(server.vram_report())
        ok, reply = send_chat([{"role": "user", "content": "Responda só: ok"}])
        print(f"Resposta ({BACKEND}): {reply['message']['content'] if ok else reply}")
        return ok
    finally:
        server.stop()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(0 if test_connection() else 1)
