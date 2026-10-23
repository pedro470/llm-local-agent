# TODO — Setup Completo do LLM Local

> ⚠️ **REGRA DE OURO**: Não pule fases. Cada fase tem um **CHECKPOINT** no final.
> Se o checkpoint não passar, você não avança. Sem exceções.

---

## FASE 0 — Fundamentos (antes de tocar em qualquer terminal)

Você não vai instalar nada nesta fase. Vai **ler e entender**.

- [x] **Ler** o que é virtualização e por que WSL2 existe
  - Pesquise: "O que é um hypervisor tipo 1 vs tipo 2?"
  - Pesquise: "Por que WSL2 usa um kernel Linux real e WSL1 não?"
  - Quando souber responder essas duas perguntas DE COR, marque como feito

- [x] **Ler** o que é Docker e containers
  - Pesquise: "Qual a diferença entre container e máquina virtual?"
  - Pesquise: "O que é uma imagem Docker vs um container Docker?"
  - Pesquise: "O que é um Dockerfile?"
  - Pesquise: "O que é docker-compose?"
  - Quando souber explicar para outra pessoa como se ela tivesse 10 anos, marque como feito

- [x] **Ler** o que é ROCm
  - ROCm é o equivalente AMD do CUDA da NVIDIA
  - Pesquise: "O que é HIP e qual a relação com CUDA?"
  - Pesquise: "O que significa `gfx1201` e por que sua GPU precisa disso?"
  - Vá na [matriz de compatibilidade ROCm 10.0.0](https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html), selecione "AMD Radeon" > "RX 9070 XT" e confirme que existe suporte

- [x] **Ler** o que é um LLM e como inferência funciona
  - Pesquise: "O que é quantização de modelos (Q4, Q8, FP16)?"
  - Pesquise: "O que é GGUF?"
  - Pesquise: "O que é function calling / tool use em LLMs?"

- [x] **Ler** o que é MCP (Model Context Protocol)
  - Pesquise: "Anthropic MCP protocol o que é"
  - Entenda: MCP é um protocolo que permite ao LLM chamar "ferramentas" no seu PC
  - Ex: o LLM decide que precisa listar arquivos → chama uma tool MCP → recebe a lista

### 🏁 CHECKPOINT FASE 0
> Responda pra si mesmo (em voz alta, de preferência):
> 1. Por que estamos usando WSL2 e não rodando Docker direto no Windows?
> 2. Qual a diferença entre uma imagem Docker e um container?
> 3. O que o ROCm faz que o driver normal da AMD não faz?
> 4. O que significa "Q4_K_M" quando se fala de um modelo?
> 5. Como o LLM vai saber que pode mover um arquivo no seu PC?
>
> Se travou em alguma, volte e releia. Sem pressa. Sem vergonha.

---

## FASE 1 — Preparar o WSL2 e Docker

- [x] **Verificar se WSL2 está configurado corretamente**
  - Abra o PowerShell como administrador
  - Execute: `wsl --status`
  - Confirme que diz "Versão padrão: 2"
  - Se não, execute: `wsl --set-default-version 2`

- [x] **Instalar uma distribuição Ubuntu no WSL2**
  - Execute: `wsl --list --online` (veja as distros disponíveis)
  - Execute: `wsl --install -d Ubuntu-24.04`
  - Crie seu usuário e senha quando solicitado
  - **ANOTE** o usuário e senha em algum lugar seguro

- [x] **Atualizar o Ubuntu dentro do WSL2**
  - Entre no WSL: `wsl -d Ubuntu-24.04`
  - Execute: `sudo apt update && sudo apt upgrade -y`
  - DESAFIO: O que o `apt` faz? O que o `-y` significa? Descubra antes de executar.

- [x] **Instalar Docker Engine no Ubuntu (WSL2)**
  - ⚠️ **NÃO** instale Docker Desktop. Você vai instalar o Docker Engine diretamente no Ubuntu.
  - Por quê? Porque Docker Desktop é uma GUI com licenciamento. Docker Engine é o motor puro. Você vai aprender o motor.
  - Siga a documentação oficial: https://docs.docker.com/engine/install/ubuntu/
  - DESAFIO: A documentação tem várias formas de instalar. Qual é a recomendada? Por quê?

