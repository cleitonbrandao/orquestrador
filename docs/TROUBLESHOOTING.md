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
"FROM qwen3:8b`nPARAMETER num_ctx 12288" | Out-File -Encoding ascii "$env:TEMP\Modelfile"
ollama create qwen3-12k -f "$env:TEMP\Modelfile"
```

```bash
printf 'FROM qwen3:8b\nPARAMETER num_ctx 12288\n' > /tmp/Modelfile
ollama create qwen3-12k -f /tmp/Modelfile
```

Depois aponte `agents.local-helper.model` e `agents.exec-docs.model` para
`ollama/qwen3-12k:latest`.

**Conferir:**
```powershell
ollama show qwen3-12k --modelfile | Select-String num_ctx   # PARAMETER num_ctx 12288
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
opencode run --agent local-helper --model ollama/qwen3-12k:latest "leia README.md"
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
"model": "{env:LOCAL_HELPER_MODEL:-ollama/qwen3-12k:latest}"
```
Isso faz o agente desaparecer.

---

## Modelo local "descreve" o comando mas não executa

**Sintoma:** o subagente responde com um JSON bonito de tool call em texto, ou diz "vou
executar" e nada acontece.

**Causa:** o modelo não emite `tool_calls` nativas. `qwen2.5-coder:7b` no Ollama tem esse
comportamento (retorna `tool_calls: null`).

**Solução:** usar um modelo com suporte a ferramentas — aqui, `qwen3:8b` / `qwen3-12k`.

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

Com 2 slots o KV cache dobra: 2 × 16k = 8,1 GB, que já vaza 10% para a CPU numa GPU de
8 GB (ver ARQUITETURA, Decisão 11).

**Solução, em ordem:**
1. Reduzir o contexto do derivado: `.\install.ps1 -Context 8192` cria o `qwen3-8k`
   (ajuste `agents.<id>.model` no JSON para o novo nome).
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

---

## Variáveis `OLLAMA_*` gravadas, mas o Ollama continua com 1 slot

**Sintoma:** `verify.ps1` mostra `OLLAMA_NUM_PARALLEL=2`, mas as tarefas locais rodam uma
de cada vez. O `server.log` mostra `OLLAMA_NUM_PARALLEL:1`.

**Causa:** o `ollama app.exe` herda o ambiente de quem o iniciou. Reabrir pelo terminal
antigo (ou por um processo aberto antes da gravação) traz o ambiente velho.

**Diagnóstico:**
```powershell
Select-String "$env:LOCALAPPDATA\Ollama\server.log" -Pattern "OLLAMA_NUM_PARALLEL" | Select-Object -Last 1
```

**Solução:** feche o Ollama na bandeja e abra pelo menu Iniciar (ou faça logoff/logon).
No Linux, as variáveis vão no serviço (`sudo systemctl edit ollama`) e não no shell.

**Conferir:** com duas requisições ao mesmo tempo, o log mostra `n_slots = 2` e
`ollama ps` mostra `100% GPU`.

---

## Dois slots vazando para a CPU

**Sintoma:** `ollama ps` mostra `10%/90% CPU/GPU` e os agentes locais ficam ~1/3 mais
lentos.

**Causa:** contexto por slot grande demais para a VRAM, ou `OLLAMA_KV_CACHE_TYPE=q8_0`
sem `OLLAMA_FLASH_ATTENTION=1` (a quantização do KV exige flash attention).

**Solução:** usar o `qwen3-12k` (padrão) e conferir as duas variáveis. Medições na
ARQUITETURA, Decisão 11.

---

## `opencode` resolve para a versão 1.x

**Sintoma:** `opencode --version` mostra `1.1.53`, `opencode debug agents` dá erro, e o
`verify.ps1`/`verify.sh` não acha os agentes (`JSON inválido` / `saída não contém JSON`).

**Causa:** um OpenCode antigo instalado pelo Chocolatey (`C:\ProgramData\chocolatey\bin`)
vem antes do npm (`%APPDATA%\npm`, onde está a v2.1.3) no PATH, tanto no PowerShell
quanto no Git Bash.

**Diagnóstico:**
```powershell
Get-Command opencode -All | Select-Object Source, Version
```

**Solução:** desinstalar o pacote do Chocolatey (`choco uninstall opencode`) ou colocar
`%APPDATA%\npm` antes dele no PATH. Para uma sessão só:
```powershell
$env:Path = "$env:APPDATA\npm;" + $env:Path
```
```bash
export PATH="$(cygpath -u "$APPDATA")/npm:$PATH"   # Git Bash
```

---

## `debug agents` mostra só parte dos agentes logo depois do restart

**Sintoma:** logo depois de `opencode service restart`, aparecem só os agentes nativos
(`build`, `plan`, `general`…) e os do config faltam. Segundos depois aparecem todos.

**Causa:** o serviço ainda está recarregando a configuração.

**Solução:** esperar alguns segundos. O `verify.ps1` já tenta 3 vezes até o
`decompositor` aparecer.

---

## Executor não consegue rodar o teste

**Sintoma:** o executor responde `RESULTADO: bloqueado` dizendo que a ferramenta
`run_tests` não existe ou recusou o comando.

**Causa e solução:**
- ferramenta ausente → o MCP `run_tests` não subiu: confira `mcp.run_tests` no
  `opencode.json` e se `orq-run-tests` está no PATH (`.erify.ps1` → `Servidor MCP run_tests`);
- `comando fora da allowlist` → o `comando_teste` do plano não é um comando de teste
  conhecido; estenda com `ORQ_TESTS_ALLOW="regex;;regex"` ou corrija o comando;
- `metacaracteres de shell` → o comando tem `;`, `&`, `|`, `>` ou `$()`: o `run_tests`
  roda sem shell e recusa encadeamento.

Os executores não têm `bash` nem subagente: o teste passa só pelo `run_tests`
(`.erify.ps1` → `executor: subagente negado (testes pelo run_tests)`).

---

## Verificador de docs rejeitado no `opencode run`

**Sintoma:** `permission requested: shell (...); auto-rejecting` ao rodar o
`verificar_docs.py` num `opencode run` sem `--auto`.

**Causa:** no modo não interativo, `bash: ask` vira rejeição automática.

**Solução:** o `orquestrador` tem `python *verificar_docs.py*` e
`python3 *verificar_docs.py*` em `allow` no `opencode.json`; para outro comando, use
`opencode run --auto`.

---

## `redigir_docs.py` responde `RESULTADO: indisponivel`

**Sintoma:** sai com código 3, e a rota docs cai no `exec-docs`.

**Causa e solução, conforme o `MOTIVOS`:**
- `Ollama fora do ar` → abra o Ollama (bandeja no Windows, `systemctl start ollama` no Linux)
  ou aponte `ORQ_OLLAMA_URL`;
- `modelo ... não está no Ollama` → `.\install.ps1` cria o `qwen3-12k`, ou use outro com
  `ORQ_MODELO_DOCS` (ex.: `qwen3.5:4b`);
- `texto atual grande demais` → passe `--secao '<título exato>'`: só aquela seção vai
  para o modelo.

Com `RESULTADO: falhou`, o modelo respondeu, mas o `verificar_docs.py` recusou nas 3
tentativas. Os `MOTIVOS` vão como `EVIDENCIA` para o `exec-docs`.

---

## `python3` no Git Bash não roda nada (Windows)

**Sintoma:** `python3 --version` imprime `Python não foi encontrado; executar sem
argumentos para instalar do Microsoft Store...`.

**Causa:** `%LOCALAPPDATA%\Microsoft\WindowsApps\python3.exe` é um atalho da Microsoft
Store e vem antes do Python real no PATH.

**Solução:** no Windows, use `python`. O `install.sh` e o `verify.sh` testam `python3` e
`python` e ficam com o primeiro que responde `Python 3`. Para tirar o atalho:
Configurações → Aplicativos → Configurações avançadas → Aliases de execução do aplicativo.

---

## `bash` chamado de fora do Git Bash abre o WSL (Windows)

**Sintoma:** chamar o `verificar.sh` de um programa Windows (Python `subprocess`, `cmd`)
com `bash` devolve saída vazia, ou um `git` de outra versão (`git version 2.34.1` do
Ubuntu).

**Causa:** `C:\Windows\System32\bash.exe` é o bash do WSL e vem primeiro na busca do
Windows; ele não abre caminhos `C:\...`.

**Solução:** use o caminho completo do Git Bash (`C:\Program Files\Git\usr\bin\bash.exe`;
`shutil.which("bash")` acha esse) ou, no PowerShell, o `verificar.ps1`. Dentro do Claude
Code não acontece: a ferramenta Bash já é o Git Bash.
