# LLM Local — Agente de Controle de Arquivos e Automação

## O que é este projeto

Um **agente LLM local** rodando na sua máquina que:

1. **Controla e move arquivos** — renomeia, organiza pastas, limpa lixo
2. **Executa rotinas** — sequências pré-definidas de organização e manutenção
3. **Faz troubleshooting** — segue checklists para diagnosticar e resolver problemas
4. **Opera 100% offline** — nenhum dado sai da sua máquina

---

## Arquitetura (visão geral)

Tudo roda nativo no Windows 11, sem WSL nem Docker (Fase 7). Fluxo de um pedido:

```
Você (terminal)
  │  digita o pedido e responde (s/n) às confirmações
  ▼
agent/main.py  (cliente MCP) ── HTTP 127.0.0.1:8080 ──▶ llama-server.exe  (llama.cpp, processo filho)
  │                             /v1/chat/completions     │  ROCm (HIP SDK) ou Vulkan
  │  stdio = JSON-RPC 2.0                                ▼
  │  initialize · tools/list · tools/call           driver Adrenalin (WDDM) → GPU (PCIe)
  │  elicitation/create (servidor pede o s/n)
  ▼
agent/mcp_server.py  (8 ferramentas, processo filho do main) ── agent/routines.py (rotinas YAML)
  │  agent/guard.py: raízes permitidas + programas permitidos, antes de qualquer pergunta
  ▼
Disco: leitura no projeto inteiro; escrita só em teste_sandbox\ (ou em AGENT_WRITE_ROOTS)
```

- **main.py** sobe o llama-server com o modelo escolhido, lê as ferramentas do servidor MCP pelo
  `tools/list`, converte para o formato OpenAI e executa cada chamada do modelo com `call_tool`.
  Ao sair, encerra o llama-server e a VRAM volta ao sistema.
- **llama_server.py** monta a linha de comando do servidor, espera o `/health`, mede a VRAM e fala
  com o `/v1/chat/completions`.
- **mcp_server.py** é quem executa as ferramentas. `delete_file`, `run_command` e `run_routine` pedem
  confirmação humana por *elicitation*: o servidor manda o pedido pelo canal JSON-RPC e o
  `main.py` pergunta a você no terminal. Sem resposta "s", nada acontece.
- **routines.py** executa as rotinas de `routines/` passo a passo, pelas mesmas funções das ferramentas.
- **system_prompt.py** guarda o prompt de sistema (com o catálogo das rotinas); **evals/prompt_traps.py** é a bateria de
  casos-armadilha que valida o prompt contra o modelo real.

---

## Stack tecnológica

| Camada          | Tecnologia                         | Função                                         |
|-----------------|------------------------------------|------------------------------------------------|
| **GPU**         | AMD RX 9070 XT (`gfx1201`, 16 GB)  | Aceleração da inferência do modelo             |
| **Driver GPU**  | Adrenalin (WDDM) + HIP SDK 7.2     | O HIP SDK só é preciso no backend ROCm         |
| **Servidor LLM**| llama.cpp `llama-server` b12094 (Vulkan) | Serve o GGUF, API OpenAI em 127.0.0.1:8080 |
| **Modelo**      | **gemma4-12b** (Q4_K_M)            | 11,9B parâmetros, 6,86 GiB; 8,3 GiB na VRAM com 32k |
| **Agente**      | Python 3.12 + SDK `mcp` 2.3.0      | main.py (cliente) + mcp_server.py (stdio)      |
| **Comandos**    | Git for Windows (`usr\bin`) + System32 | Programas do `run_command`                 |

### Modelo oficial: gemma4-12b (decidido em 27/10/2026)

O projeto nasceu com o Llama 3.1 8B Instruct Q4_K_M. A troca foi decidida pela bateria
`evals/prompt_traps.py` (6 casos-armadilha × 3 rodadas, conferindo chamadas e texto):

| Modelo        | Arquivo | Bateria (caminho MCP) | Observação |
|---------------|---------|-----------------------|------------|
| `llama3.1:8b` | 4,6 GB  | 12/18                 | Obedece a instrução escondida em arquivo; às vezes erra nome de arquivo |
| `gemma4:12b`  | 7,0 GB  | 18/18                 | O único sem falha, inclusive no caso de injeção |

