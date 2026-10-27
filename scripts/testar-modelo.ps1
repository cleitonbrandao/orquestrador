#Requires -Version 5.1
<#
.SYNOPSIS
    Testa um modelo do Ollama: mede tok/s, roda os prompts A-D de docs/PROMPT-TESTE.md, salva o
    resultado e mostra a pontuação. Equivale a scripts/testar-modelo.sh.

.PARAMETER Modelo
    Nome no Ollama (ex.: qwen3.5:4b). Se omitido, o script mostra os instalados e pergunta.
.PARAMETER Think
    Liga o thinking nos modelos que o suportam (padrão: desligado).
.PARAMETER Rapido
    Gera 300 tokens na medição de velocidade em vez de 700.
.PARAMETER Velocidade
    Mede só tok/s (rápido), sem os prompts de qualidade e sem salvar nada.
.PARAMETER Limpar
    Antes do teste, libera RAM (descarrega outros modelos; pergunta antes de parar containers e fechar
    apps) e restaura no fim.
.PARAMETER Listar
    Mostra os testes salvos com a nota e os modelos que faltam testar; não roda nenhum teste.

.EXAMPLE
    .\scripts\testar-modelo.ps1 qwen3.5:4b
    .\scripts\testar-modelo.ps1 qwen3.5:4b -Think -Rapido
    .\scripts\testar-modelo.ps1 -Listar

Ao terminar um teste completo, abre o terminal interativo (scripts\modelos.ps1).
Requisitos: Ollama em execução e Python 3 (python ou py).
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Modelo = "",
    [switch]$Think,
    [switch]$Rapido,
    [switch]$Velocidade,
    [switch]$Limpar,
    [switch]$Listar
)

$RAIZ = Split-Path $PSScriptRoot -Parent
$AVALIADOR = Join-Path $PSScriptRoot "avaliar_respostas.py"
$RELATORIO = Join-Path $PSScriptRoot "relatorio.py"
$SAIDA = if ($env:ORQ_RESULTADOS) { $env:ORQ_RESULTADOS } else { Join-Path $RAIZ "docs\resultados" }
$CSV = Join-Path $SAIDA "resultados.csv"
$inv = [Globalization.CultureInfo]::InvariantCulture
$utf8 = New-Object Text.UTF8Encoding($false)

. (Join-Path $PSScriptRoot "visual.ps1")
. (Join-Path $PSScriptRoot "limpar-ram.ps1")

function Fmt([double]$x) { return $x.ToString("0.#", $inv) }

# Situacao <modelo>: última nota e tok/s do modelo (qualquer thinking), ou "" se nunca testado.
function Situacao([string]$nome) {
    if (-not (Test-Path $CSV)) { return "" }
    $alvo = $nome -replace ':latest$', ''
    $linhas = @(Import-Csv $CSV | Where-Object { ($_.modelo -replace ':latest$', '') -eq $alvo })
    if ($linhas.Count -eq 0) { return "" }
    $u = $linhas[-1]
    return "nota $($u.nota)/100, $($u.tok_s_geracao) tok/s"
}

function Listar-Testes {
    $inst = (NomesTestaveis) -join ","
    Invoke-Py $RELATORIO lista --csv $CSV --instalados $inst
}

# Passo <n> <texto>: linha de progresso (n de 5)
function Passo([int]$n, [string]$texto) {
    Write-Host ("  " + (Fg $PAL.Amar) + $ICO.Frasco + (Rs) + " " + (Dim) + "[$n/5]" + (Rs) + " $texto")
}

# Continuar-No-Terminal: fora do terminal interativo, não fecha ao terminar: abre o modelos.ps1.
function Continuar-No-Terminal {
    if ($env:ORQ_CLI) { return }
    if ([Console]::IsInputRedirected -or [Console]::IsOutputRedirected) { return }
    Write-Host ""
    $r = Read-Host "Enter para abrir o terminal de modelos (/help lista os comandos), q para sair"
    if ($r -match '^[qQ]$') { return }
    $script:LimpouAqui = $false   # a sessão interativa assume a restauração dos containers
    & (Join-Path $PSScriptRoot "modelos.ps1")
}

