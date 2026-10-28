# LLM Local — Agente de Controle de Arquivos e Automação

## O que é este projeto

Um **agente LLM local** rodando na sua máquina que:

1. **Controla e move arquivos** — renomeia, organiza pastas, limpa lixo
2. **Executa rotinas** — sequências pré-definidas de organização e manutenção
3. **Faz troubleshooting** — segue checklists para diagnosticar e resolver problemas
4. **Opera 100% offline** — nenhum dado sai da sua máquina

---

## Arquitetura (visão geral)

Tudo roda dentro do WSL2 (Ubuntu 24.04) no Windows 11. Fluxo de um pedido:

```
Você (terminal)
  │  digita o pedido e responde (s/n) às confirmações
  ▼
agent/main.py  (cliente MCP) ──── HTTP :11434 ────▶ Ollama  (container ollama/ollama:rocm)
  │                                                    │  llama-server + HIP/ROCm
  │  stdio = JSON-RPC 2.0                              │  librocdxg → libdxcore → /dev/dxg
  │  initialize · tools/list · tools/call              ▼
  │  elicitation/create (servidor pede o s/n)     VMBus → dxgkrnl → Adrenalin → GPU (PCIe)
  ▼
agent/mcp_server.py  (7 ferramentas, processo filho do main)
  │  agent/guard.py: raízes permitidas + programas permitidos, antes de qualquer pergunta
  ▼
Disco: leitura no projeto inteiro; escrita só em teste_sandbox/ (ou em AGENT_WRITE_ROOTS)
```

- **main.py** conversa com o Ollama, lê as ferramentas do servidor pelo `tools/list`, converte
  para o formato do Ollama e executa cada chamada do modelo com `call_tool`.
- **mcp_server.py** é quem executa as ferramentas. `delete_file` e `run_command` pedem
  confirmação humana por *elicitation*: o servidor manda o pedido pelo canal JSON-RPC e o
  `main.py` pergunta a você no terminal. Sem resposta "s", nada acontece.
- **system_prompt.py** guarda o prompt de sistema; **evals/prompt_traps.py** é a bateria de
  casos-armadilha que valida o prompt contra o modelo real.

---

## Stack tecnológica

| Camada          | Tecnologia                     | Função                                      |
|-----------------|--------------------------------|----------------------------------------------|
| **GPU**         | AMD RX 9070 XT (`gfx1201`)    | Aceleração da inferência do modelo           |
| **Driver GPU**  | ROCm 10.x                     | Interface entre o SO Linux e a GPU AMD       |
| **Container**   | Docker no WSL2 (Ubuntu)        | Isola o ambiente Linux com ROCm + Ollama     |
| **Servidor LLM**| Ollama                        | Serve o modelo, expõe API REST na porta 11434|
| **Modelo**      | **gemma4:12b** (Q4_K_M)        | 11,9B parâmetros, 7,0 GB; 7,8 GB na VRAM     |
| **Agente**      | Python 3.12 + SDK `mcp` 2.3.0  | main.py (cliente) + mcp_server.py (stdio)    |

### Modelo oficial: gemma4:12b (decidido em 27/10/2026)

O projeto nasceu com o Llama 3.1 8B Instruct Q4_K_M. A troca foi decidida pela bateria
`evals/prompt_traps.py` (6 casos-armadilha × 3 rodadas, conferindo chamadas e texto):

| Modelo        | Arquivo | Bateria (caminho MCP) | Observação |
|---------------|---------|-----------------------|------------|
| `llama3.1:8b` | 4,6 GB  | 12/18                 | Obedece a instrução escondida em arquivo; às vezes erra nome de arquivo |
| `gemma4:12b`  | 7,0 GB  | 18/18                 | Ocupa 7,8 GB na VRAM com contexto de 4096 (~8,1 GB com 32k); carrega em ~7 s a frio |
| `qwen38-27b`  | 12,2 GB | não medido            | Cabe nos 15,8 GiB, mas sobra pouco para o contexto |