- [x] **Verificar se o Docker funciona**
  - Execute: `sudo docker run hello-world`
  - Se aparecer "Hello from Docker!", funcionou
  - DESAFIO: O que aconteceu por baixo dos panos quando você executou esse comando? O Docker baixou uma imagem? De onde? O que é o Docker Hub?

- [x] **Configurar Docker para rodar sem `sudo`**
  - Pesquise: "docker post-installation steps linux"
  - Adicione seu usuário ao grupo `docker`
  - Faça logout e login no WSL
  - Teste: `docker run hello-world` (sem sudo)

### 🏁 CHECKPOINT FASE 1
- [x] `wsl --status` (Versão padrão: 2)
- [x] `docker --version` (Docker Engine 29.8.0 puro, sem Docker Desktop)
- [x] `docker run hello-world` (Executado e validado SEM sudo)

---

## FASE 2 — Entender e Configurar o acesso GPU (ROCm)

> Esta é a fase mais complexa. Vá devagar.

- [x] **Instalar drivers AMD Adrenalin atualizados no Windows**
  - Drivers Adrenalin atualizados e validados com WDDM e paravirtualização DXCore
  - Nó paravirtualizado `/dev/dxg` ativo no WSL2 com permissões `crw-rw-rw-`

- [x] **Verificar se o WSL2 enxerga a GPU**
  - No WSL2, `/dev/kfd` e `/dev/dri` não existem por padrão devido à arquitetura de paravirtualização do Hyper-V (VMBus)
  - Descoberto e validado o nó `/dev/dxg` (character device major 10, minor 125) e bibliotecas de usuário em `/usr/lib/wsl/lib/libdxcore.so`

- [x] **Instalar a biblioteca de ponte ROCDXG (`librocdxg.so`) no WSL2**
  - Pacote oficial `rocdxg-roct_1.2.2_amd64.deb` instalado via `apt install ./rocdxg-roct_1.2.2_amd64.deb`
  - Arquivos instalados em `/opt/rocm/lib/librocdxg.so`

- [x] **Testar se o ROCm funciona dentro de um container Docker**
  - Executado container `rocm/dev-ubuntu-24.04:latest` com mapeamento de `/dev/dxg`, `libdxcore.so` e `librocdxg.so`
  - Variável `HSA_ENABLE_DXG_DETECTION=1` ativada

### 🏁 CHECKPOINT FASE 2 CONCLUÍDO
```bash
docker run --rm \
  --device=/dev/dxg \
  -v /usr/lib/wsl/lib/libdxcore.so:/usr/lib/libdxcore.so \
  -v /opt/rocm/lib/librocdxg.so:/opt/rocm/core-10.0/lib/librocdxg.so \
  -v /opt/rocm/lib/librocdxg.so:/usr/lib/librocdxg.so \
  -e HSA_ENABLE_DXG_DETECTION=1 \
  rocm/dev-ubuntu-24.04:latest \
  rocminfo | grep -E "Name:|Marketing Name|gfx"
```
> ✅ **Output Validado**:
> - CPU: AMD Ryzen 5 5500X3D 6-Core Processor
> - GPU: AMD Radeon RX 9070 XT (`gfx1201`, `amdgcn-amd-amdhsa--gfx1201`)

---

## FASE 3 — Instalar e Rodar o Ollama no Docker com GPU

- [x] **Entender o que é o Ollama**
  - Ollama como middleware daemon (Go + llama-server em C++) expondo API REST na porta 11434
  - Ciclo de vida de modelos, offloading de tensores na VRAM e persistência via volumes

- [x] **Rodar o Ollama em um container Docker com acesso à GPU**
  - Comando validado adaptado para paravirtualização DXG (RDNA 4 / RX 9070 XT):
    ```bash
    docker run -d \
      --name ollama \
      --device=/dev/dxg \
      -v /usr/lib/wsl/lib/libdxcore.so:/usr/lib/libdxcore.so \
      -v /opt/rocm/lib/librocdxg.so:/usr/lib/librocdxg.so \
      -v /opt/rocm/lib/librocdxg.so:/opt/rocm/lib/librocdxg.so \
      -e HSA_ENABLE_DXG_DETECTION=1 \
      -v ollama_data:/root/.ollama \
      -p 11434:11434 \
      ollama/ollama:rocm
    ```
  - Validado: Container ativo, GPU RX 9070 XT (`gfx1201`) detectada com 15.8 GiB VRAM total.

