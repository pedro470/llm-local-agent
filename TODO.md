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
    (substituído em 27/10 por `~/.venvs/llm-local`, no disco Linux: em `/mnt/c` os imports eram ~5x mais lentos)
  - Conceito validado: `$PATH` priorizado, isolamento de `site-packages` e link simbólico para `/usr/bin/python3`

- [x] **Instalar dependências básicas**
  - Instalados `requests` e `pydantic` no `.venv`
  - Congelamento determinístico gerado em `requirements.txt` via `pip freeze`

- [x] **Criar um script de teste simples**
  - Implementado `agent/test_connection.py` com health check inicial e inferência síncrona (`stream: False`)
  - Validada resposta em português e latência de geração (~97 tokens/s na RX 9070 XT)
  - Hoje o `test_connection.py` só lista os modelos com suporte a ferramentas (sem inferência)

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
  - [x] `create_directory(directory_path)` (o nome real; o rascunho dizia `create_folder`)
  - [x] `move_file(src, dst)` e `copy_file(src, dst)`
  - [x] `delete_file(path)` com confirmação explícita no terminal (HITL)
  - [x] `run_command(cmd)` com timeout (as restrições de verdade só vieram na etapa 3 do roteiro abaixo)

### 🏁 CHECKPOINT FASE 4 CONCLUÍDO
- [x] Conexão e inferência direta validadas (`agent/test_connection.py`)
- [x] CLI interativo com function calling multi-turnos e auto-cura (`agent/main.py`)
- [x] Ferramentas de sistema de arquivos e subprocessos com HITL (`agent/tools.py`, removido na etapa 4: as ferramentas agora vivem só no `mcp_server.py`)

- Dividas técnicas a serem satisfeitas:
    - [x] Inspecionar a VRAM: GET /api/ps devolve exatamente quais modelos estão ocupando a memória de vídeo agora. (`loaded_models()`, etapa 5)
    - [x] Ejetar modelo ativo (`unload()`; o `main.py` descarrega na subida o modelo que não for o escolhido): POST /api/generate com {"model": "modelo_anterior", "keep_alive": 0} libera a VRAM instantaneamente. (Na prática o container já usa `OLLAMA_MAX_LOADED_MODELS=1`, que descarrega o anterior sozinho.)
    - [x] Warm-up imediato: `warm_up()` em `ollama_client.py`; o `main.py` carrega o modelo em paralelo com a subida do servidor MCP (com o modelo na VRAM, o "Você:" aparece em 1,6 s).



---

## FASE 5 — MCP Servers e Rotinas

- [x] **Implementar MCP Server de filesystem**
  - Implementado servidor MCP oficial em `agent/mcp_server.py` sobre transporte STDIO (JSON-RPC)
  - 7 ferramentas registradas via decorators (`list_files`, `read_file`, `create_directory`, `move_file`, `copy_file`, `delete_file`, `run_command`)
  - Validado cliente assíncrono em `agent/test_mcp_client.py` com handshake, listagem de tools e execução remota via IPC

- [x] **Cerca de segurança** (`agent/guard.py`, etapa 3 do roteiro)
  - Raízes permitidas: leitura no projeto, escrita só em `teste_sandbox/` (trocar com `AGENT_WRITE_ROOTS`)
  - `run_command` só com 18 programas de leitura, executados sem shell
  - A recusa vem antes da pergunta ao humano

- [x] **Agente como cliente MCP** (etapa 4 do roteiro)
  - `main.py` sobe o `mcp_server.py` por stdio e usa `tools/list` + `call_tool`; `tools.py` removido
  - Confirmação humana por elicitation do MCP (o `/dev/tty` não existe no processo filho: o SDK usa `start_new_session=True`)

- [x] **Prompt de sistema revisado + bateria de armadilhas**
  - `agent/system_prompt.py` e `evals/prompt_traps.py` (9 casos desde a etapa 6, conferindo chamadas, texto e disco)

- [x] **Implementar rotinas pré-definidas** (etapa 6 do roteiro)
  - `routines/organizar-por-tipo.yaml`, executada por `agent/routines.py` (o modelo só chama `run_routine`)
  - Formato: passos `tool`, `for_each`, `say`, `stop`, com `when` (ver o docstring de `routines.py`)
  - Para mexer em `~/Downloads`, inclua a pasta em `AGENT_WRITE_ROOTS` antes: a cerca vale igual
  - Uma confirmação só, com a lista de ações já expandida; `delete_file` pergunta arquivo por arquivo

- [x] **Implementar rotinas de troubleshooting**
  - `routines/diagnostico-agente.yaml`: Ollama rodando, memória do WSL, disco C:, tamanho da `.trash`
  - Lógica condicional com `save` + `when` (regex e comparação numérica)
  - "Reinicie o serviço" ficou como conclusão com o comando a rodar: a cerca não deixa o agente
    iniciar serviços

- [x] **Testar end-to-end**
  - `main.py` real, pasta com 8 arquivos, pedido em linguagem natural, "s" no terminal: 7 arquivos
    nas pastas certas e o de tipo desconhecido no lugar (28/10/2026)
  - Bateria com 3 casos novos: organizar por rotina, diagnóstico por rotina, mover em linguagem natural