O gemma4:12b foi o único sem falha, inclusive no caso de injeção (instrução escondida num
arquivo), em que o llama3.1:8b caiu nas 3 rodadas. O custo é mais VRAM (7,8 GB contra ~5 GB) e
~7 s para carregar a frio, que o `main.py` esconde aquecendo o modelo na subida.
No código, o modelo oficial fica em `OFFICIAL_MODEL` (`agent/ollama_client.py`): o `main.py` o marca
como "(oficial)" e o escolhe com Enter, e a bateria o usa como padrão.

---

## Como rodar

Tudo no terminal do WSL, na raiz do projeto (`/mnt/c/Users/plepl/Downloads/01-Trabalho/LLMs`).

```bash
# 1. Ambiente Python (uma vez). Fica no disco Linux: em /mnt/c, o protocolo 9P deixa
#    os imports do SDK do MCP ~5x mais lentos (4,3 s contra 0,85 s).
python3 -m venv ~/.venvs/llm-local
~/.venvs/llm-local/bin/pip install -r requirements.txt

# 2. Ollama (o WSL desliga a VM quando o último terminal fecha, e o container cai junto)
docker start ollama

# 3. Agente
~/.venvs/llm-local/bin/python agent/main.py

# Bateria do prompt (um modelo por vez na GPU)
~/.venvs/llm-local/bin/python evals/prompt_traps.py gemma4:12b 3
```

O código está versionado em https://github.com/pedro470/llm-local-agent (privado).

---

## Decisões de design

### Tamanho do modelo
- O limite é o tamanho em GB, não o número de parâmetros: arquivo do modelo + KV cache precisam
  caber nos ~14,7 GiB livres da 9070 XT. Se não couberem, parte das camadas vai para a RAM e a
  velocidade despenca.
- Medido na Fase 3: llama3.1:8b a 84,45 tokens/s de geração, 100% na VRAM.
- O 8B foi a aposta inicial ("com bom prompting é suficiente"), mas a bateria de armadilhas mostrou
  limites dele em segurança e fidelidade; o oficial passou a ser o gemma4:12b (ver acima).

### Por que quantização Q4_K_M?
- Ocupa ~4.9GB (vs ~16GB em FP16)
- Perda de qualidade mínima para tarefas de tool-use
- Cabe 100% na VRAM com sobra para contexto

### Contexto e VRAM (etapa 5, medido em 28/10/2026)
- O agente pede `num_ctx = 32768` (`NUM_CTX` em `agent/ollama_client.py`, trocar com `AGENT_NUM_CTX`).
  O padrão do Ollama é 4096, e o prompt de sistema mais o schema das 7 ferramentas já gastam 1.656.
- KV cache do gemma4:12b: ~8,5 KiB por token. Só 8 das 48 camadas têm atenção global (cache que
  cresce com o contexto); as outras 40 usam janela deslizante de 1024 tokens, com cache fixo de ~255 MiB.
  Com 32k: 7,0 GB de pesos + 272 MiB de KV global + 255 MiB de KV deslizante + ~250 MiB de buffers.
- O aquecimento usa o mesmo `num_ctx` do chat: o KV cache é alocado no carregamento, e um valor
  diferente obriga o Ollama a recarregar o modelo.
- Se o prompt passa do `num_ctx`, o Ollama descarta mensagens antigas sem avisar (2.298 tokens viraram
  1.903 com `num_ctx=2048`, sem erro). Por isso o `main.py` tem a própria janela (`trim_history`):
  corta pedidos inteiros, mais antigos primeiro, antes de cada chamada, e mantém o prompt de sistema
  e o pedido atual. Depois do corte, uma nota no prompt de sistema avisa o modelo; sem a frase
  "o primeiro pedido que você ainda vê NÃO é o primeiro", ele ignorava a nota em 4 de 5 rodadas.
- Medidor: `prompt_eval_count` do Ollama conta o prompt inteiro, mesmo o trecho que veio do cache.
  O `main.py` mostra o uso depois de cada resposta e, na subida, o que o `/api/ps` diz da VRAM.
- O raciocínio do gemma4 (campo `thinking`) não entra no histórico: o template não o reenvia.

### Por que Docker em vez de instalar tudo direto?
- Ambiente limpo, reprodutível, descartável
- Se quebrar, destrói o container e recria — sem sujar o sistema
- Separa o "mundo Linux + ROCm" do seu Windows

