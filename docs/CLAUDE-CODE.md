# Usando a estrutura com o Claude Code

O Claude Code consome o mesmo MCP do OpenCode. O Claude raciocina; o lado local entrega
ferramentas determinísticas (testes, busca na base de conhecimento) e triagem barata.

## O que entra

| Peça | Para quê | Onde |
|---|---|---|
| MCP `run_tests` | testes com saída condensada (falhas + resumo) e allowlist | `mcp/run_tests/server.py` → `orq-run-tests` |
| MCP `kb` | busca BM25 (+ embeddings opcionais) por aplicação | `mcp/kb/kb.py` → `orq-kb` |
| Subagente `triagem` | exploração em Haiku, somente leitura | `claude/agents/triagem.md` |
| Trecho de CLAUDE.md | instrui o uso das três peças | `claude/CLAUDE.snippet.md` |

## Instalar

```bash
./install.sh --no-model --claude
```

`--claude` (idempotente): copia o subagente para `~/.claude/agents/`, registra os dois MCP no
escopo user, adiciona `mcp__run_tests__run_tests`, `mcp__kb__search_kb` e `mcp__kb__list_apps`
em `permissions.allow` de `~/.claude/settings.json` (preservando o resto) e mantém um bloco
delimitado por `<!-- orquestrador:begin/end -->` em `~/.claude/CLAUDE.md`.

## Usar em qualquer projeto

```bash
ollama pull nomic-embed-text      # uma vez; habilita busca semântica
cd ~/Documentos/projetos/<projeto>
orq-kb index                      # app = nome da raiz git; embeddings automáticos se o modelo existir
orq-kb search "onde é feito o login no SGD"
orq-kb apps                       # arquivos, chunks e embeddings por app
orq-kb forget <app>               # apaga um índice
```

No Claude Code, `search_kb(query)` usa o projeto atual por padrão; se ele não estiver
indexado, a resposta diz como indexar. Reindexar é incremental (hash do arquivo); com
embeddings em CPU o primeiro índice é lento: medido nesta máquina (2026-10-26, sem outro modelo
competindo), um chunk de ~1,8 mil caracteres leva ~1,1 s (~55 chunks/min); com outro modelo do Ollama
em uso a mesma indexação ficou muito mais lenta. Depois só o que mudou é reindexado.
`.env*`, chaves, `vendor/`, `node_modules/`, `storage/` e arquivos > 300 KB nunca entram.
Banco: `~/.local/share/orquestrador/kb.sqlite` (`ORQ_KB_DB` para mudar). `--no-embed` força só BM25.

## Onde o embedding entra (`nomic-embed-text`)

`nomic-embed-text` é um modelo de embeddings (274 MB): não gera texto, só vetores. O `orq-kb` o usa
em dois pontos, via Ollama (`/api/embed`): ao indexar (um vetor por trecho) e a cada `search_kb`
(um vetor da pergunta). O resultado é combinado com a busca BM25, então achar o trecho certo não
depende de a pergunta repetir as palavras do documento. Sem o modelo, o `kb` cai em só BM25.

| Ferramenta | Usa o `kb` | Como |
|---|---|---|
| Claude Code | sim | MCP `kb` no escopo user + `claude/CLAUDE.snippet.md` + subagente `triagem` |
| OpenCode | sim | MCP `kb` em `opencode/opencode.json` (ferramenta `kb_search_kb`); orquestrador e `local-helper` são instruídos a consultá-la antes de ler vários arquivos |

Um app só tem busca semântica se foi indexado com o modelo presente: `orq-kb apps` mostra
"N com embedding" por app, e o `verify.sh` avisa os que estão com 0. Para completar um app antigo,
rode `orq-kb index` na raiz dele (preenche só os vetores que faltam). `scripts/testar-modelo.sh`
não testa esse modelo: ele não responde a prompts.

## Economia de tokens: o que esperar

Estimativas, **não medidas**: veja `docs/MEDICOES.md` para como medir (`/cost` no Claude Code).

- `run_tests` condensado: corta ~70–90% do resultado de uma suíte que falha.
- `triagem` (Haiku): mantém a leitura de vários arquivos fora do contexto principal.
- `kb`: troca leitura de vários arquivos por 1–5 trechos, quando o índice acerta.
- Modelos locais pequenos como subagentes **não** entram: nesta máquina (sem GPU) são lentos
  demais e os que existem não fazem tool calling de forma confiável.