Os números acima são da época do Ollama. Na Fase 7 o mesmo GGUF passou a ser servido pelo llama.cpp
(ver abaixo). No código, o modelo oficial fica em `OFFICIAL_MODEL` (`agent/llama_server.py`): é o nome
do arquivo em `C:\Users\plepl\llm\models\` sem o `.gguf`. O `main.py` o marca como "(oficial)" e o
escolhe com Enter, e a bateria o usa como padrão.

---

## Como rodar

No PowerShell, na raiz do projeto.

```powershell
# 1. Ambiente Python (uma vez)
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

# 2. Agente (sobe e encerra o llama-server sozinho)
.venv\Scripts\python agent\main.py

# Checagens manuais
.venv\Scripts\python agent\test_connection.py     # modelo: sobe, responde "ok", encerra
.venv\Scripts\python agent\test_mcp_client.py     # ferramentas e cerca, sem modelo

# Bateria do prompt (sobe o próprio llama-server; não rode com o agente aberto)
.venv\Scripts\python evals\prompt_traps.py gemma4-12b 3
```

Pré-requisitos fora do repositório:

| Item | Onde | Observação |
|---|---|---|
| Builds do llama.cpp | `C:\Users\plepl\llm\llama.cpp\{rocm,vulkan}\` | Releases oficiais do llama.cpp para Windows |
| Modelos GGUF | `C:\Users\plepl\llm\models\*.gguf` | Um arquivo por modelo; o nome vira a opção do menu |
| HIP SDK 7.2 | `C:\Program Files\AMD\ROCm\7.2\` | Só para o backend ROCm; instala sem trocar o Adrenalin |
| Git for Windows | `C:\Program Files\Git\usr\bin\` | Os programas GNU do `run_command` |

Variáveis de ambiente (todas opcionais):

| Variável | Padrão | Para quê |
|---|---|---|
| `AGENT_BACKEND` | `vulkan` | `vulkan` ou `rocm` |
| `AGENT_NUM_CTX` | `32768` | Janela de contexto do llama-server |
| `AGENT_PORT` | `8080` | Porta do llama-server (sempre no loopback) |
| `AGENT_WRITE_ROOTS` | `<projeto>\teste_sandbox` | Raízes de escrita, separadas por `;` |
| `LLM_HOME` | `C:\Users\plepl\llm` | Onde ficam `llama.cpp\` e `models\` |
| `HIP_PATH` | `C:\Program Files\AMD\ROCm\7.2` | HIP SDK (backend ROCm) |

O código está versionado em https://github.com/pedro470/llm-local-agent (privado). O setup antigo
(WSL2 + Docker + Ollama, Fases 1 a 6) fica no histórico do git, no commit `76a8228`.

---

## Decisões de design

### Fase 7: llama.cpp nativo no Windows (05/11/2026)
Com o agente pronto, a pilha WSL2 → Docker → Ollama virou peso morto: três camadas de virtualização
entre o Python e a GPU, que existiam porque o ROCm era só Linux. O llama.cpp tem builds Windows
oficiais com ROCm e Vulkan, e o `llama-server` dele é o mesmo motor que o Ollama embute.

O que mudou, camada por camada:

| Antes (Fases 1-6) | Agora (Fase 7) | Por quê |
|---|---|---|
| Ollama em container, `restart: unless-stopped` | `llama-server.exe` filho do `main.py` | Um servidor = um modelo; sai o agente, sai a VRAM |
| GPU-PV: `/dev/dxg` + `libdxcore` + `librocdxg` | Driver Adrenalin direto (WDDM) | Sem a ponte, a geração ficou ~12% mais rápida (bench abaixo) |
| `/api/chat` do Ollama | `/v1/chat/completions` (OpenAI) | Formato padrão; `reasoning_content` no lugar de `thinking` |
| `num_ctx` por pedido | `-c 32768 -np 1` na subida | O KV é alocado uma vez; um slot só, com a janela inteira |
| `/api/ps` para a VRAM | Contador `GPU Process Memory` do Windows | O WDDM mede a VRAM por processo, driver incluso |
| `ls`, `ps`, `free`... do Ubuntu | GNU do Git + `tasklist`, `systeminfo` | Mesma lista, caminhos absolutos, sem shell |
| venv em `~/.venvs` (fora do 9P) | `.venv` no projeto | Sem 9P, o NTFS não penaliza mais os imports |

**Ciclo de vida do servidor.** O `main.py` cria o `llama-server.exe` e o põe num **Job Object** com
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Um Job Object é um grupo de processos gerido pelo kernel: quando o
último handle dele fecha, e o único handle é do Python, o kernel mata os membros. Então, se o Python
morrer de qualquer jeito (Ctrl+C, janela fechada, crash), o servidor morre junto e não fica um órfão
segurando ~8 GB de VRAM e a porta 8080. O SDK do MCP faz o mesmo com o `mcp_server.py`.
`CREATE_NEW_PROCESS_GROUP` faz o Ctrl+C ir só para o Python, que encerra o servidor na ordem certa.

**Backend: ROCm ou Vulkan.** É a física das duas fases da inferência:
- *Prefill* (o prompt inteiro de uma vez) é produto matriz × matriz, limitado por **computação**. O ROCm
  usa as GEMMs afinadas da AMD (hipBLASLt/rocBLAS) e ganha: +32% com contexto vazio, +62% em 8k.
- *Geração* (um token por vez) é matriz × vetor, limitada por **banda de memória**: cada token lê os
  6,86 GiB de pesos. Com ~640 GB/s, o teto é ~87 t/s. O Vulkan chega a 78% dele (68,3 t/s), o ROCm a
  71% (61,9): o HIP no Windows paga mais por lançamento de kernel, e os shaders do Vulkan fundem mais
  operações por envio.
- Com `p` tokens novos de prefill e `g` tokens gerados por chamada, em 8k o Vulkan só ganha se
  `g/p > 0,37`. A estimativa inicial (ler ~600 tokens de ferramenta, gerar ~150: `g/p ≈ 0,25`) dava o
  ROCm, e errou o `g`: o gemma4 pensa de 100 a 300 tokens por chamada e, com o cache do prefixo no
  slot, os tokens novos de prefill são poucos. A geração domina.
- Medido na bateria completa (9 casos × 3 rodadas, 27/27 nos dois): ROCm 224, 246 e 228 s (média 233);
  Vulkan 222 e 197 s (média 210). ~10% a favor do Vulkan, da ordem da variação entre rodadas.
- O ROCm continua melhor quando o cache se perde: quando a janela corta o histórico, o prefill de
  ~28k tokens leva ~16 s no ROCm contra ~28 s no Vulkan.
- **Decisão (05/11/2026): Vulkan é o padrão.** Mais rápido na carga real do agente e sem depender do
  HIP SDK (o driver Vulkan vem com o Adrenalin). O build ROCm fica instalado: `AGENT_BACKEND=rocm`.

| Bench `llama-bench`, gemma4 Q4_K_M, `-ngl 99 -fa 1` | pp512 | pp2048 | tg128 | pp512 @8k | tg128 @8k |
|---|---|---|---|---|---|
| Windows ROCm (HIP SDK 7.2) | 2720 | 2589 | 61,9 | 1796 | 57,8 |
| Windows Vulkan | 2066 | 1912 | 68,3 | 1108 | 61,1 |
| WSL, container `ollama:rocm` (Fases 3-6) | 2520 | 2536 | 54,2 | 1770 | 51,7 |

O Vulkan nesta máquina precisa de `VK_LOADER_LAYERS_DISABLE=VK_LAYER_Twitch_Overlay`: a camada
implícita do Twitch Studio derruba o `vkCreateDevice` com `ErrorDeviceLost`. O `llama_server.py` define
a variável sozinho.

**Bug achado na migração.** O SDK do MCP só repassa ao processo do servidor uma lista fixa de
variáveis de ambiente (`PATH`, `HOME`/`USERPROFILE`...). O `AGENT_WRITE_ROOTS` nunca chegava ao
`guard.py`, nem no Linux: a cerca sempre usava o padrão `teste_sandbox`. Errava para o lado seguro,
mas a configuração documentada não funcionava. Agora o `main.py` repassa as `AGENT_*` à mão.

### Tamanho do modelo
- O limite é o tamanho em GB, não o número de parâmetros: arquivo do modelo + KV cache precisam
  caber na VRAM livre da 9070 XT. Se não couberem, parte das camadas vai para a RAM e a
  velocidade despenca.
- O 8B foi a aposta inicial ("com bom prompting é suficiente"), mas a bateria de armadilhas mostrou
  limites dele em segurança e fidelidade; o oficial passou a ser o gemma4 12B (ver acima).

### Por que quantização Q4_K_M?
- 6,86 GiB contra ~24 GB em FP16
- Perda de qualidade mínima para tarefas de tool-use
- Cabe 100% na VRAM com sobra para contexto

### Contexto e VRAM (etapa 5; números do llama.cpp de 05/11/2026)
- O servidor sobe com `-c 32768` (`NUM_CTX` em `agent/llama_server.py`, trocar com `AGENT_NUM_CTX`).
  O prompt de sistema mais o schema das 8 ferramentas gastam ~1.700 tokens.
- VRAM medida pelo contador do Windows: **8,26 GiB** = pesos 6,86 + KV 0,97 + compute 0,15 + driver.
  O KV tem duas partes: as 8 camadas de atenção global (512 MiB, crescem com o contexto) e as 40 de
  janela deslizante de 1024 tokens (480 MiB, fixas). A tabela de embeddings (787 MiB, vocabulário de
  262k) fica na RAM, mapeada do arquivo: só é lida uma linha por token.
- Se o prompt passa da janela, o llama-server recusa o pedido (o Ollama descartava mensagens antigas
  sem avisar). Por isso o `main.py` tem a própria janela (`trim_history`): corta pedidos inteiros,
  mais antigos primeiro, antes de cada chamada, e mantém o prompt de sistema e o pedido atual.
  Depois do corte, uma nota no prompt de sistema avisa o modelo; sem a frase "o primeiro pedido que
  você ainda vê NÃO é o primeiro", ele ignorava a nota em 4 de 5 rodadas.
- Medidor: `usage.prompt_tokens` conta o prompt inteiro, mesmo o trecho que veio do cache do slot.
  O `main.py` mostra o uso depois de cada resposta.
- O raciocínio do gemma4 (`reasoning_content`; `enable_thinking` liga o canal no template) fica no
  histórico só durante a rodada em andamento. No meio de uma cadeia de ferramentas o template o
  reenvia (52 tokens sem, 299 com): é o plano do modelo. Com a rodada encerrada, o template o
  descarta, e o `chat_turn` o apaga quando chega pedido novo. A versão da etapa 5 apagava cedo demais,
  e o modelo criava a pasta, esquecia que faltava mover e dizia "movi" (3 de 10 vezes).

### Rotinas: o modelo escolhe, o Python executa (etapa 6)
- Cada rotina é um YAML em `routines/`. O modelo só escolhe a rotina e os parâmetros (`run_routine`);
  `agent/routines.py` expande os arquivos, roda os passos em ordem e avalia as condições. O mesmo
  pedido gera sempre as mesmas ações, e o modelo não tem como pular passo nem inventar resultado.
- Os passos chamam as mesmas funções das ferramentas: a cerca vale igual, e recusa antes da pergunta
  (caminho fora das raízes de escrita ou programa fora da lista barra a rotina inteira).
- Uma confirmação só, com a lista de tudo que escreve ou executa comando. Os arquivos são expandidos
  antes dessa pergunta: a lista que o humano aprova é a que roda. `delete_file` pergunta de novo,
  arquivo por arquivo.
- Passos: `tool` (com `save` para guardar a saída), `for_each` (arquivos de uma pasta por padrão,
  com `before` que só roda se algo casou), `say` (conclusão para o relatório) e `stop`. Qualquer
  passo aceita `when` (regex, e comparação numérica do grupo capturado): é a lógica condicional
  do troubleshooting. Ver `routines/diagnostico-agente.yaml`.
- O catálogo das rotinas vai no prompt de sistema. Com uma ferramenta `list_routines` no meio, o
  modelo consultava, anunciava "vou executar" e parava (organizar 2/3, diagnóstico 1/3); com o
  catálogo no prompt, 5/5 nos dois.
- As rotinas só leem e organizam: a cerca não deixa o agente encerrar processos. No troubleshooting,
  a conclusão diz o comando que o usuário deve rodar (ex.: `taskkill /PID <pid>` para um llama-server órfão).

### Por que o agente é cliente de um servidor MCP
- Uma implementação só das ferramentas (o antigo `tools.py` duplicava o servidor e divergia dele)
- O servidor valida os argumentos pelo schema: tipo errado vindo do modelo é convertido ou recusado
- Qualquer outro cliente MCP pode usar as mesmas ferramentas com as mesmas travas

### Por que a confirmação humana é por elicitation
- O SDK cria o servidor sem console próprio (`CREATE_NO_WINDOW`; no Linux era `start_new_session`),
  e o stdin dele é o canal JSON-RPC: o servidor não tem como perguntar nada direto a você
- A elicitation é o mecanismo do próprio protocolo: o servidor pede, o cliente pergunta ao humano
- Fail-closed: cliente sem elicitation, recusa, cancelamento ou erro bloqueiam a ação

### Por que uma cerca além da confirmação humana
- A confirmação só existe em `delete_file` e `run_command`; mover e copiar não perguntam
- O llama3.1:8b obedece a instruções escondidas em arquivos (teste de injeção da bateria): o prompt
  não protege, a cerca sim
- `guard.py` resolve cada caminho (segue symlinks e junctions, elimina `..`) e exige que caia numa raiz
  permitida; `run_command` aceita 18 programas de leitura, executados sem shell
- Cada programa aponta para um `.exe` com caminho absoluto. O `CreateProcess` do Windows procura um
  programa sem caminho também na pasta atual: um `ls.exe` plantado no projeto seria executado
- Caminhos no estilo do Git (`/c/Windows`) resolvem, no Python, para `C:\c\Windows`: fora das raízes,
  recusados. Opções com valor colado (`--file=C:/x`) têm o valor conferido
- A saída dos programas do Git é UTF-8; a dos do Windows (`tasklist`, `systeminfo`) vem na code page
  OEM do console (cp850 em pt-BR), e o servidor decodifica cada uma do jeito certo
- A recusa vem antes da pergunta: quando o (s/n) aparece, a ação já é permitida

---

## Estimativa de armazenamento

| Item                                        | Tamanho aprox. |
|---------------------------------------------|---------------|
| Builds do llama.cpp (ROCm + Vulkan)         | ~1 GB         |
| HIP SDK 7.2                                 | ~3 GB         |
| Modelos (`gemma4-12b`, `gemma4-12b-heretic`) | ~14 GB       |
| Python + dependências do agente             | ~0,1 GB       |
| **Total estimado**                          | **~18 GB**    |

> Antes, com a distro do WSL, a imagem `ollama:rocm` e o volume, eram ~25 GB só dentro do disco
> virtual do WSL, mais o HIP SDK no Windows para os benchmarks.

---

## Modo de Trabalho e Regras

1. **Pair Programming Ativo**: O agente executa a implementação prática de código, configurações e testes, detalhando cada etapa.
2. **Arquitetura e Fundamentos**: O usuário direciona o projeto, valida as entregas e domina a arquitetura através de explicações transparentes de cada componente.
3. **Commits frequentes**: Manter configurações e código versionados.
4. **Sem atalhos conceituais**: Cada fase mantém seu checkpoint validado para garantir que a pilha está íntegra antes de avançar.

---

## Referências

- [llama.cpp — GitHub](https://github.com/ggml-org/llama.cpp) (releases com builds Windows ROCm e Vulkan)
- [llama-server — README](https://github.com/ggml-org/llama.cpp/tree/master/tools/server)
- [HIP SDK para Windows (AMD)](https://rocm.docs.amd.com/projects/install-on-windows/en/latest/)
- [Job Objects (Microsoft)](https://learn.microsoft.com/pt-br/windows/win32/procthread/job-objects)
- [ROCm — Matriz de compatibilidade](https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html)
