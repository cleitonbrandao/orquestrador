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

Depois aponte `agents.local-helper.model` e `agents.qwen-testes.model` para
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
opencode run --agent qwen-testes --model ollama/qwen3-16k:latest "rode: git --version"
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