- [x] **Baixar o modelo Llama 3.1 8B**
  - `docker exec -it ollama ollama pull llama3.1:8b`
  - Modelo ~4.9GB baixado e persistido no volume gerenciado `ollama_data`.

- [x] **Testar o modelo**
  - Execução via CLI: `docker exec -it ollama ollama run llama3.1:8b`
  - Validado `ollama ps`: `100% GPU`, contexto 4096.
  - Velocidade: 84.45 tokens/s (decode/eval) e 345.15 tokens/s (prefill/prompt eval).

- [x] **Testar a API REST**
  - Executado: `curl http://localhost:11434/api/generate -d '{"model": "llama3.1:8b", "prompt": "Diga oi em português", "stream": false}'`
  - Resposta JSON recebida em ~90ms (`"response":"Olá!"`).

### 🏁 CHECKPOINT FASE 3 CONCLUÍDO
- [x] `docker ps` (Container `ollama` ativo)
- [x] `curl http://localhost:11434/` ("Ollama is running")
- [x] `curl http://localhost:11434/api/generate` (Resposta validada com 100% GPU offload)

---

## FASE 4 — Construir o Agente Python

- [x] **Instalar Python 3.11+ no WSL2 (ou usar o do Windows)**
  - No WSL: `python3.12` validado, pacote `python3-venv` instalado via `sudo apt install python3-venv -y`
  - Verificado: interpretador do sistema funcional com `ensurepip`

- [x] **Criar ambiente virtual do projeto**
  - Navegado até a raiz do projeto em `/mnt/c/Users/plepl/Downloads/01-Trabalho/LLMs`
  - Criado `.venv` via `python3 -m venv .venv` e ativado com `source .venv/bin/activate`
  - Conceito validado: `$PATH` priorizado, isolamento de `site-packages` e link simbólico para `/usr/bin/python3`

- [x] **Instalar dependências básicas**
  - Instalados `requests` e `pydantic` no `.venv`
  - Congelamento determinístico gerado em `requirements.txt` via `pip freeze`

- [x] **Criar um script de teste simples**
  - Implementado `agent/test_connection.py` com health check inicial e inferência síncrona (`stream: False`)
  - Validada resposta em português e latência de geração (~97 tokens/s na RX 9070 XT)

- [x] **Projetar as MCP Tools iniciais**
  - Mapeadas operações essenciais de sistema de arquivos e execução
  - Conceito de segurança validado: Human-in-the-Loop (HITL), controle de *blast radius* e whitelisting via dispatcher (`AVAILABLE_TOOLS`)

- [x] **Implementar o agente com function calling (Loop Básico + Memória)**
  - Implementado `agent/tools.py` com `list_files`, validação defensiva de caminhos (`validade_path`) e contrato OpenAPI/JSON Schema (`TOOLS_SCHEMA`)
  - Implementado `agent/main.py` com ciclo autônomo multi-step (`chat_turn`) e travamento de iterações (`max_turns`)
  - Adicionado `system prompt` para controle de *over-eager tool calling* (gatilho rápido)
  - Resolvida a amnésia contextual persistindo `conversation_history` entre as entradas do usuário
  - Injetado `Path.cwd()` no prompt e mitigado *example poisoning* no schema de caminhos

- [x] **Expandir as Ferramentas em `agent/tools.py` e Integrar no Agente**
  - [x] `read_file(filepath, max_chars)` com trava de tamanho e detecção de binários
  - [x] `create_folder(path)`
  - [x] `move_file(src, dst)` e `copy_file(src, dst)`
  - [x] `delete_file(path)` com confirmação explícita no terminal (HITL)
  - [x] `run_command(cmd)` com restrições e timeout

### 🏁 CHECKPOINT FASE 4 CONCLUÍDO
- [x] Conexão e inferência direta validadas (`agent/test_connection.py`)
- [x] CLI interativo com function calling multi-turnos e auto-cura (`agent/main.py`)
- [x] Ferramentas de sistema de arquivos e subprocessos blindadas e testadas com HITL (`agent/tools.py`)

