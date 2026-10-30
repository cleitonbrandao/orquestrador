# Tema visual compartilhado (dot-source): estilo powerline / oh-my-posh, cores truecolor,
# ícones Nerd Font e título em pixel art. Equivale a scripts/visual.sh.
#   $env:NO_COLOR = "1"                    sem cores nem ícones (texto puro)
#   $env:ORQ_ICONS = "nerd|unicode|ascii"  força o conjunto de ícones (padrão: detecta Nerd Font)
# Requer um terminal com cores ANSI (Windows Terminal, ou conhost do Windows 10/11 recente).

# Saída em UTF-8 (títulos, ícones, acentos). Também vale para o que o Python imprime.
try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $OutputEncoding = [Console]::OutputEncoding
} catch { }

$script:ESC = [string][char]27

function Test-Cor {
    if ($env:NO_COLOR) { return $false }
    if ([Console]::IsOutputRedirected) { return $false }
    return $true
}
$script:V_COR = Test-Cor

# --- paleta (r;g;b), tons de pixel art ---
$script:PAL = @{
    Base = "30;30;46";  Texto = "205;214;244"; Cinza = "88;91;112";  Escuro = "49;50;68"
    Roxo = "137;88;245"; Ciano = "34;211;238"; Verde = "74;222;128"; Amar = "250;204;21"
    Rosa = "244;114;182"; Verm = "248;113;113"; Laranja = "251;146;60"; Azul = "96;165;250"
}

function Fg([string]$rgb) { if ($script:V_COR) { return "$($script:ESC)[38;2;${rgb}m" } else { return "" } }
function Bg([string]$rgb) { if ($script:V_COR) { return "$($script:ESC)[48;2;${rgb}m" } else { return "" } }
function Rs  { if ($script:V_COR) { return "$($script:ESC)[0m" } else { return "" } }
function Neg { if ($script:V_COR) { return "$($script:ESC)[1m" } else { return "" } }
function Dim { if ($script:V_COR) { return "$($script:ESC)[2m" } else { return "" } }

# --- ícones ---
function Get-ModoIcones {
    if ($env:ORQ_ICONS) { return $env:ORQ_ICONS }
    # fontes instaladas: procura "Nerd" nos registros de fontes do usuário e do sistema
    foreach ($chave in @("HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Fonts", "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")) {
        try {
            $nomes = (Get-ItemProperty -Path $chave -ErrorAction Stop).PSObject.Properties.Name
            if ($nomes -match "Nerd") { return "nerd" }
        } catch { }
    }
    return "unicode"
}

function Set-Icones {
    $modo = Get-ModoIcones
    $env:ORQ_ICONS = $modo   # o Python (relatorio.py) usa o mesmo conjunto de ícones
    $c = { param($n) [string][char]$n }
    if ($modo -eq "nerd") {
        $script:S_CAP_E = & $c 0xE0B6; $script:S_SEP = & $c 0xE0B0; $script:S_CAP_D = & $c 0xE0B0
        $script:ICO = @{
            Chip = & $c 0xF2DB; Bolt = & $c 0xF0E7; Trofeu = & $c 0xF091; Check = & $c 0xF00C; Xis = & $c 0xF00D
            Frasco = & $c 0xF0C3; Docker = & $c 0xF308; Codigo = & $c 0xF121; Engr = & $c 0xF085; Painel = & $c 0xF0E4
            Relogio = & $c 0xF017
        }
    } elseif ($modo -eq "unicode") {
        $script:S_CAP_E = [string][char]0x2590; $script:S_SEP = [string][char]0x258C; $script:S_CAP_D = [string][char]0x258C
        $script:ICO = @{
            Chip = [string][char]0x25A3; Bolt = [string][char]0x25B2; Trofeu = [string][char]0x2605; Check = [string][char]0x2714; Xis = [string][char]0x2718
            Frasco = [string][char]0x25C6; Docker = [string][char]0x25A4; Codigo = "<>"; Engr = [string][char]0x25C8; Painel = [string][char]0x25A6
            Relogio = [string][char]0x25F7
        }
    } else {
        $script:S_CAP_E = "["; $script:S_SEP = ""; $script:S_CAP_D = "]"
        $script:ICO = @{
            Chip = "#"; Bolt = "^"; Trofeu = "*"; Check = "+"; Xis = "x"
            Frasco = "*"; Docker = "d"; Codigo = "c"; Engr = "o"; Painel = "="; Relogio = "t"
        }
    }
}
Set-Icones

