# LLM Local — Agente de Controle de Arquivos e Automação

## O que é este projeto

Um **agente LLM local** rodando na sua máquina que:

1. **Controla e move arquivos** — renomeia, organiza pastas, limpa lixo
2. **Executa rotinas** — sequências pré-definidas de organização e manutenção
3. **Faz troubleshooting** — segue checklists para diagnosticar e resolver problemas
4. **Opera 100% offline** — nenhum dado sai da sua máquina

---

## Arquitetura (visão geral)

```
┌─────────────────────────────────────────────────┐
│  WINDOWS 11                                     │
│                                                  │
│  ┌─────────────────────────────────────────────┐ │
│  │  WSL2 (Ubuntu)                              │ │
│  │                                              │ │
│  │  ┌───────────────────────────────────────┐   │ │
│  │  │  Docker Container                     │   │ │
│  │  │                                        │   │ │
│  │  │  ┌────────────┐   ┌────────────────┐  │   │ │
│  │  │  │  ROCm      │   │   Ollama       │  │   │ │
│  │  │  │  (driver   │──▶│   (servidor    │  │   │ │
│  │  │  │   GPU AMD) │   │    do modelo)  │  │   │ │
│  │  │  └────────────┘   └───────┬────────┘  │   │ │
│  │  │                           │ API :11434 │   │ │
│  │  └───────────────────────────┼────────────┘   │ │
│  │                              │                │ │
│  └──────────────────────────────┼────────────────┘ │
│                                 │                  │
│  ┌──────────────────────────────▼────────────────┐ │
│  │  Python Agent + MCP Servers                   │ │
│  │  (roda no Windows ou no WSL, chama a API      │ │
│  │   do Ollama e executa ferramentas locais)     │ │
│  └───────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

---

## Stack tecnológica

| Camada          | Tecnologia                     | Função                                      |
|-----------------|--------------------------------|----------------------------------------------|
| **GPU**         | AMD RX 9070 XT (`gfx1201`)    | Aceleração da inferência do modelo           |
| **Driver GPU**  | ROCm 10.x                     | Interface entre o SO Linux e a GPU AMD       |
| **Container**   | Docker no WSL2 (Ubuntu)        | Isola o ambiente Linux com ROCm + Ollama     |
| **Servidor LLM**| Ollama                        | Serve o modelo, expõe API REST na porta 11434|
| **Modelo**      | Llama 3.1 8B Instruct (Q4_K_M)| LLM com function-calling nativo, ~4.9GB      |
| **Agente**      | Python + MCP Tools             | Orquestra o modelo e executa ações no PC     |

---

## Decisões de design

### Por que 8B e não maior?
- 16GB de VRAM da 9070 XT comporta 8B quantizado inteiro na GPU
- Resposta rápida (~20-40 tokens/s)
- Para mover arquivos e seguir rotinas, 8B com bom prompting é suficiente
- Modelos maiores (13B+) exigiriam offload para RAM e ficariam lentos

### Por que quantização Q4_K_M?
- Ocupa ~4.9GB (vs ~16GB em FP16)
- Perda de qualidade mínima para tarefas de tool-use
- Cabe 100% na VRAM com sobra para contexto

### Por que Docker em vez de instalar tudo direto?
- Ambiente limpo, reprodutível, descartável
- Se quebrar, destrói o container e recria — sem sujar o sistema
- Separa o "mundo Linux + ROCm" do seu Windows

### Por que Ollama e não PyTorch direto?
- Ollama abstrai toda a complexidade de carregar modelos GGUF
- API REST simples para o agente se conectar
- Gerencia modelos (download, remoção, atualização) com um único comando
- PyTorch seria necessário se você fosse TREINAR; para INFERÊNCIA, é overkill

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
| Modelo Llama 3.1 8B Q4_K_M            | ~4.9 GB       |
| Python + dependências do agente       | ~2 GB         |
| **Total estimado**                    | **~30-40 GB** |

> Sobram **160-170GB** livres dos seus 200GB. Margem confortável.

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