### 🏁 CHECKPOINT FASE 5
> O agente consegue:
> - [x] Listar arquivos de uma pasta (bateria: caso "listar sem inventar")
> - [x] Mover arquivos baseado em instrução em linguagem natural (bateria: caso "mover em linguagem natural")
> - [x] Executar uma rotina pré-definida do início ao fim (`organizar-por-tipo` no `main.py` real; bateria: casos de rotina)
> - [x] Recusar ações perigosas: a cerca recusa caminhos e programas fora da lista; apagar e executar só com "s" no terminal (teste de ponta a ponta)

---

## FASE 6 — Docker Compose e Persistência

- [x] **Criar `docker-compose.yml`** — `docker/docker-compose.yml` (05/11/2026)
  - Sobe o Ollama com acesso à GPU (`/dev/dxg` + binds da ROCDXG; log: `library=ROCm compute=gfx1201`)
  - Volume `ollama_data` como `external` (os modelos que já existiam, sem risco no `down -v`)
  - Porta 11434 só no loopback (`127.0.0.1`); o Windows chega por localhost
  - (Opcional) Open WebUI: não feito, segue no backlog

- [x] **Configurar início automático**
  - systemd (já ligado) sobe o dockerd no boot; `restart: unless-stopped` religa o container
  - VM ligada sem terminal: `[general] instanceIdleTimeout=-1` no `.wslconfig`. `vmIdleTimeout=-1`
    sozinho não segurou (a distro caiu antes); `instanceIdleTimeout` em `[wsl2]` é chave desconhecida no WSL 2.6.3
  - Não automatizado: ligar a VM no logon do Windows (sobe no primeiro `wsl.exe`)

- [x] **Documentar tudo** — README, "Fase 6: compose e VM sempre ligada"

### 🏁 CHECKPOINT FASE 6 — aprovado em 05/11/2026
```bash
docker compose -f docker/docker-compose.yml up -d   # Deve subir tudo com um comando
curl http://localhost:11434/    # Deve responder "Ollama is running"
```

---

## Roteiro de correções (revisão de 23/10/2026)

A revisão do projeto achou erros no agente e propôs esta ordem, do risco maior para o menor.
Repositório: https://github.com/pedro470/llm-local-agent (privado).

- [x] **0. Escolher o modelo oficial** — `gemma4:12b`, decidido em 27/10/2026 (ver abaixo)
- [x] **1. Versionar e congelar o ambiente** — git, `.gitignore`, `requirements.txt` com `mcp` 2.3.0 (`0c41d82`)
- [x] **2. Consertar o laço** — `select_model` com `(ok, valor)`, timeout no `send_chat`, tamanho real no truncamento, default numérico no schema (`1c9d444`)
- [x] **3. Cerca nas ferramentas** — `agent/guard.py` com raízes e programas permitidos (`4d397f7`)
- [x] **Prompt de sistema e bateria de armadilhas** — `agent/system_prompt.py`, `evals/prompt_traps.py`; `read_file` aceita `max_chars` em texto (`69f2835`)
- [x] **4. Agente como cliente MCP** — elicitation no lugar do `/dev/tty`, `tools.py` removido, imports tardios e aquecimento do modelo, ambiente em `~/.venvs/llm-local` (`a2b7970`)
- [x] **5. Controlar contexto e VRAM** — `num_ctx` 32768 (`AGENT_NUM_CTX`), janela de histórico com nota de memória cortada, `/api/ps` e ejeção na subida; bateria 18/18 (detalhes no README, "Contexto e VRAM")
- [x] **6. Rotinas e teste ponta a ponta** — executor determinístico (`routines.py`), 2 rotinas, catálogo no prompt, `thinking` mantido dentro da rodada; checkpoint 5; bateria 27/27 (03/11/2026)
- [x] **7. Fase 6** — compose, início automático, distro ligada sem terminal (`instanceIdleTimeout`); checkpoint 6 (05/11/2026)

### Decisão: modelo oficial é o gemma4:12b

Bateria `evals/prompt_traps.py`, 3 rodadas por caso, pelo caminho MCP (27/10/2026):

| Modelo        | Resultado | Ponto fraco |
|---------------|-----------|-------------|
| `llama3.1:8b` | 12/18     | Obedece a instrução escondida em arquivo (0/3 no caso de injeção) |
| `gemma4:12b`  | 18/18     | Ocupa 7,8 GB de VRAM; ~7 s para carregar a frio |
| `qwen38-27b`  | não medido | 12,2 GB: pouca folga para o contexto |

Escolhido o `gemma4:12b`: único 18/18, inclusive no caso de injeção. No código: `OFFICIAL_MODEL` em
`agent/ollama_client.py` (Enter no `main.py`, padrão da bateria).
- [ ] Opcional: remover do volume os modelos que não forem mais usados (`docker exec ollama ollama rm <modelo>`)

### Pendências conhecidas
- [ ] Resposta vazia esporádica do gemma4: às vezes pensa (~100 a 200 tokens de `thinking`) e termina sem texto
  nem ferramenta. Visto no 1º pedido do `main.py` em 2 de 3 execuções (28/10), 0 de 10 na chamada direta.
  Ideia: no `chat_turn`, repetir a chamada uma vez quando vier vazia
- [ ] `agent/test_mcp_client.py`: o docstring ainda descreve a confirmação por `/dev/tty`
- [ ] `.vscode/settings.json` aponta para o Python do Windows; usar a extensão WSL com `~/.venvs/llm-local/bin/python`
- [ ] O `.venv` antigo em `/mnt/c` pode ser apagado (o oficial é `~/.venvs/llm-local`)
- [ ] Testes das etapas 2 a 4 rodaram como scripts avulsos; trazer para `evals/` ou `tests/`

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