- Dividas técnicas a serem satisfeitas:
    - [ ] Inspecionar a VRAM: GET /api/ps devolve exatamente quais modelos estão ocupando a memória de vídeo agora.
    - [ ] Ejetar modelo ativo: POST /api/generate com {"model": "modelo_anterior", "keep_alive": 0} libera a VRAM instantaneamente.
    - [ ] Warm-up imediato: POST /api/generate com {"model": "modelo_escolhido"} (sem prompt) força o Ollama a subir tudo para a GPU antes de liberar o prompt "Você: " para o usuário.



---

## FASE 5 — MCP Servers e Rotinas

- [x] **Implementar MCP Server de filesystem**
  - Implementado servidor MCP oficial em `agent/mcp_server.py` sobre transporte STDIO (JSON-RPC)
  - 7 ferramentas registradas via decorators (`list_files`, `read_file`, `create_directory`, `move_file`, `copy_file`, `delete_file`, `run_command`)
  - Validado cliente assíncrono em `agent/test_mcp_client.py` com handshake, listagem de tools e execução remota via IPC

- [ ] **Implementar rotinas pré-definidas**
  - Crie um diretório `routines/` com arquivos YAML ou JSON descrevendo rotinas
  - Exemplo de rotina:
    ```yaml
    name: "limpar-downloads"
    description: "Organiza a pasta Downloads por tipo de arquivo"
    steps:
      - action: list_files
        path: "~/Downloads"
      - action: create_folder
        path: "~/Downloads/Imagens"
      - action: move_file
        pattern: "*.jpg,*.png,*.gif"
        destination: "~/Downloads/Imagens"
      # ... etc
    ```

- [ ] **Implementar rotinas de troubleshooting**
  - Mesma ideia, mas com lógica condicional
  - Ex: "Se o serviço X não está rodando, reinicie. Se falhar, verifique os logs."

- [ ] **Testar end-to-end**
  - Crie uma pasta de teste com arquivos bagunçados
  - Peça ao agente para organizá-la
  - Verifique se os arquivos foram movidos corretamente

### 🏁 CHECKPOINT FASE 5
> O agente consegue:
> - [ ] Listar arquivos de uma pasta
> - [ ] Mover arquivos baseado em instrução em linguagem natural
> - [ ] Executar uma rotina pré-definida do início ao fim
> - [ ] Recusar ações perigosas (deletar sem confirmação, executar comandos arbitrários)

---

## FASE 6 — Docker Compose e Persistência

- [ ] **Criar `docker-compose.yml`** que:
  - Sobe o Ollama com acesso à GPU
  - Monta volumes para persistir modelos
  - Expõe a porta 11434
  - (Opcional) Sobe uma interface web como Open WebUI

- [ ] **Configurar início automático**
  - O container deve subir quando o WSL2 iniciar
  - Pesquise: "como rodar um script no boot do WSL2"

- [ ] **Documentar tudo**
  - Atualize este README com o que você aprendeu
  - Documente os problemas que encontrou e como resolveu
  - Isso é o seu diário de bordo

### 🏁 CHECKPOINT FASE 6
```bash
docker compose up -d            # Deve subir tudo com um comando
curl http://localhost:11434/    # Deve responder "Ollama is running"
```

---

## Backlog futuro (não faça agora)

- [ ] Adicionar interface web (Open WebUI)
- [ ] Implementar memória persistente (histórico de conversas)
- [ ] Adicionar mais rotinas de automação
- [ ] Testar modelos maiores (se precisar de mais capacidade de raciocínio)
- [ ] Deep dive: A viagem do dado GPU-PV (como a instrução de inferência sai do Python no container, passa por /dev/kfd, dxgkrnl no WSL2, driver Adrenalin no Windows e chega no silício da GPU)
- [ ] Implementar sistema de logs e auditoria das ações do agente
- [ ] Monitoramento de uso de GPU (temperatura, VRAM)

---

## Recursos úteis

| Recurso | Link |
|---------|------|
| Docker docs | https://docs.docker.com/ |
| ROCm docs | https://rocm.docs.amd.com/ |
| Ollama docs | https://github.com/ollama/ollama |
| MCP spec | https://spec.modelcontextprotocol.io/ |
| Llama 3.1 | https://llama.meta.com/ |
| Python venv | https://docs.python.org/3/library/venv.html |
