from ollama_client import get_available_models

def test_connection():
    sucess, models = get_available_models()
    if not sucess:
        print(f"Erro: {models}")
        return False
    elif not models:
        print("Nenhum modelo encontrado!")
        return False
    else:
        print("Ollama está rodando e com modelos disponíveis!")
        print("Modelos disponíveis:")
        for model in models:
            print(f"- {model}")
        return True

if __name__ == "__main__":
    test_connection()