### Por que Ollama e não PyTorch direto?
- Ollama abstrai toda a complexidade de carregar modelos GGUF
- API REST simples para o agente se conectar
- Gerencia modelos (download, remoção, atualização) com um único comando
- PyTorch seria necessário se você fosse TREINAR; para INFERÊNCIA, é overkill

### Por que o agente é cliente de um servidor MCP
- Uma implementação só das ferramentas (o antigo `tools.py` duplicava o servidor e divergia dele)
- O servidor valida os argumentos pelo schema: tipo errado vindo do modelo é convertido ou recusado
- Qualquer outro cliente MCP pode usar as mesmas ferramentas com as mesmas travas

### Por que a confirmação humana é por elicitation, e não por /dev/tty
- O SDK cria o servidor com `start_new_session=True`: o processo filho não tem terminal de
  controle, então `open("/dev/tty")` falha sempre e toda ação ficava bloqueada, mesmo com "s"
- A elicitation é o mecanismo do próprio protocolo: o servidor pede, o cliente pergunta ao humano
- Fail-closed: cliente sem elicitation, recusa, cancelamento ou erro bloqueiam a ação

### Por que uma cerca além da confirmação humana
- A confirmação só existe em `delete_file` e `run_command`; mover e copiar não perguntam
- O llama3.1:8b obedece a instruções escondidas em arquivos (teste de injeção da bateria): o prompt
  não protege, a cerca sim
- `guard.py` resolve cada caminho (segue symlinks, elimina `..`) e exige que caia numa raiz
  permitida; `run_command` aceita 18 programas de leitura, executados sem shell
- A recusa vem antes da pergunta: quando o (s/n) aparece, a ação já é permitida

### Por que o ambiente Python fica fora do projeto
- `/mnt/c` é o NTFS do Windows exposto por 9P: cada abertura de arquivo atravessa a VM
- O SDK do MCP abre centenas de arquivos no import: 4,3 s em `/mnt/c` contra 0,85 s no disco Linux
- O `requirements.txt` recria o ambiente idêntico em segundos (`pip freeze` conferido)

---

## Mapa Mental de Baixo Nível: Paravirtualização, Paths e Binds

Consulte esta matriz para relacionar o conceito de sistemas com o caminho exato do arquivo:

| Camada / Função | Origem no Host (WSL2) | Quem colocou lá? | Mapeamento no Docker | Por que precisa disso? |
|---|---|---|---|---|
| **Canal de Kernel (I/O)** | `/dev/dxg` | Kernel WSL2 (VMBus) | `--device=/dev/dxg` | Abre permissão no cgroup para o container falar com a Root Partition (Windows) |
| **API DXCore (Microsoft)** | `/usr/lib/wsl/lib/libdxcore.so` | Windows Host (`System32\lxss\lib`) | `-v ...:/usr/lib/libdxcore.so` | Biblioteca de usuário da MS que empacota chamadas para o `/dev/dxg` |
| **Ponte AMD ROCDXG** | `/opt/rocm/lib/librocdxg.so` | Pacote AMD (`rocdxg-roct.deb`) | `-v ...:/usr/lib/librocdxg.so` | Intercepta chamadas ROCm e traduz para chamadas da `libdxcore.so` |
| **Ponte AMD (RPATH fixo)** | `/opt/rocm/lib/librocdxg.so` | Pacote AMD (`rocdxg-roct.deb`) | `-v ...:/opt/rocm/lib/librocdxg.so` | Atende binários compilados com busca de runtime restrita a `/opt/rocm/lib` |
| **Flag de Hardware** | `HSA_ENABLE_DXG_DETECTION=1` | Usuário / Ambiente | `-e HSA_ENABLE_DXG_DETECTION=1` | Força o ROCm a inicializar o backend DXG em vez de falhar procurando `/dev/kfd` |
| **Persistência de Tensores**| Volume Docker (`ollama_data`) | Docker Engine no WSL2 | `-v nome_vol:/root/.ollama` | Grava modelos no disco real do WSL2, evitando perda ao destruir o container |

---

## Estratégia de Investigação (Como encontrar os paths sozinho)

Se você esquecer de onde veio um arquivo ou onde ele deve ser montado, não copie e cole da internet. Use as ferramentas do próprio Linux para rastrear:

