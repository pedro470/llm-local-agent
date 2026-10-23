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
- **WSL2**: Instalado (para Docker + ROCm)
- **Armazenamento disponível**: 200GB (negociável até 300GB)

## Stack Definida

- **ROCm 10.x** para aceleração GPU via AMD
- **Docker Engine** no WSL2 (Ubuntu) — NÃO Docker Desktop
- **Ollama** (imagem `ollama/ollama:rocm`) como servidor de modelo
- **Modelo**: Llama 3.1 8B Instruct, quantização Q4_K_M (~4.9GB)
- **Agente**: Python com MCP Tools para manipulação de arquivos e automação

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

- `README.md` — Arquitetura, stack, decisões de design, regras
- `TODO.md` — Roteiro de setup em 7 fases com checkpoints obrigatórios
- `AGENTS.md` — (este arquivo) Instruções permanentes para o agente
- `agent/` — Código Python do agente (`test_connection.py`, `tools.py`, `main.py`)
- `routines/` — (futuro) Rotinas YAML de automação
- `docker/` — (futuro) Dockerfile e docker-compose.yml

## Progresso Atual

- **FASE 0 CONCLUÍDA**: Fundamentos teóricos aprovados no Checkpoint (Virtualização, Docker, ROCm gfx1201, GGUF/Quantização, Tokenização BBPE, KV Cache e MCP).
- **FASE 1 CONCLUÍDA**: WSL2 + Docker Engine 29.8 nativo no Ubuntu 24.04 (sem Docker Desktop), permissões de socket POSIX (`/run/docker.sock`), grupo `docker` configurado e testado com sucesso via `docker run hello-world` sem `sudo`.
- **FASE 2 CONCLUÍDA**: Acesso GPU validado no Docker via paravirtualização DirectX (`/dev/dxg`), `libdxcore.so` e ponte ROCDXG (`librocdxg.so` v1.2.2). `rocminfo` reconhecendo perfeitamente CPU Ryzen 5 5500X3D e GPU AMD Radeon RX 9070 XT (`gfx1201`).
- **FASE 3 CONCLUÍDA**: Ollama no Docker com aceleração GPU (RX 9070 XT, `gfx1201`), 100% dos tensores alocados na VRAM, inferência testada a 84.45 t/s, modelo Llama 3.1 8B persistido no volume `ollama_data` e API REST HTTP operacional na porta 11434.
- **FASE 4 EM ANDAMENTO**: Ambiente Python isolado com `.venv`, `requirements.txt` gerado, conexão validada (~97 tokens/s). Implementado loop autônomo multi-step em `agent/main.py` com `tools.py` (`list_files`). Tratados desafios reais de agentes: *over-eager tool calling*, *context amnesia* (memória entre turnos) e *example poisoning*. Próxima etapa: expandir ferramentas (`read_file`, `create_folder`, `move_file`, `copy_file`, `delete_file` com HITL e `run_command`).

## Referências Rápidas

- ROCm compat matrix: https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html
- Ollama Docker ROCm: `docker pull ollama/ollama:rocm`
- GPU target: `gfx1201`
