# Benchmark multimodal (texto, imagem, áudio e fala)

`scripts/testar-modelo.ps1` / `.sh` mede **só texto**: tok/s, prompt, carga e a nota dos
prompts A–D de [`PROMPT-TESTE.md`](PROMPT-TESTE.md). Isso não descreve um modelo omni,
onde a pergunta certa é *quanto tempo até a primeira palavra* e *quantas vezes mais rápido
que o tempo real o áudio é processado*.

`scripts/bench-omni.ps1` / `.sh` (motor em `scripts/bench_omni.py`, só biblioteca padrão)
preenche essa lacuna. Cada etapa roda apenas se o modelo declarar a capacidade em
`/api/show`:

| Etapa | Capacidade | O que mede |
|---|---|---|
| texto | `completion` | carga, TTFT a frio e a quente, tok/s de leitura e de geração |
| imagem | `vision` | tokens de prompt que a imagem custa, prefill, latência extra |
| áudio | `audio` | prefill e **RTF de entrada** (tempo de máquina ÷ duração do áudio) |
| fala | `speech` | **RTF de saída** (tempo de geração ÷ duração do áudio produzido) |

RTF é a métrica que importa em voz: **abaixo de 1** o modelo processa mais rápido do que o
áudio toca; acima de 1, a conversa fica mais lenta que o tempo real.

## Uso

```powershell
.\scripts\bench-omni.ps1 -Listar                  # modelos instalados e modalidades de cada um
.\scripts\bench-omni.ps1 llava:7b                 # texto + imagem
.\scripts\bench-omni.ps1 gemma4:e4b --only audio
.\scripts\bench-omni.ps1 lfm3-omni --audio fala.wav --num-predict 128
```

```bash
scripts/bench-omni.sh --listar
scripts/bench-omni.sh llava:7b
scripts/bench-omni.sh gemma4:e4b --only audio --sem-salvar
```

Sem `--image`/`--audio`, o script gera as fixtures: um PNG 512×512 com gradiente (custo de
imagem típico) e um WAV 16 kHz mono de 3 s com um tom de 440 Hz. O tom serve para latência;
para avaliar **transcrição**, passe fala real:

```powershell
# Windows: gera fala em português com a voz do sistema, 16 kHz mono
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile("fala.wav", $fmt)
$s.Speak("O rato roeu a roupa do rei de Roma.")
$s.Dispose()
```

Resultados vão para `docs/resultados/omni/<modelo>_<data>.json` e uma linha por execução em
`docs/resultados/omni.csv` (use `--sem-salvar` para não gravar).

### Códigos de saída

| Código | Significado |
|---|---|
| 0 | todas as etapas aplicáveis rodaram |
| 3 | o modelo exige o runtime MLX e não roda nesta plataforma |
| 4 | modelo não instalado (ou o Ollama não o encontra) |
| 5 | alguma etapa falhou — o motivo aparece na saída e no JSON |

## Estado em 28/10/2026: a família LFM3 não roda no Windows/Linux

`lfm3-omni` e `lfm3-audio` foram publicados em 27/10/2026 e **não executam** no Ollama
0.40.12 fora do Apple Silicon. Não é limitação de RAM nem de GPU: é o runtime.

```
$ ollama pull lfm3-audio
Error: this model requires MLX support, but the MLX runtime is not available
```

O manifesto no registry confirma o formato:

```
model_format  safetensors
file_type     nvfp4
requires      0.40.12
capabilities  completion, tools, audio, speech          (lfm3-audio)
capabilities  completion, vision, tools, audio, speech  (lfm3-omni)
```

E as notas da release v0.40.12 dizem, textualmente:

> Note: lfm3 and d1 2b are supported on Apple hardware in this release.
> Support for Linux/Windows coming soon.

`nvfp4` é quantização de 4 bits servida pelo runtime MLX. Enquanto o suporte a
Linux/Windows não sair, **qualquer número medido aqui seria inventado** — por isso o script
sai com código 3 em vez de gravar.

Quando o suporte chegar (ou numa máquina Apple), o mesmo comando passa a valer sem mudança:

```powershell
.\scripts\bench-omni.ps1 lfm3-omni
.\scripts\bench-omni.ps1 lfm3-audio
```

## Áudio de entrada: aceito e ignorado no 0.40.12

O `Message` do `/api/chat` só tem `content` (string) e `images`; não há campo de áudio na
struct `Message` do pacote `api` do Ollama ([api/types.go](https://github.com/ollama/ollama/blob/main/api/types.go)).
Mesmo assim, enviar `"audio": ["<base64>"]` devolve **HTTP 200** — o que
produz um falso positivo se o teste confiar no status.

Medido com `gemma4:e4b` (declara `audio`) e um WAV de 9,47 s de fala em português:

| Pedido | HTTP | tokens de prompt | resposta |
|---|---|---|---|
| `"Transcreva o audio."` | 200 | 17 | "Por favor, forneça o áudio para que eu possa transcrevê-lo em português." |
| idem + `audio: [base64]` | 200 | 17 | **exatamente a mesma frase** |

Formato alternativo (`content` como lista de `{type, ...}`) é rejeitado:

```
json: cannot unmarshal array into Go struct field .ChatRequest.messages.content of type string
```

Por isso `etapa_audio` só aceita o formato se a resposta **mudar** ou o prompt **crescer**
em relação ao mesmo pedido sem áudio. Caso contrário registra "HTTP 200, mas ignorado" e a
etapa falha com código 5. É o comportamento atual no 0.40.12.

Saída de fala é diferente: existe de verdade, pelo endpoint OpenAI-compatível
`/v1/audio/speech`, para modelos com capacidade `speech`. Modelos sem ela respondem
`400 "does not support speech"`. Nenhum modelo com `speech` está instalado nesta máquina,
então essa etapa ainda não foi exercitada de ponta a ponta.

## Exemplo de saída (medido, `llava:7b`)

```
Modelo      llava:7b
            7B · Q4_0
Capacidades completion, vision

Texto
  carga                11.64 s
  TTFT frio/quente     13.88 s / 2.1 s
  leitura              615.3 tok/s
  geração              45.0 tok/s
  prompt / gerados     99 / 96 tokens

Imagem
  tokens da imagem     577  (24 → 601)
  prefill              1.4 s
  latência extra       0.08 s
  geração              45.3 tok/s
```

Leitura: cada imagem custa **577 tokens de prompt** neste `llava:7b` — 24× o texto da
pergunta. Em contextos longos isso é o que estoura a janela, não a pergunta.

## Limites conhecidos

- Modelos com `thinking` gastam `num_predict` raciocinando antes de escrever: o campo
  `resposta` do JSON pode vir vazio com `tok/s` válido. Use `--num-predict` maior para
  avaliar conteúdo.
- A etapa de imagem mede **custo**, não acerto: não há gabarito de descrição.
- O WAV de teste padrão é um tom, não fala — mede codificação, não qualidade de transcrição.
