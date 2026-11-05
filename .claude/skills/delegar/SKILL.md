---
name: delegar
description: Delega a execução de uma tarefa de código ao modelo local (Qwen 3.8 27B via OpenCode + llama-server) para poupar tokens de saída do Opus. O Opus escreve a especificação e revisa o diff; o modelo local escreve o código. Use quando o usuário disser /delegar, "delega isso", "manda pro local", ou quando uma tarefa for mecânica, bem especificada e verificável por um comando.
---

# /delegar — o Opus planeja, o modelo local executa

O Opus (você) escreve uma especificação fechada. `tools/delegar.py` entrega essa especificação ao
agente `delegado` do OpenCode (`opencode.json` na raiz do repositório), que roda no llama-server local.
O script roda a verificação por conta própria e devolve um relatório curto. Você revisa e aprova,
ou devolve para uma volta de correção.

## 1. Vale delegar? (decida antes de escrever qualquer coisa)

Delegue só se as três condições valem:
- **Mecânica:** o "como" já está decidido. Exemplos: código repetitivo, função pura com contrato
  claro, testes a partir de um contrato, migração em lote, refatoração por padrão.
- **Especificável em menos de ~60 linhas** de especificação. Se a especificação vai sair do tamanho
  do código, escreva o código você mesmo.
- **Verificável por um comando** (teste, lint, script) que roda em segundos.

NÃO delegue: `agent/guard.py`, segurança, concorrência, prompt de sistema, decisões de arquitetura,
ou qualquer coisa em que o erro não aparece num teste. Nesses casos, escreva você.

## 2. Pré-condições

- O roteador está no ar: `curl -s http://127.0.0.1:8080/health` responde. Se não estiver, peça ao
  usuário para rodar `C:\Users\plepl\llm\start-opencode-router.cmd`. Não suba o servidor você mesmo,
  porque a porta 8080 e a VRAM são de um só (o `agent/main.py` usa as mesmas).
- Só uma delegação por vez: a GPU tem um modelo carregado de cada vez.
- O executor não vê esta conversa. Tudo o que ele precisa saber vai na especificação.

## 3. A especificação

Escreva em `logs/delegar/spec-<curto>.md` (o diretório `logs/` está fora do git). Use este molde:

```
# Tarefa: <uma linha>

## Contexto
<2 a 5 linhas: onde isso entra no projeto e por quê. Cite os arquivos que ele deve LER antes.>

## Arquivos
- criar: <caminho>
- alterar: <caminho> (só a função X)
- não tocar: <o que estiver perto e for tentador>

## Contrato
<assinaturas exatas, tipos, formato de entrada e saída, erros esperados. Seja literal.>

## Critério de pronto
<o que o teste prova; casos de borda que importam>
```

Se o teste ainda não existe e é ele que define o contrato, escreva o teste VOCÊ (é curto e é onde
mora a precisão) e delegue a implementação. É o melhor equilíbrio entre economia e controle.

## 4. Rodar

Se as ferramentas MCP do servidor `delegar` estiverem carregadas (`.mcp.json` na raiz), prefira-as:
`delegar(especificacao, pasta, verificacao)` devolve um job_id; `status(job_id, aguardar_segundos=240)`
devolve o mesmo relatório descrito abaixo. Volta de correção: `delegar(..., sessao=<ses_...>)`.
Para uma segunda opinião barata ou pesquisa (não para editar o repositório), use `antigravity(prompt)`.

Sem o MCP, pela linha de comando, em segundo plano (`run_in_background: true`), porque a execução leva minutos:

```bash
.venv/Scripts/python tools/delegar.py logs/delegar/spec-<curto>.md --verify "<comando de teste>" --title "<curto>"
```

Códigos de saída: 0 = verificação passou, 1 = verificação falhou, 2 = pré-condição (roteador ou CLI),
3 = timeout ou erro do OpenCode.

## 5. Revisar (é aqui que o Opus ganha o dinheiro)

1. Leia o relatório: status, arquivos mexidos, `--stat` e a verificação.
2. Se mexeu em arquivo fora da lista da especificação, isso já é motivo para devolver ou reverter.
3. Leia o diff dos arquivos mexidos: `git diff -- <arquivos>` (e `Read` nos arquivos novos).
   Para arquivos grandes, leia só os trechos alterados.
4. Decida:
   - **Aprovar:** está correto e a verificação passou. Siga em frente (commit só se o usuário pedir).
   - **Corrigir:** devolva uma especificação curta só com o que está errado, na mesma sessão:
     `tools/delegar.py <spec-correcao.md> --session <ses_...> --verify "<mesmo comando>"`
   - **Assumir:** depois de **2 voltas de correção** sem acerto, pare de delegar e escreva você.
     Mais voltas custam mais do que escrever.
   - **Reverter:** `git checkout -- <arquivos rastreados>` e apague os arquivos novos que ele criou.
     Confira o que vai reverter antes de reverter: o script já separa o que estava sujo antes.

## 6. Relatar ao usuário

Uma linha por delegação: tarefa, status, número de voltas, tempo, e se você aprovou, corrigiu ou
assumiu. As métricas acumuladas ficam em `logs/delegar.jsonl`.

## A cerca (o que o executor pode e não pode fazer)

Definida no agente `delegado` do `opencode.json`. A execução usa `--auto`, que aprova tudo o que
não estiver negado. Por isso as regras são de lista branca no shell:
- shell: só o Python do `.venv` e `git status/diff/log` (e `ls`/`cat`); o resto é negado;
- edição: liberada no projeto, negada em `.git`, `.claude`, `.opencode`, `opencode.json` e `.env`;
- fora da pasta do projeto, web, subagentes, skills e perguntas ao usuário: negados.

Atenção: o Python liberado ainda executa código arbitrário. A rede de segurança real é o git, mais
a sua revisão do diff. Delegue com a árvore de trabalho conhecida (o script registra o que já estava sujo).