# Pl <bg> <fg> <texto> [<bg> <fg> <texto> ...]: segmentos powerline numa linha.
function Pl {
    $a = @($args)
    if (-not $script:V_COR) {
        $partes = @()
        for ($i = 0; $i + 2 -lt $a.Count; $i += 3) { $partes += "[" + $a[$i + 2] + "]" }
        Write-Host ($partes -join " ")
        return
    }
    $linha = ""; $bgAnt = $null
    for ($i = 0; $i + 2 -lt $a.Count; $i += 3) {
        $bgc = $a[$i]; $fgc = $a[$i + 1]; $txt = $a[$i + 2]
        if ($null -eq $bgAnt) { $linha += (Fg $bgc) + $script:S_CAP_E }
        else { $linha += (Fg $bgAnt) + (Bg $bgc) + $script:S_SEP }
        $linha += (Bg $bgc) + (Fg $fgc) + (Neg) + " $txt " + (Rs)
        $bgAnt = $bgc
    }
    $linha += (Fg $bgAnt) + $script:S_CAP_D + (Rs)
    Write-Host $linha
}

# BarraV <valor> <máximo> <largura> <cor>: barra de blocos preenchida na cor dada.
function BarraV([double]$valor, [double]$maximo, [int]$largura = 20, [string]$cor = "") {
    if (-not $cor) { $cor = $script:PAL.Ciano }
    $n = 0
    if ($maximo -gt 0) { $n = [int][Math]::Round($valor / $maximo * $largura, [MidpointRounding]::AwayFromZero) }
    if ($n -gt $largura) { $n = $largura }
    if ($n -lt 0) { $n = 0 }
    $cheio = [string][char]0x2588; $vazio = [string][char]0x2591
    return (Fg $cor) + ($cheio * $n) + (Rs) + (Dim) + ($vazio * ($largura - $n)) + (Rs)
}

# CorNota <0-100>: cor da paleta para a nota.
function CorNota([int]$nota) {
    if ($nota -ge 70) { return $script:PAL.Verde }
    if ($nota -ge 40) { return $script:PAL.Amar }
    return $script:PAL.Verm
}

# --- título em pixel art (fonte 3x5, pixels de 2 colunas, gradiente rosa -> ciano) ---
$script:PX = @{
    "M" = "X.X XXX XXX X.X X.X"; "O" = "XXX X.X X.X X.X XXX"; "D" = "XX. X.X X.X X.X XX."
    "E" = "XXX X.. XX. X.. XXX"; "L" = "X.. X.. X.. X.. XXX"; "S" = "XXX X.. XXX ..X XXX"
    "T" = "XXX .X. .X. .X. .X."; "N" = "XX. X.X X.X X.X X.X"; "A" = "XXX X.X XXX X.X X.X"
    "R" = "XX. X.X XX. X.X X.X"; "K" = "X.X X.X XX. X.X X.X"; "I" = "XXX .X. .X. .X. XXX"
    "B" = "XX. X.X XX. X.X XX."; "C" = "XXX X.. X.. X.. XXX"; "P" = "XXX X.X XXX X.. X.."
    "H" = "X.X X.X XXX X.X X.X"; "Q" = "XXX X.X X.X XXX ..X"; "U" = "X.X X.X X.X X.X XXX"
    " " = "... ... ... ... ..."
}
$script:GRAD = @("244;114;182", "206;125;214", "168;139;238", "110;172;240", "34;211;238")

# TituloPixel <TEXTO>: desenha o texto em 5 linhas.
function TituloPixel([string]$texto) {
    $bloco = [string][char]0x2588
    for ($linha = 0; $linha -lt 5; $linha++) {
        $saida = ""
        foreach ($ch in $texto.ToCharArray()) {
            $px = $script:PX[[string]$ch]
            if (-not $px) { $px = $script:PX[" "] }
            $celula = ($px -split " ")[$linha]
            foreach ($pix in $celula.ToCharArray()) {
                if ($pix -eq "X") { $saida += $bloco + $bloco } else { $saida += "  " }
            }
            $saida += "  "
        }
        Write-Host ("  " + (Fg ($script:GRAD[$linha])) + (Neg) + $saida + (Rs))
    }
}
