# Troubleshooting

Cada item abaixo foi **observado na prática** durante a montagem deste setup
(OpenCode v2.1.3 + Ollama 0.40.9). Comandos mostrados em PowerShell; a versão bash é o
equivalente direto.

---

## Contexto sempre 4096 (`num_ctx` ignorado)

**Sintoma:** o agente local esquece o começo da conversa, corta arquivos no meio, ou
responde "não recebi o conteúdo completo". `ollama ps` mostra `CONTEXT 4096`.

**Causa:** o OpenCode não envia `num_ctx` por requisição, e `options`/`body` no bloco do
provider Ollama são ignorados nesse caminho.

**Solução:** criar um modelo derivado com o parâmetro embutido.

```powershell
"FROM qwen3:8b`nPARAMETER num_ctx 16384" | Out-File -Encoding ascii "$env:TEMP\Modelfile"
ollama create qwen3-16k -f "$env:TEMP\Modelfile"
```

```bash
printf 'FROM qwen3:8b\nPARAMETER num_ctx 16384\n' > /tmp/Modelfile
ollama create qwen3-16k -f /tmp/Modelfile
```

Depois aponte `agents.local-helper.model` para
`ollama/qwen3-16k:latest`.

**Conferir:**
```powershell
ollama show qwen3-16k --modelfile | Select-String num_ctx   # PARAMETER num_ctx 16384
```

---

## Sessão nova cai em modelo pago / config antiga "volta"

**Sintoma:** você remove o `model` do `opencode.json`, reinicia, e o modelo pago continua
aparecendo. A config no disco está certa.

**Causa:** a variável de ambiente `OPENCODE_CONFIG_CONTENT` contém um snapshot da config
antiga (com `model` fixo e, no nosso caso, o provider Ollama em `/v1`). O OpenCode a
propaga para processos filhos — inclusive para o script que reinicia o serviço. Cada
restart feito de um shell contaminado **regera** a variável no serviço novo.

**Diagnóstico:**
```powershell
$env:OPENCODE_CONFIG_CONTENT.Length
($env:OPENCODE_CONFIG_CONTENT | ConvertFrom-Json).model
```

**Solução:** reiniciar o serviço a partir de um processo **sem** a variável:

```powershell
Remove-Item Env:OPENCODE_CONFIG_CONTENT -ErrorAction SilentlyContinue
opencode service restart
```

No Linux/macOS:
```bash
unset OPENCODE_CONFIG_CONTENT
opencode service restart
```

**Verificação:** abra um processo novo e confirme que a variável está vazia e que o modelo
default é o esperado.
```powershell
opencode run --standalone "Responda: OK"
```

---

## `opencode run --agent X` usa o modelo errado

**Sintoma:** você chama um agente que tem `model` definido no JSON e o run usa outro
modelo (na v2.1.3, caía em um modelo de nuvem).

**Causa:** limitação da v2.1.3: `--agent` não aplica o `model` do agente em `run`.

**Solução:** passar o modelo explicitamente.
```powershell
opencode run --agent local-helper --model ollama/qwen3-16k:latest "leia README.md"
```

---

## Agente desaparece da lista

**Sintoma:** o agente existia, você editou o `model`, e ele sumiu de
`opencode debug agents`. Nenhum erro no terminal.

**Causa:** string de modelo inválida ou não resolvível. O OpenCode descarta o agente
silenciosamente. Aconteceu com `{env:VAR:-default}` no campo `model` — substituição de
ambiente **não** funciona ali.

**Solução:** usar valor literal `provider/modelo`. Depois de qualquer edição de modelo,
sempre reconferir:
```powershell
opencode debug agents
```

**Não use:**
```json
"model": "{env:LOCAL_HELPER_MODEL:-ollama/qwen3-16k:latest}"
```
Isso faz o agente desaparecer.

---

## Modelo local "descreve" o comando mas não executa

**Sintoma:** o subagente responde com um JSON bonito de tool call em texto, ou diz "vou
executar" e nada acontece.

**Causa:** o modelo não emite `tool_calls` nativas. `qwen2.5-coder:7b` no Ollama tem esse
comportamento (retorna `tool_calls: null`).

**Solução:** usar um modelo com suporte a ferramentas — aqui, `qwen3:8b` / `qwen3-16k`.

**Teste rápido na API do Ollama:**
```bash
curl -s http://127.0.0.1:11434/api/chat -d '{"model":"qwen3:8b","stream":false,"messages":[{"role":"user","content":"liste arquivos"}],"tools":[{"type":"function","function":{"name":"shell","description":"roda comando","parameters":{"type":"object","properties":{"cmd":{"type":"string"}}}}}]}' | grep -o '"tool_calls":\[[^]]*\]'
```

Se vier `"tool_calls":null`, o modelo não serve para agente.

---

## `shell: ask` em subagente não pede permissão

**Sintoma:** você configurou `ask` e espera um prompt; o comando executa direto.

**Causa:** em subagente não há superfície de prompt. O log mostra a execução sem nenhum
registro de pedido de permissão.

**Solução:** usar `deny` para o que não pode rodar. `ask` só faz sentido no agente
`primary`.
```json
{ "action": "shell", "resource": "composer *", "effect": "deny" }
```

---

## Permissões configuradas não têm efeito

**Sintoma:** o agente está na lista, mas `edit` e `shell` funcionam livremente.

**Causa 1:** bloco `agent` (V1) em vez de `agents` (V2) — o array de permissões é
descartado sem aviso.
**Causa 2:** ordem das regras. O último match vence; um `*: allow` no fim anula tudo.

**Conferir as permissões efetivas:**
```powershell
opencode debug agents | Select-String -Pattern '"action"|"resource"|"effect"'
```

---

## Erro de permissão em arquivo fora do projeto

**Sintoma:** `read` de um caminho absoluto fora do repositório falha.

**Causa:** `external_directory` é `deny` nos subagentes — proposital.

**Solução:** o orquestrador lê o arquivo e passa o conteúdo no prompt da delegação. Não
afrouxe essa regra: ela evita que um modelo local saia varrendo o disco.

---

## VRAM insuficiente / modelo lento

**Sintomas:** `ollama ps` mostra `PROCESSOR: 100% CPU`, ou o turno passa de 3 minutos.

**Causa:** contexto grande demais para a GPU, ou modelo grande demais.

**Solução, em ordem:**
1. Reduzir o contexto do derivado: `PARAMETER num_ctx 8192` (recria o modelo).
2. Trocar a base: `FROM qwen3:4b` com `num_ctx 8192`.
3. Fechar aplicações que usam VRAM (navegador, jogos, outros modelos no Ollama).

Verificar o consumo real:
```powershell
ollama ps
```

---

## Modelo exige MLX (LFM3 no Windows/Linux)

**Sintoma:** `ollama pull lfm3-audio` (ou `lfm3-omni`, `lfm3`, `lfm3-vl`, `d1:2b`) termina
com:

```
Error: this model requires MLX support, but the MLX runtime is not available
```

**Causa:** esses modelos são publicados em `nvfp4` (4 bits) e só são servidos pelo runtime
MLX. O Ollama 0.40.12 o habilita apenas em Apple Silicon — as notas da release dizem
"supported on Apple hardware in this release. Support for Linux/Windows coming soon".

**Não é** falta de RAM, VRAM ou driver. Conferir o formato sem baixar:

```bash
curl -s https://registry.ollama.ai/v2/library/lfm3-audio/manifests/2b \
  -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
  | python -c "import json,sys; print(json.load(sys.stdin)['layers'][0]['mediaType'])"