### 1. Rastrear arquivos instalados por um pacote
**Comando:** `dpkg -L <nome_do_pacote>` (ex: `dpkg -L rocdxg-roct`)
- **`dpkg`**: O gerenciador de pacotes de baixo nível do Debian/Ubuntu (o `apt` usa ele por baixo dos panos).
- **`-L` (List)**: Lista todos os caminhos físicos (arquivos e pastas) que aquele pacote extraiu no seu disco. Use isso logo após instalar um `.deb` para ver exatamente onde a biblioteca caiu (ex: descobrindo o `/opt/rocm/lib/librocdxg.so`).

### 2. Encontrar bibliotecas do cache do sistema
**Comando:** `ldconfig -p | grep <nome>` (ex: `ldconfig -p | grep dxcore`)
- **`ldconfig`**: Utilitário que constrói e lê o cache do Dynamic Linker (`ld.so`), mapeando onde estão as bibliotecas compartilhadas (`.so`) no sistema.
- **`-p` (Print cache)**: Pede para imprimir a lista atual de todas as bibliotecas que o Linux sabe encontrar automaticamente (geralmente lendo de `/etc/ld.so.conf.d/`).
- **`\| grep`**: Filtra a saída. Útil para rastrear as bibliotecas injetadas pelo Windows (como a `libdxcore.so`), que o pacote `dpkg` não gerencia.

### 3. Abrir o capô de um executável para ver o que ele procura
**Comando:** `readelf -d /caminho/do/binario | grep -E "NEEDED|RPATH"` (ex: lendo o binário do `ollama` ou `llama-server`)
- **`readelf`**: Ferramenta que lê os metadados de arquivos binários padrão do Linux (formato ELF).
- **`-d` (Dynamic)**: Exibe as seções do cabeçalho relativas à linkagem dinâmica (tudo que o programa precisa carregar em tempo de execução para não dar "Segmentation Fault" ou "cannot open shared object file").
- **`NEEDED`**: Lista o nome exato das bibliotecas `.so` que o binário quer.
- **`RPATH / RUNPATH`**: Mostra se quem compilou o programa "cravou" no código um diretório absoluto (ex: `/opt/rocm/lib`) onde o sistema deve procurar as dependências antes de olhar os diretórios padrão. É por isso que montamos volumes no Docker espelhando essa estrutura exata.

---

## Estimativa de armazenamento

| Item                                  | Tamanho aprox. |
|---------------------------------------|---------------|
| Imagem base Ubuntu (WSL2)             | ~2 GB         |
| Docker Engine + overhead              | ~3 GB         |
| Imagem Docker com ROCm + Ollama       | ~15-25 GB     |
| Modelos baixados hoje (4, no volume `ollama_data`) | ~30 GB |
| Python + dependências do agente       | ~0,1 GB       |
| **Total estimado**                    | **~50-60 GB** |

> Os modelos são o que mais cresce: o volume tem llama3.1:8b (4,6 GB), gemma4:12b (7,0 GB),
> qwen38-27b (12,2 GB) e uma variante do gemma (6,5 GB). Com o gemma4:12b como oficial,
> `docker exec ollama ollama rm <modelo>` libera os outros, se não forem mais usados para comparação.

---

## Modo de Trabalho e Regras

1. **Pair Programming Ativo**: O agente executa a implementação prática de código, configurações e testes, detalhando cada etapa.
2. **Arquitetura e Fundamentos**: O usuário direciona o projeto, valida as entregas e domina a arquitetura através de explicações transparentes de cada componente.
3. **Commits frequentes**: Manter configurações e código versionados.
4. **Sem atalhos conceituais**: Cada fase mantém seu checkpoint validado para garantir que a pilha está íntegra antes de avançar.

---

## Referências obrigatórias

Antes de começar, você vai **ler** (não apenas abrir) estas páginas:

- [O que é Docker? (docs oficiais)](https://docs.docker.com/get-started/docker-overview/)
- [O que é WSL2? (Microsoft)](https://learn.microsoft.com/pt-br/windows/wsl/about)
- [O que é ROCm? (AMD)](https://rocm.docs.amd.com/en/latest/about/what-is-rocm.html)
- [Ollama — GitHub](https://github.com/ollama/ollama)
- [ROCm 10.0.0 — Matriz de compatibilidade](https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html)