if ($Listar) { Listar-Testes; return }

if (-not (Get-Python)) { Write-Host "python não encontrado (instale o Python 3 e marque 'Add to PATH')." -ForegroundColor Red; exit 1 }
if (-not (Test-Ollama)) { Write-Host "Ollama não responde em $($script:API). Abra o app do Ollama ou rode 'ollama serve'." -ForegroundColor Red; exit 1 }

if (-not $Modelo) {
    Write-Host "Modelos instalados:"
    foreach ($nome in (NomesTestaveis)) {
        $s = Situacao $nome
        if ($s) { Write-Host ("  [testado]      {0}  ({1})" -f $nome, $s) }
        else { Write-Host ("  [falta testar] {0}" -f $nome) }
    }
    Write-Host "  (-Listar mostra o ranking por tok/s)"
    $Modelo = Read-Host "Nome do modelo no Ollama"
}
if (-not $Modelo) { Write-Host "nenhum modelo informado" -ForegroundColor Red; exit 2 }

$tags = Invoke-Ollama "/api/tags" -Get -Timeout 5
$instalado = @($tags.models | Where-Object { $_.name -eq $Modelo -or $_.name -eq "${Modelo}:latest" }).Count -gt 0
if (-not $instalado) {
    $r = Read-Host "'$Modelo' não está instalado. Baixar agora? [s/N]"
    if ($r -notmatch '^[sSyY]$') { exit 1 }
    ollama pull $Modelo
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

if (-not (GeraTexto $Modelo)) {
    Write-Host ((Fg $PAL.Verm) + "$($ICO.Xis) $Modelo não gera texto (modelo de embeddings)." + (Rs) + " Ele não responde aos prompts de teste;") -ForegroundColor Red
    Write-Host "  escolha um modelo de linguagem. Use /list para ver os testáveis."
    exit 1
}

# Capacidades: o parâmetro "think" só pode ser enviado a modelos que o suportam.
$show = Invoke-Ollama "/api/show" @{ model = $Modelo } -Timeout 10
$temThinking = ($null -ne $show) -and ($null -ne $show.capabilities) -and (@($show.capabilities) -contains "thinking")
if ($temThinking) { $thinkRotulo = if ($Think) { "on" } else { "off" } }
else {
    $thinkRotulo = "n/a"
    if ($Think) { Write-Host "aviso: $Modelo não tem thinking; -Think ignorado." }
}

$npVel = if ($Rapido) { 300 } else { 700 }
$minimo = [int]($npVel / 2)
$agora = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$DIR = Join-Path (Join-Path $SAIDA ($Modelo -replace '[:/\\]', '_')) $agora
New-Item -ItemType Directory -Path $DIR -Force | Out-Null
$sw = [Diagnostics.Stopwatch]::StartNew()
$script:LimpouAqui = $false

# --- Prompts (mesmos de docs/PROMPT-TESTE.md e de testar-modelo.sh) ---
$PROMPTS = @{}
$PROMPTS["vel"] = @'
Explique, em português, como funciona um índice B-tree em banco de dados relacional.
Cubra: estrutura de nós, busca, inserção com divisão de página e custo de leitura.
Escreva exatamente 6 parágrafos de 4 a 5 frases cada. Não use listas nem tabelas.
'@
$PROMPTS["A"] = @'
Você é um planejador de software. Pedido: "adicionar paginação à listagem de clientes de uma API Laravel,
com os parâmetros page e per_page (máximo 100)".
Responda SOMENTE com um plano de exatamente 5 passos numerados. Cada passo tem no máximo 20 palavras e
cita o arquivo ou a camada afetada (rota, controller, request, resource, teste). Sem introdução e sem conclusão.
'@
$PROMPTS["B"] = @'
Converta o plano abaixo em tarefas para agentes. Responda SOMENTE com JSON válido, sem texto antes ou depois,
sem markdown, neste formato:
{"tarefas":[{"id":1,"titulo":"...","arquivos":["..."],"depende_de":[],"criterio":"..."}]}

Plano:
1. Criar PaginacaoRequest validando page (inteiro >= 1) e per_page (inteiro 1..100).
2. Usar o request no ClienteController@index com paginate().
3. Devolver os dados via ClienteResource::collection.
4. Atualizar a rota GET /clientes se necessário.
5. Escrever teste de feature cobrindo per_page=101 (422) e per_page=10 (200).
'@
$PROMPTS["C"] = @'
Escreva em Python 3 uma função slugify(texto: str) -> str que:
- converte para minúsculas;
- remove acentos (ex.: "ação" vira "acao");
- troca qualquer sequência de caracteres não alfanuméricos por um único hífen;
- remove hífens no início e no fim.
Depois escreva 2 testes pytest: slugify("  Olá, Mundo!! ") == "ola-mundo" e slugify("---") == "".
Responda só com o código em um único bloco python, sem explicações.
'@
$PROMPTS["D"] = @'
Revise o diff abaixo. Liste somente problemas reais (bugs ou riscos), um por linha, no formato
"linha N: problema". Se não houver nenhum, responda "nenhum problema".

--- a/paginacao.py
+++ b/paginacao.py
@@ -1,9 +1,9 @@
 def paginar(itens, page, per_page):
     if per_page > 100:
         per_page = 100
-    inicio = (page - 1) * per_page
+    inicio = page * per_page
     fim = inicio + per_page
     return itens[inicio:fim]
'@
$ROTULO = @{ A = "Planejamento"; B = "Divisão JSON"; C = "Código"; D = "Revisão" }
$NPRED = @{ A = 600; B = 1200; C = 1200; D = 600 }

# Gerar <prompt> <num_predict>: chama /api/generate; devolve o objeto da resposta (ou $null).
function Gerar([string]$prompt, [int]$np) {
    $corpo = @{
        model = $Modelo; prompt = $prompt; stream = $false
        options = @{ temperature = 0; seed = 42; num_ctx = 4096; num_predict = $np }
    }
    if ($temThinking) { $corpo["think"] = [bool]$Think }
    return Invoke-Ollama "/api/generate" $corpo -Timeout 900
}

function Tem-Campo($obj, [string]$campo) { return ($null -ne $obj) -and ($null -ne $obj.PSObject.Properties[$campo]) }

function Executar-Teste {
    Write-Host ""
    Pl $PAL.Roxo $PAL.Texto "$($ICO.Frasco)  Testando" $PAL.Escuro $PAL.Ciano $Modelo $PAL.Escuro $PAL.Cinza "thinking: $thinkRotulo"

    if ($Limpar) {
        Write-Host ""
        $script:LimpouAqui = $true
        Limpar $Modelo
    }

    # --- 1. Velocidade: rodada a frio e rodada a quente ---
    Write-Host ""
    Passo 1 "Velocidade (a frio, depois a quente; $npVel tokens)"
    $null = Invoke-Ollama "/api/generate" @{ model = $Modelo; keep_alive = 0 } -Timeout 30
    Start-Sleep -Seconds 2
    $ramDisp = MemDispMB
    Write-Host ("      " + (Dim) + "RAM disponível no início: $ramDisp MB" + (Rs))
    $frio = Gerar $PROMPTS["vel"] $npVel
    $quente = Gerar $PROMPTS["vel"] $npVel
    foreach ($par in @(@("frio", $frio), @("quente", $quente))) {
        $o = $par[1]
        if (-not (Tem-Campo $o "eval_duration")) {
            $msg = if (Tem-Campo $o "error") { $o.error } else { "sem resposta" }
            Write-Host "erro do Ollama: $msg" -ForegroundColor Red
            return
        }
    }
    [IO.File]::WriteAllText((Join-Path $DIR "velocidade_frio.json"), ($frio | ConvertTo-Json -Depth 10), $utf8)
    [IO.File]::WriteAllText((Join-Path $DIR "velocidade_quente.json"), ($quente | ConvertTo-Json -Depth 10), $utf8)

    $tokGer = [Math]::Round($quente.eval_count / ($quente.eval_duration / 1e9), 1)
    # Leitura do prompt vem da rodada a frio: na quente o prompt já está em cache e a taxa sai inflada.
    $tokLeit = [Math]::Round($frio.prompt_eval_count / ($frio.prompt_eval_duration / 1e9), 1)
    $carga = [Math]::Round($frio.load_duration / 1e9, 1)
    $tokens = [int]$quente.eval_count

    $ramGb = 0.0; $cpuPct = 0; $gpuPct = 0
    $ps = Invoke-Ollama "/api/ps" -Get -Timeout 5
    if ($null -ne $ps) {
        $m = @($ps.models | Where-Object { $_.name -eq $Modelo -or $_.name -eq "${Modelo}:latest" }) | Select-Object -First 1
        if ($m) {
            $ramGb = [Math]::Round($m.size / 1e9, 1)
            if ($m.size -gt 0) {
                $cpuPct = [int][Math]::Round(($m.size - $m.size_vram) / $m.size * 100)
                $gpuPct = 100 - $cpuPct
            }
        }
    }

    function Mostrar-Velocidade([string]$recuo) {
        Write-Host ("{0}geração   {1}{2}{3,7} tok/s{4}  {5}" -f $recuo, (Fg $PAL.Ciano), (Neg), (Fmt $tokGer), (Rs), (BarraV $tokGer 40 20 $PAL.Ciano))
        Write-Host ("{0}leitura   {1,7} tok/s" -f $recuo, (Fmt $tokLeit))
        Write-Host ("{0}carga     {1,7} s" -f $recuo, (Fmt $carga))
        Write-Host ("{0}memória   {1,7} GB em uso | {2}% CPU / {3}% GPU | RAM livre no início: {4} MB" -f $recuo, (Fmt $ramGb), $cpuPct, $gpuPct, $ramDisp)
        if ($tokens -lt $minimo) {
            Write-Host ("{0}{1}{2} aviso:{3} só $tokens tokens gerados; a taxa de velocidade é pouco confiável." -f $recuo, (Fg $PAL.Amar), $ICO.Xis, (Rs))
        }
    }

    if ($Velocidade) {
        Write-Host ""
        Pl $PAL.Amar $PAL.Base "$($ICO.Bolt)  Velocidade" $PAL.Escuro $PAL.Ciano $Modelo
        Write-Host ""
        Mostrar-Velocidade "  "
        Write-Host ((Dim) + "  (só velocidade: nada foi salvo; use /test para a avaliação completa)" + (Rs))
        Remove-Item -Recurse -Force $DIR -ErrorAction SilentlyContinue
        $pai = Split-Path $DIR
        if ((Test-Path $pai) -and -not (Get-ChildItem $pai -Force)) { Remove-Item $pai -ErrorAction SilentlyContinue }
        Continuar-No-Terminal
        return
    }

    # --- 2. Qualidade: prompts A-D ---
    $RES = @{}
    $i = 2
    foreach ($t in @("A", "B", "C", "D")) {
        Passo $i "${t}. $($ROTULO[$t])"
        $r = Gerar $PROMPTS[$t] $NPRED[$t]
        $texto = if (Tem-Campo $r "response") { [string]$r.response } else { "" }
        $arq = Join-Path $DIR "resposta_$t.txt"
        [IO.File]::WriteAllText($arq, $texto, $utf8)
        $avaliacao = (Invoke-Py $AVALIADOR $t $arq) -join " "
        $RES[$t] = $avaliacao.Trim()
        $i++
    }

    # --- 3. Pontuação ---
    # Qualidade: 15 pontos por prompt (máx. 60). Velocidade: até 40 pontos, 40 em >= 20 tok/s.
    $pontosQ = 0
    foreach ($t in @("A", "B", "C", "D")) { if ($RES[$t] -eq "OK") { $pontosQ += 15 } }
    $pontosV = [int][Math]::Round([Math]::Min(40, $tokGer / 20 * 40), [MidpointRounding]::AwayFromZero)
    $nota = $pontosQ + $pontosV
    $tempo = [int]$sw.Elapsed.TotalSeconds

    $serve = @()
    if ($tokGer -ge 15 -and $RES["B"] -eq "OK") { $serve += "roteador/divisor" }
    if ($tokGer -ge 8 -and $RES["A"] -eq "OK" -and $RES["D"] -eq "OK") { $serve += "planejador/revisor" }
    if ($tokGer -ge 8 -and $RES["C"] -eq "OK") { $serve += "executor" }
    $serveTxt = if ($serve.Count -gt 0) { $serve -join " " } else { "nenhuma etapa (abaixo do mínimo de velocidade ou qualidade)" }

    $corNota = CorNota $nota
    Write-Host ""
    Pl $PAL.Verde $PAL.Base "$($ICO.Check)  Resultado" $PAL.Escuro $PAL.Ciano $Modelo $corNota $PAL.Base "$($ICO.Trofeu) $nota/100"
    Write-Host ""
    Write-Host ("  " + (Fg $PAL.Ciano) + "$($ICO.Bolt) Velocidade" + (Rs))
    Mostrar-Velocidade "    "
    Write-Host ""
    Write-Host ("  " + (Fg $PAL.Rosa) + "$($ICO.Codigo) Qualidade" + (Rs))
    foreach ($t in @("A", "B", "C", "D")) {
        if ($RES[$t] -eq "OK") {
            Write-Host ("    {0}{1}{2}  {3}  {0}ok{2}" -f (Fg $PAL.Verde), $ICO.Check, (Rs), "${t}. $($ROTULO[$t])")
        } else {
            Write-Host ("    {0}{1}{2}  {3}  {4}{5}{2}" -f (Fg $PAL.Verm), $ICO.Xis, (Rs), "${t}. $($ROTULO[$t])", (Dim), $RES[$t])
        }
    }
    Write-Host ""
    Write-Host ("  {0}{1} Nota{2}    {3}{4}{5}/100{2}  {6}  {7}(qualidade {8}/60 + velocidade {9}/40){2}" -f `
        (Fg $PAL.Amar), $ICO.Trofeu, (Rs), (Fg $corNota), (Neg), $nota, (BarraV $nota 100 20 $corNota), (Dim), $pontosQ, $pontosV)
    Write-Host ("  " + (Neg) + "Serve para" + (Rs) + "  $serveTxt")
    $rel = $DIR.Replace($RAIZ + [IO.Path]::DirectorySeparatorChar, "")
    Write-Host ((Dim) + "  Tempo do teste: ${tempo}s | respostas em: $rel" + (Rs))

    # --- 4. CSV ---
    $cab = "data,modelo,thinking,tok_s_geracao,tok_s_leitura,carga_s,ram_gb,cpu_pct,A,B,C,D,pontos_qualidade,pontos_velocidade,nota,tempo_s,ram_disp_mb,maquina"
    if (-not (Test-Path $CSV)) { [IO.File]::WriteAllText($CSV, $cab + "`n", $utf8) }
    $linhasCsv = [IO.File]::ReadAllLines($CSV, $utf8)
    if ($linhasCsv.Count -gt 0) {
        # CSV criado antes das colunas ram_disp_mb/maquina: completa o cabeçalho (linhas antigas ficam vazias)
        if ($linhasCsv[0] -notmatch "ram_disp_mb") { $linhasCsv[0] += ",ram_disp_mb" }
        if ($linhasCsv[0] -notmatch "maquina") { $linhasCsv[0] += ",maquina" }
        [IO.File]::WriteAllText($CSV, (($linhasCsv -join "`n") + "`n"), $utf8)
    }
    $campos = @(
        (Get-Date -Format "yyyy-MM-dd_HH:mm"), $Modelo, $thinkRotulo, (Fmt $tokGer), (Fmt $tokLeit), (Fmt $carga),
        (Fmt $ramGb), $cpuPct,
        ($RES["A"] -split ":")[0], ($RES["B"] -split ":")[0], ($RES["C"] -split ":")[0], ($RES["D"] -split ":")[0],
        $pontosQ, $pontosV, $nota, $tempo, $ramDisp, $env:COMPUTERNAME
    )
    [IO.File]::AppendAllText($CSV, (($campos -join ",") + "`n"), $utf8)
    Write-Host ((Dim) + "  $($ICO.Check) salvo em $CSV. Use /rank, /nota ou /report para comparar." + (Rs))
    Continuar-No-Terminal
}

try { Executar-Teste }
finally { if ($script:LimpouAqui) { $null = Restaurar } }