```

**Solução:** esperar o suporte a Linux/Windows, ou rodar numa máquina Apple. Não tente
requantizar: o checkpoint público é nvfp4 e não há tag `q4_K_M`/`q8_0` no registry.
Enquanto isso, `scripts/bench-omni.ps1 lfm3-omni` sai com código 3 e explica, em vez de
medir nada. Ver [`BENCH-OMNI.md`](BENCH-OMNI.md).

---

## Orquestrador não consegue ler arquivo PHP ou SQL

**Sintoma:** o agente principal diz que não pode abrir um controller ou um arquivo de migration
PHP, ou pede para delegar mesmo quando você quer que ele leia.

**Causa:** é proposital. `read` de `*.php` e `*.sql` está negado no `orquestrador` para manter
o código fora do contexto pago — leitura vai para `local-helper`/`local-mini`, e a conferência
do que um executor mudou é feita por `git diff` e `run_tests`.

**Solução, se precisar reverter:** remova as duas entradas do `orquestrador` em
`opencode.json` e reinicie o OpenCode:

```json
{ "action": "read", "resource": "*.php", "effect": "deny" },
{ "action": "read", "resource": "*.sql", "effect": "deny" }
```

Alternativas que não abrem o arquivo inteiro: `grep` pelo símbolo (saída curta), `git diff`
para o que mudou, ou delegar ao `local-helper` com a pergunta específica.

---

## Google: "API key not valid" ou "Connect Google with Antigravity OAuth"

**Sintoma:** escolher um modelo `google/*` falha.

**Causa:** são dois caminhos de autenticação diferentes.
- API key expirada/revogada → `API key not valid`;
- modelos `antigravity-*` exigem OAuth do Antigravity → mensagem pedindo para conectar.

**Solução:** dentro do OpenCode, rodar `/auth` e reconectar. Se você não usa Google,
apague o bloco `provider.google` e o plugin `opencode-antigravity-auth` do config — nada
mais depende deles.

---

## Config não recarrega

**Causa:** não há hot-reload completo.

**Solução:**
```powershell
opencode service restart
```
Confirme antes que `OPENCODE_CONFIG_CONTENT` está vazia (ver item acima), senão o restart
reintroduz o snapshot antigo.

---

## Instalador sobrescreveu minha config

O instalador **sempre** faz backup antes: `opencode.json.bak.<timestamp>` no mesmo
diretório. Para recuperar:

```powershell
Copy-Item "$env:USERPROFILE\.config\opencode\opencode.json.bak.20261023-120000" "$env:USERPROFILE\.config\opencode\opencode.json" -Force
```

Se você tem providers/agentes próprios, faça merge manual em vez de copiar por cima.

---

## Subagente local falha com `Nothing to compact yet`

**Sintoma:** o subagente local (decompositor, local-helper, exec-local…) morre com
`Subagent failed` e o erro `Session.StepFailedError: Nothing to compact yet`. No histórico,
a mensagem do assistente fica vazia (`content: []`, sem `tokens`) e a sessão termina com
`compaction.unavailable`.

**Causa:** o OpenCode (V2) chama a auto-compactação **a cada passo** do runner
(`SessionRunner.runStep`). Se a compactação falhar, o passo é abortado — não é "skip".
Ela falha quando não sobra nenhuma mensagem com texto para resumir, o que acontece depois
de uma primeira compactação que engoliu a conversa inteira.

Isso é inevitável em modelos de contexto pequeno, porque o `keep` interno é **fixo em
15.000 tokens** e o limiar é calculado assim:

```text
limiar = contexto - max(15% do contexto, 16000 se contexto >= 32000)
```

| contexto | limiar | `keep` | resultado |
|---|---|---|---|
| 8.192 | 6.963 | 15.000 | compactação sempre degenerada |
| 16.384 | 13.927 | 15.000 | compactação sempre degenerada |
| 32.768 | 16.768 | 15.000 | funciona |
| 65.536 | 49.536 | 15.000 | folgado |

Ou seja: **agente local precisa de contexto ≥ 32k**. Com 16k o limiar fica abaixo do `keep`
e toda compactação resume tudo, deixando a sessão sem texto para a etapa seguinte.

Agravante medido nesta máquina: o estimador de tokens do OpenCode superestima ~33% sobre
o real (prompt de 10.481 tokens reais disparou um limiar de 13.927).

**Solução:** derivar os modelos locais com `num_ctx 32768` e apontar os agentes para eles.

```bash
printf 'FROM qwen3.5:2b\nPARAMETER num_ctx 32768\n' > /tmp/Modelfile
ollama create qwen3.5-2b-32k -f /tmp/Modelfile
printf 'FROM gemma4:e2b\nPARAMETER num_ctx 32768\n' > /tmp/Modelfile
ollama create gemma4-e2b-32k -f /tmp/Modelfile
```

No `opencode.json`, o limite precisa casar com o Modelfile:

```json
"qwen3.5-2b-32k:latest": {
  "limit": { "context": 32768, "output": 4096 }
}
```

Confirme com `ollama ps` (`CONTEXT 32768`) e valide que o modelo emite `tool_calls` nativos
— modelo que devolve a chamada como texto não executa ferramenta nenhuma.

Benchmark desta máquina (CPU, prompt real de ~8.100 tokens):

| modelo | leitura | geração | parede | caminhos válidos no plano |
|---|---:|---:|---:|---|
| `qwen3.5-2b-32k` | 17,3 tok/s | 5,5 tok/s | 594 s | 8/8 |
| `gemma4-e2b-32k` | 19,1 tok/s | 6,3 tok/s | 581 s | 7/11 |
| `qwen3.5-4b-32k` | 17,0 tok/s | 3,1 tok/s | 694 s | 5/9 |

O 4B é mais lento **e** menos preciso que o 2B nesta tarefa.

**Limite conhecido (2026-10-31):** 32k reduz, mas **não elimina** o problema. Sessão
`ses_e700bf37affe…` (`local-helper` + `gemma4-e2b-32k`) fez compactação com sucesso
(resumiu ~9 k tokens), recebeu resposta vazia do modelo e morreu no passo seguinte
com o mesmo erro. O gatilho é o **estimador** (superestima ~33%) cruzar o limiar
enquanto o conteúdo real ainda cabe no `keep` de 15.000 — aí a compactação resume
tudo e não sobra texto.

Se acontecer de novo, as saídas são, em ordem: (1) contexto 64k no agente local;
(2) reduzir a superfície de ferramentas do agente (menos schemas = base menor);
(3) repetir a delegação — é falha do turno, não do projeto.
