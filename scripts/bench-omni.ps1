#Requires -Version 5.1
<#
.SYNOPSIS
    Benchmark multimodal de um modelo do Ollama: texto, imagem, áudio e fala.
    Equivale a scripts/bench-omni.sh; a medição em si fica em scripts/bench_omni.py.

.DESCRIPTION
    Complementa scripts/testar-modelo.ps1, que só mede texto. Aqui a etapa de cada
    modalidade roda apenas se o modelo a declarar em /api/show:

      texto   carga, TTFT, tok/s de leitura e de geração
      imagem  custo da imagem em tokens de prompt e latência extra
      áudio   RTF de entrada (codificação ÷ duração do áudio)
      fala    RTF de saída (geração ÷ duração do áudio produzido)

    Modelos da família LFM3 (lfm3-omni, lfm3-audio) exigem o runtime MLX e, no
    Ollama 0.40.12, só rodam em Apple Silicon. O script avisa e sai com código 3
    em vez de gravar número inválido.

.PARAMETER Modelo
    Nome no Ollama (ex.: lfm3-omni, llava:7b). Sem ele, lista os instalados.
.PARAMETER Listar
    Só mostra os modelos instalados e as modalidades de cada um.
.PARAMETER Somente
    Etapas separadas por vírgula: text,image,audio,speech.
.PARAMETER NumPredict
    Tokens máximos por resposta (padrão 256).
.PARAMETER Imagem
    PNG de teste. Sem ele, o script gera um gradiente 512×512.
.PARAMETER Audio
    WAV 16 kHz de teste. Sem ele, gera um tom de 3 s (bom para latência, não para transcrição).
.PARAMETER SemSalvar
    Não grava JSON/CSV em docs/resultados/omni.

.EXAMPLE
    .\scripts\bench-omni.ps1 llava:7b
    .\scripts\bench-omni.ps1 lfm3-omni --audio fala.wav
    .\scripts\bench-omni.ps1 -Listar
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Modelo = "",
    [switch]$Listar,
    [Alias("only")][string]$Somente = "",
    [Alias("num-predict")][int]$NumPredict = 256,
    [Alias("image")][string]$Imagem = "",
    [string]$Audio = "",
    [Alias("sem-salvar")][switch]$SemSalvar
)

. (Join-Path $PSScriptRoot "visual.ps1")
. (Join-Path $PSScriptRoot "limpar-ram.ps1")

$BENCH = Join-Path $PSScriptRoot "bench_omni.py"

# Modalidades <modelo>: rótulo curto com o que o modelo declara em /api/show.
function Modalidades([string]$nome) {
    $s = Invoke-Ollama "/api/show" @{ model = $nome } -Timeout 15
    if ($null -eq $s -or $null -eq $s.capabilities) { return "texto" }
    $caps = @($s.capabilities)
    $rot = @()
    if ($caps -contains "completion") { $rot += "texto" }
    if ($caps -contains "vision") { $rot += "visão" }
    if ($caps -contains "audio") { $rot += "áudio" }
    if ($caps -contains "speech") { $rot += "fala" }
    if ($caps -contains "tools") { $rot += "tools" }
    if ($rot.Count -eq 0) { return "—" }
    return ($rot -join ", ")
}

function Mostrar-Modelos {
    $tags = Invoke-Ollama "/api/tags" -Get -Timeout 10
    if ($null -eq $tags) { Write-Host "Ollama não respondeu em $($script:API)." -ForegroundColor Red; return }
    Write-Host ""
    Write-Host ("  " + (Fg $PAL.Ciano) + (Neg) + "Modelos instalados" + (Rs))
    Write-Host ""
    foreach ($m in @($tags.models | Sort-Object name)) {
        $mod = Modalidades $m.name
        $cor = if ($mod -match "áudio|fala|visão") { Fg $PAL.Rosa } else { Dim }
        Write-Host ("  {0,-28} {1}{2}{3}" -f $m.name, $cor, $mod, (Rs))
    }
    Write-Host ""
    Write-Host ((Dim) + "  benchmark: .\scripts\bench-omni.ps1 <modelo>" + (Rs))
    Write-Host ((Dim) + "  só texto: .\scripts\testar-modelo.ps1 <modelo>" + (Rs))
}

if ($Listar -or -not $Modelo) { Mostrar-Modelos; return }

if (-not (Test-Ollama)) {
    Write-Host "Ollama não responde em $($script:API). Abra o app do Ollama ou rode 'ollama serve'." -ForegroundColor Red
    exit 1
}

$argumentos = @("--model", $Modelo, "--num-predict", $NumPredict)
if ($Somente)  { $argumentos += @("--only", $Somente) }
if ($Imagem)   { $argumentos += @("--image", $Imagem) }
if ($Audio)    { $argumentos += @("--audio", $Audio) }
if ($SemSalvar) { $argumentos += "--sem-salvar" }

Invoke-Py $BENCH @argumentos
$codigo = $LASTEXITCODE

if ($codigo -eq 3) {
    Write-Host ""
    Write-Host ((Fg $PAL.Amar) + "$($ICO.Chip) modelo Apple-only nesta versão do Ollama." + (Rs))
    Write-Host "  A família LFM3 usa quantização nvfp4 e exige o runtime MLX."
    Write-Host "  O Ollama 0.40.12 só a executa em Apple Silicon (release notes de 27/10/2026)."
    Write-Host "  Detalhes em docs/TROUBLESHOOTING.md#modelo-exige-mlx."
    exit 3
}
exit $codigo
