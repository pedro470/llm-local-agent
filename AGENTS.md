# Instruções para o Agente — Projeto LLM Local

## Contexto do Projeto

Este projeto é a construção de um **agente LLM local** que roda na máquina do usuário
para controlar arquivos, executar rotinas de organização/limpeza e seguir checklists
de troubleshooting. Tudo offline, tudo local.

## Hardware do Usuário

- **GPU**: AMD Radeon RX 9070 XT (RDNA 4, `gfx1201`, 16GB VRAM)
- **CPU**: AMD Ryzen 5 5500X3D
- **RAM**: 32GB
- **OS**: Windows 11 Home
- **Armazenamento disponível**: 200GB (negociável até 300GB)

## Stack Definida (desde a Fase 7: tudo nativo no Windows, sem WSL nem Docker)

- **llama.cpp** b12094 (`llama-server.exe`), builds em `C:\Users\plepl\llm\llama.cpp\{rocm,vulkan}\`.
  Backend oficial: **Vulkan** (decidido pelo usuário em 05/11/2026; 210 s contra 233 s na bateria).
  `AGENT_BACKEND=rocm` usa o build ROCm, que precisa do HIP SDK 7.2 (`C:\Program Files\AMD\ROCm\7.2\bin`).
- **Modelos**: um GGUF por modelo em `C:\Users\plepl\llm\models\`; o nome do arquivo é o nome do modelo.
- **Modelo oficial**: `gemma4-12b` (Q4_K_M, 8,3 GiB na VRAM com 32k), decidido pelo usuário em 27/10/2026.
  Na bateria de armadilhas fez 18/18, contra 12/18 do `llama3.1:8b` (o modelo original). No código:
  `OFFICIAL_MODEL` em `agent/llama_server.py`. Trocar de modelo é decisão do usuário.
- **Agente**: Python 3.12 + SDK `mcp` 2.3.0. `agent/main.py` sobe o `llama-server` (filho, num Job Object)
  e o `agent/mcp_server.py` (stdio); a confirmação humana é por elicitation do MCP; a cerca fica em `agent/guard.py`.
- **Ambiente Python**: `.venv` na raiz do projeto, recriado do `requirements.txt` (`py -3.12 -m venv .venv`).

## Perfil e Nível Técnico do Usuário

- **Base Matemática e Engenharia**: Quase graduado em Engenharia Mecânica (UFPE). Domínio sólido de álgebra linear, cálculo matricial, cálculo diferencial, engenharia de controle (espaço de estados, Laplace/Fourier), mecânica lagrangiana e física aplicada. **Não infantilizar matemática nem modelagem analítica**.
- **Experiência Corporativa**: 3+ anos em SAP e 1+ ano em desenvolvimento de integrações (APIs, orquestração, contratos de dados e middleware).
- **Pontos Cegos (Onde focar o ensino)**: Arquitetura de computadores, relação física/lógica CPU-RAM-GPU, barramentos (PCIe, DMA), drivers de kernel (`/dev/kfd`, `/dev/dri`), virtualização no osso e administração Linux/Docker Engine via terminal.
- **Estratégia**: Usar a base de engenharia/física e sistemas corporativos como ponte conceitual para desmistificar o hardware e o sistema operacional.

## Modo de Trabalho — Pair Programming Ativo (Copiloto Executor)

A partir da Fase 5, o formato de atuação é de **Pair Programming Ativo**:

1. **Execução Prática pelo Agente**: O agente escreve o código, cria/modifica arquivos, configura o ambiente e propõe/executa os comandos necessários diretamente.
2. **Explicação Profunda e Arquitetural**: Para cada alteração ou bloco de código, o agente explica a mecânica exata (o que foi feito, por que foi feito e como o sistema/SO/hardware reage por baixo dos panos), mantendo a ponte com engenharia, sistemas corporativos e computação de baixo nível.
3. **Fim das Perguntas Socráticas de Adivinhação**: O usuário não deve ser forçado a adivinhar conceitos opacos da documentação. O agente entrega a explicação direta e clara.
4. **Papel do Usuário**: O usuário atua como arquiteto e revisor do projeto, validando as entregas, fazendo perguntas de aprofundamento e definindo requisitos e prioridades.
5. **Cadência Iterativa**: Um passo ou componente por vez $\to$ implementa $\to$ explica $\to$ valida $\to$ avança para o próximo.

## Estrutura do Projeto

- `README.md` — Arquitetura, stack, como rodar, decisões de design
- `TODO.md` — Fases com checkpoints, roteiro de correções (etapas 0 a 7) e decisão do modelo
- `AGENTS.md` — (este arquivo) Instruções permanentes para o agente
- `agent/main.py` — Laço de conversa com o llama-server; cliente MCP; pergunta (s/n) ao humano
- `agent/mcp_server.py` — As 8 ferramentas (servidor MCP, stdio), incluindo `run_routine`
- `agent/routines.py` — Executor das rotinas YAML (determinístico; o modelo só escolhe a rotina)
- `agent/guard.py` — Cerca: raízes permitidas e programas permitidos
- `agent/system_prompt.py` — Prompt de sistema (com as regras para editá-lo)
- `agent/llama_server.py` — Sobe/encerra o `llama-server`, `/health`, VRAM e `/v1/chat/completions`
- `agent/test_connection.py`, `agent/test_mcp_client.py` — Checagens manuais
- `evals/prompt_traps.py` — Bateria de casos-armadilha do prompt contra o modelo real
- `teste_sandbox/` — Única raiz de escrita padrão (fora do git)
- `routines/` — Rotinas YAML: `organizar-por-tipo`, `diagnostico-agente`

## Progresso Atual

- **FASE 0 CONCLUÍDA**: Fundamentos teóricos aprovados no Checkpoint (Virtualização, Docker, ROCm gfx1201, GGUF/Quantização, Tokenização BBPE, KV Cache e MCP).
- **FASE 1 CONCLUÍDA**: WSL2 + Docker Engine 29.8 nativo no Ubuntu 24.04 (sem Docker Desktop), permissões de socket POSIX (`/run/docker.sock`), grupo `docker` configurado e testado com sucesso via `docker run hello-world` sem `sudo`.
- **FASE 2 CONCLUÍDA**: Acesso GPU validado no Docker via paravirtualização DirectX (`/dev/dxg`), `libdxcore.so` e ponte ROCDXG (`librocdxg.so` v1.2.2). `rocminfo` reconhecendo perfeitamente CPU Ryzen 5 5500X3D e GPU AMD Radeon RX 9070 XT (`gfx1201`).
- **FASE 3 CONCLUÍDA**: Ollama no Docker com aceleração GPU (RX 9070 XT, `gfx1201`), 100% dos tensores alocados na VRAM, inferência testada a 84.45 t/s, modelo Llama 3.1 8B persistido no volume `ollama_data` e API REST HTTP operacional na porta 11434.
- **FASE 4 CONCLUÍDA**: Laço autônomo multi-step com memória entre turnos e 7 ferramentas. Tratados *over-eager tool calling*, *context amnesia* e *example poisoning*.
- **FASE 5 CONCLUÍDA**: servidor MCP pronto e já usado pelo agente; checkpoint 5 aprovado. Feito no roteiro de correções (TODO.md):
  1. git + `requirements.txt` com `mcp`; repositório privado no GitHub pessoal
  2. laço consertado (`select_model`, timeout, truncamento, schema)
  3. cerca `guard.py` (raízes e programas permitidos, recusa antes da pergunta)
  4. `main.py` como cliente MCP, elicitation no lugar do `/dev/tty`, `tools.py` removido, subida rápida
  5. contexto e VRAM: `num_ctx` 32768, janela de histórico (`trim_history`), `/api/ps` e ejeção na subida
  6. rotinas YAML com executor determinístico, catálogo no prompt e teste ponta a ponta (checkpoint 5)
  Mais: prompt de sistema reescrito, bateria `evals/prompt_traps.py` e modelo oficial `gemma4:12b`.
- **FASE 6 CONCLUÍDA** (05/11/2026, etapa 7): `docker/docker-compose.yml` substitui o `docker run`;
  início automático por systemd + `restart: unless-stopped`; a distro fica ligada sem terminal com
  `[general] instanceIdleTimeout=-1` no `.wslconfig` do Windows. Checkpoint 6 aprovado.
- **FASE 7** (fase extra, 05/11/2026): WSL2, Docker e Ollama saíram; o agente sobe o `llama-server.exe`
  nativo como processo filho. O setup antigo fica no histórico do git (commit `76a8228`).

## Regras práticas (aprendidas no projeto)

- **Python**: rode sempre com `.venv\Scripts\python` (ou `.venv/Scripts/python` no Git Bash), da raiz do projeto.
  Saída redirecionada no Windows é cp1252: os scripts fazem `sys.stdout.reconfigure(encoding="utf-8")`.
- **llama-server**: quem sobe é o `main.py` (ou a bateria, ou o `test_connection.py`), e ele morre junto
  com o Python. Não rode dois ao mesmo tempo: a porta 8080 e a VRAM são de um só. Log em `logs/llama-server.log`.
  Órfão (aberto à mão, fora do Job Object): `tasklist /FI "IMAGENAME eq llama-server.exe"` e `taskkill /PID`.
- **GPU**: um modelo por vez, naturalmente: um servidor = um GGUF. Trocar de modelo = sair e entrar no agente.
- **Vulkan**: precisa de `VK_LOADER_LAYERS_DISABLE=VK_LAYER_Twitch_Overlay` (o `llama_server.py` define).
- **Prompt**: mudou `agent/system_prompt.py` ou uma rotina em `routines/` (o catálogo vai no prompt)? Rode
  `evals/prompt_traps.py` antes de commitar. Não cite no
  prompt símbolos ou exemplos que o modelo não deva copiar (o 🛑 citado virou recusa inventada).
- **Segurança**: a proteção real é a cerca + a confirmação humana, não o prompt. Ferramenta nova que escreve
  ou executa passa por `guard.py`; ação destrutiva pede `_ask_confirmation` (elicitation, fail-closed).
- **thinking do gemma4**: não apague dentro da rodada em andamento: é o plano do modelo entre uma ferramenta e
  outra. Só sai das rodadas encerradas (`chat_turn`).
- **Git**: commit e push só quando o usuário pedir. O remoto é o GitHub **pessoal** `pedro470/llm-local-agent`
  (autor `pedromoura463@gmail.com`, configurado só neste repositório), nunca a conta da empresa. Faça o push
  com o token do `gh`: `git -c credential.helper= -c "credential.helper=!gh auth git-credential" push`.

## Referências Rápidas

- ROCm compat matrix: https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html
- llama.cpp releases (builds Windows ROCm e Vulkan): https://github.com/ggml-org/llama.cpp/releases
- GPU target: `gfx1201`
