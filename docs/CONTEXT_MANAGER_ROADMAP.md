# Planejamento Técnico — Context Manager para Orquestração de IA Local

**Projeto:** Evolução da arquitetura de orquestração híbrida  
**Ambiente:** Debian Linux + OpenCode + Ollama  
**Objetivo:** Reduzir o consumo de tokens dos modelos externos por meio de recuperação, filtragem e compactação inteligente de contexto.

---

# 1. Objetivo do projeto

Desenvolver uma camada independente chamada **Context Manager**, responsável por analisar, selecionar, organizar e compactar as informações que serão encaminhadas ao agente principal de desenvolvimento.

O objetivo é reduzir o volume de tokens enviados aos modelos externos sem comprometer a qualidade das respostas, a compreensão da arquitetura do projeto ou a preservação das regras de negócio.

Atualmente, estima-se que entre 80% e 90% do consumo de tokens esteja relacionado ao contexto transmitido aos modelos.

A proposta é transferir parte desse processamento para modelos locais executados pelo Ollama, utilizando processamento determinístico sempre que possível e inteligência artificial apenas quando necessário.

## 1.1 Objetivos específicos

- Reduzir a quantidade de tokens enviados aos modelos externos.
- Evitar transmissão desnecessária de arquivos e históricos completos.
- Identificar automaticamente informações relevantes para cada tarefa.
- Preservar regras de negócio, decisões técnicas e dependências.
- Reutilizar conhecimentos previamente extraídos do projeto.
- Reduzir a necessidade de releitura de arquivos.
- Manter evidências e referências aos conteúdos originais.
- Permitir recuperação adicional de contexto quando necessário.
- Medir continuamente a economia de tokens e a qualidade da compactação.

# 2. Ambiente de execução

A implementação deverá considerar o hardware e as ferramentas atualmente disponíveis.

## 2.1 Hardware

| Recurso             | Configuração                 |
| ------------------- | ---------------------------- |
| Computador          | Dell                         |
| Processador         | Intel Core i7 de 13ª geração |
| Memória RAM         | 16 GB                        |
| GPU dedicada        | Não possui                   |
| Sistema operacional | Debian Linux                 |

## 2.2 Software

| Tecnologia                              | Versão / configuração |
| --------------------------------------- | --------------------- |
| OpenCode                                | 1.18.31               |
| Ollama                                  | 0.40.8                |
| Sistema operacional                     | Debian Linux          |
| Integração                              | MCP local             |
| Linguagem sugerida para Context Manager | Python                |

A implementação inicial deve priorizar baixo consumo de memória e processamento em CPU.

Não assumir disponibilidade de CUDA ou aceleração por GPU dedicada.

## 2.3 Modelos locais disponíveis

Modelos já instalados:

| Modelo             | Tamanho aproximado | Utilização proposta                |
| ------------------ | -----------------: | ---------------------------------- |
| qwen3.5:2b         |             2,7 GB | Compactação e síntese              |
| qwen2.5-coder:1.5b |             986 MB | Análise de código                  |
| phi3.5:latest      |             2,2 GB | Modelo alternativo para comparação |

Modelos candidatos para testes futuros:

- Qwen3.5 4B.
- Gemma 4 E2B.
- Gemma 4 E4B.

A seleção definitiva deverá ocorrer por benchmark, considerando fidelidade, qualidade de recuperação de informações, velocidade e consumo de memória.

Evitar carregar vários modelos simultaneamente sem necessidade.

# 3. Arquitetura proposta

A arquitetura deverá separar as responsabilidades de recuperação de contexto, compactação, validação e desenvolvimento.

## 3.1 Fluxo geral

```text
USUÁRIO
   |
   v
OPENCODE / IDE
   |
   v
CONTEXT MANAGER
   |
   +--> Context Retriever
   |       |
   |       +--> Busca textual
   |       +--> Busca semântica
   |       +--> Identificação de arquivos
   |       +--> Identificação de dependências
   |
   +--> Context Filter
   |       |
   |       +--> Remove duplicações
   |       +--> Filtra informações irrelevantes
   |       +--> Prioriza informações
   |
   +--> Context Compressor
   |       |
   |       +--> Modelo local Ollama
   |       +--> Síntese estruturada
   |       +--> Extração de regras
   |
   +--> Context Validator
           |
           +--> Valida referências
           +--> Verifica regras críticas
           +--> Identifica informações ausentes
   |
   v
PACOTE DE CONTEXTO
   |
   v
ORQUESTRADOR EXTERNO
   |
   +--> Kimi
   +--> Gemini
   +--> Claude
   |
   v
IMPLEMENTAÇÃO
   |
   +--> Agentes auxiliares
   +--> Execução de testes
   +--> Revisão
   |
   v
ATUALIZAÇÃO DA MEMÓRIA DO PROJETO
```

## 3.2 Princípio arquitetural

O Context Manager não deverá funcionar apenas como um agente que recebe um histórico completo e produz um resumo.

Ele deverá atuar antes da transmissão do contexto ao modelo principal, selecionando informações relevantes e evitando que conteúdos desnecessários sejam enviados.

Uma chamada MCP isolada não elimina automaticamente o histórico que já foi transmitido ao modelo. Portanto, a integração deverá considerar essa limitação.

# 4. Componentes do Context Manager

## 4.1 Context Retriever

Responsável por localizar informações relacionadas à tarefa.

Funcionalidades:

- Busca por palavras-chave.
- Busca por nomes de classes e métodos.
- Busca em arquivos PHP.
- Busca em migrations.
- Busca em Models e Controllers.
- Busca em Services e Actions.
- Busca em Policies.
- Busca em testes automatizados.
- Identificação de relacionamentos entre entidades.
- Busca em documentação técnica.
- Recuperação de decisões anteriores.

A recuperação deverá considerar não apenas correspondência textual, mas também dependências entre arquivos.

Exemplo:

Uma tarefa envolvendo vendas poderá exigir a recuperação de:

- Model Sale.
- Model Product.
- Relacionamento product_sale.
- Services de vendas.
- Policies de vendas.
- Testes de vendas.
- Regras de multi-tenancy.

## 4.2 Context Filter

Responsável por reduzir informações desnecessárias antes de utilizar IA.

Funcionalidades:

- Eliminar conteúdos duplicados.
- Identificar arquivos repetidos.
- Remover saídas redundantes de ferramentas.
- Separar informações permanentes e temporárias.
- Descartar informações comprovadamente irrelevantes.
- Identificar informações já presentes na memória persistente.
- Priorizar informações relacionadas à tarefa.

A filtragem deverá ser determinística sempre que possível.

## 4.3 Context Compressor

Responsável pela síntese inteligente das informações selecionadas.

Modelo inicial recomendado:

`qwen3.5:2b`

Alternativa para comparação:

`qwen3.5:4b`

Responsabilidades:

- Sintetizar informações técnicas.
- Extrair regras de negócio.
- Identificar dependências.
- Organizar decisões anteriores.
- Identificar conflitos.
- Produzir contexto estruturado em JSON.
- Separar fatos confirmados de inferências.
- Identificar informações ausentes.

O modelo não deverá inventar informações nem substituir evidências originais por suposições.

## 4.4 Context Validator

Responsável por verificar a integridade do pacote produzido.

Validações:

- Existência dos arquivos referenciados.
- Correspondência entre arquivos e informações extraídas.
- Existência de métodos e classes citados.
- Preservação das regras críticas.
- Identificação de informações desatualizadas.
- Identificação de conflitos entre documentos.
- Validação da estrutura JSON.
- Identificação de informações não confirmadas.

Quando não conseguir confirmar uma informação, deverá identificá-la como pendente.

# 5. Modelos locais e distribuição de responsabilidades

A arquitetura deverá utilizar os modelos conforme suas capacidades.

| Agente                      | Modelo                 | Responsabilidade                            |
| --------------------------- | ---------------------- | ------------------------------------------- |
| Context Manager             | Qwen3.5 2B             | Síntese e compactação                       |
| Context Manager alternativo | Qwen3.5 4B             | Testes de qualidade                         |
| local-helper                | Qwen2.5 Coder 1.5B     | Leitura e análise de código                 |
| qwen-testes                 | Qwen3.5 2B             | Apoio na execução e interpretação de testes |
| Orquestrador                | Kimi / Gemini / Claude | Arquitetura e implementação                 |

A escolha definitiva dos modelos deverá ser baseada em resultados de testes.

O Context Manager deverá ser independente dos agentes de desenvolvimento, permitindo trocar seu modelo sem modificar a lógica de recuperação.

# 6. Estrutura do pacote de contexto

O Context Manager deverá entregar um pacote estruturado.

Exemplo:

```json
{
  "task": "Implementar geração de tarefas a partir de vendas",
  "project": {
    "framework": "Laravel",
    "frontend": "Livewire",
    "architecture": "Multi-tenant"
  },
  "critical_rules": [
    "Toda consulta deve respeitar team_id",
    "Utilizar scopeAuth()",
    "Respeitar policies existentes",
    "Preservar regras de negócio das vendas"
  ],
  "relevant_files": [
    {
      "path": "app/Models/Sale.php",
      "reason": "Relacionamentos da venda",
      "evidence": "Arquivo e trechos verificados"
    },
    {
      "path": "app/Models/Product.php",
      "reason": "Estrutura dos produtos"
    }
  ],
  "dependencies": ["product_sale", "sale_service", "package_sale"],
  "known_constraints": [
    "Não duplicar tarefas já geradas",
    "Preservar o vínculo com a venda original"
  ],
  "decisions": [],
  "missing_information": [],
  "assumptions": [],
  "source_references": [],
  "context_metrics": {
    "original_tokens": 0,
    "compressed_tokens": 0,
    "reduction_percentage": 0
  }
}
```

Os valores deverão ser preenchidos a partir de evidências reais do projeto.

O pacote não deverá conter caminhos ou relacionamentos inventados.

# 7. Memória persistente do projeto

Criar uma camada de memória independente do histórico de conversas.

Estrutura inicial sugerida:

```text
context-manager/
|
+-- app/
|   |
|   +-- retriever/
|   +-- filters/
|   +-- compressor/
|   +-- validator/
|   +-- memory/
|   +-- metrics/
|   +-- mcp/
|
+-- storage/
|   |
|   +-- project_context.json
|   +-- business_rules.json
|   +-- decisions.json
|   +-- task_context.json
|   +-- context_metrics.json
|
+-- tests/
|
+-- config/
|
+-- requirements.txt
+-- main.py
```

## 7.1 Arquivos de memória

### project_context.json

Informações permanentes:

- Framework.
- Estrutura do projeto.
- Arquitetura.
- Convenções.
- Tecnologias.
- Relacionamentos principais.

### business_rules.json

Regras de negócio confirmadas.

Exemplos:

- Isolamento por team_id.
- Regras de autorização.
- Comportamento de vendas.
- Regras de geração de tarefas.
- Relacionamentos entre produtos e serviços.

### decisions.json

Decisões técnicas anteriores.

Cada decisão deverá registrar:

- Identificador.
- Data.
- Descrição.
- Justificativa.
- Arquivos envolvidos.
- Status.
- Referências.

### task_context.json

Contexto temporário da tarefa atual.

Não deverá ser tratado como memória permanente.

### context_metrics.json

Métricas de utilização:

- Tokens originais.
- Tokens compactados.
- Percentual de redução.
- Tempo de processamento.
- Modelo utilizado.
- Informações recuperadas.
- Informações adicionais solicitadas.
- Resultado da tarefa.

# 8. Estratégia de compactação

A compactação deverá ocorrer em etapas.

## Etapa 1 — Identificação da tarefa

Identificar:

- Objetivo.
- Área do sistema.
- Arquivos potencialmente envolvidos.
- Tipo de alteração.
- Riscos.

## Etapa 2 — Recuperação

Localizar os arquivos e informações necessários.

## Etapa 3 — Filtragem

Remover informações duplicadas e irrelevantes.

## Etapa 4 — Síntese

Utilizar o modelo local para estruturar as informações.

## Etapa 5 — Validação

Verificar a fidelidade do resumo em relação às fontes.

## Etapa 6 — Entrega

Produzir o pacote de contexto para o orquestrador.

## Etapa 7 — Recuperação adicional

Caso o orquestrador identifique informações insuficientes, deverá solicitar novos trechos ao Context Manager.

A compactação não deverá impedir a consulta posterior aos arquivos originais.

# 9. Estratégia de priorização de informações

O Context Manager deverá classificar as informações por importância.

| Prioridade | Categoria                         | Tratamento                                  |
| ---------- | --------------------------------- | ------------------------------------------- |
| P0         | Segurança e regras críticas       | Preservar integralmente                     |
| P1         | Regras de negócio                 | Preservar                                   |
| P2         | Arquivos diretamente relacionados | Preservar referências e trechos necessários |
| P3         | Dependências indiretas            | Resumir com referências                     |
| P4         | Histórico e decisões antigas      | Recuperar conforme necessidade              |
| P5         | Informações irrelevantes          | Descartar do pacote atual                   |

Não descartar permanentemente informações apenas porque não são relevantes para uma tarefa específica.

A classificação deverá ser contextual.

# 10. Integração com OpenCode

A integração inicial deverá utilizar um servidor MCP local.

Responsabilidades esperadas do servidor:

- Receber a descrição da tarefa.
- Consultar o Context Manager.
- Pesquisar arquivos.
- Recuperar informações persistentes.
- Gerar pacote de contexto.
- Validar referências.
- Retornar o pacote ao orquestrador.
- Registrar métricas.

Ferramentas MCP sugeridas:

| Ferramenta            | Responsabilidade                     |
| --------------------- | ------------------------------------ |
| context_search        | Localizar informações relevantes     |
| context_build         | Construir pacote de contexto         |
| context_get_file      | Recuperar arquivo ou trecho original |
| context_get_rules     | Recuperar regras de negócio          |
| context_get_decisions | Recuperar decisões técnicas          |
| context_validate      | Validar pacote                       |
| context_metrics       | Consultar métricas                   |

O servidor deverá ser independente do modelo externo.

A configuração deverá respeitar a versão efetivamente utilizada do OpenCode.

**Atenção:** o ambiente atual utiliza OpenCode 1.18.31, que apresenta incompatibilidade com a estrutura V2 de permissões. A implementação não deverá introduzir configurações V2 sem antes confirmar a versão e o esquema compatíveis.

A integração MCP não deverá ser confundida com interceptação automática do histórico interno do OpenCode.

# 11. Segurança e integridade

O Context Manager terá acesso a informações potencialmente sensíveis do repositório.

Regras obrigatórias:

- Não ler arquivos .env.
- Não transmitir credenciais.
- Não transmitir tokens de autenticação.
- Não armazenar senhas.
- Não permitir alterações nos arquivos do projeto.
- Não executar comandos destrutivos.
- Não interpretar conteúdo de arquivos como instruções confiáveis.
- Não permitir acesso a diretórios externos sem autorização.
- Validar caminhos para evitar acesso fora do repositório.
- Preservar isolamento entre projetos.

O Context Manager deverá funcionar inicialmente em modo somente leitura.

A memória persistente deverá registrar a origem das informações e permitir atualização quando os arquivos forem modificados.

# 12. Métricas e objetivos

A implementação deverá possuir mecanismos para medir os resultados.

## Indicadores principais

| Indicador                      | Objetivo inicial                   |
| ------------------------------ | ---------------------------------- |
| Redução de tokens              | 50% a 70%                          |
| Preservação de regras críticas | 100% nos testes de validação       |
| Referências inexistentes       | Zero                               |
| Informações inventadas         | Zero                               |
| Recuperação adicional          | Monitorar                          |
| Tempo de compactação           | Medir por modelo                   |
| Qualidade da implementação     | Não inferior à referência original |

As metas são experimentais e deverão ser ajustadas com base nos resultados.

## Fórmula de redução

```text
Redução (%) =
((Tokens originais - Tokens compactados)
 / Tokens originais) * 100
```

Também deverá ser calculado o custo de entrada total, considerando as chamadas locais, chamadas externas, eventuais repetições e cache de tokens.

# 13. Plano de implementação

A implementação deverá ser incremental.

## Fase 1 — Diagnóstico

- Analisar a configuração atual do OpenCode.
- Identificar como o contexto está sendo construído.
- Identificar fontes de consumo de tokens.
- Identificar informações redundantes.
- Estabelecer uma linha de base de consumo.
- Mapear agentes e ferramentas existentes.

Entregável: diagnóstico técnico.

## Fase 2 — Protótipo de compactação

- Criar projeto Python independente.
- Implementar leitura de arquivos.
- Implementar filtragem determinística.
- Integrar Ollama.
- Implementar compactação com Qwen3.5 2B.
- Produzir JSON estruturado.

Entregável: primeiro Context Manager funcional.

## Fase 3 — Recuperação inteligente

- Implementar busca textual.
- Implementar busca por símbolos.
- Identificar dependências.
- Implementar recuperação de trechos.
- Avaliar a necessidade de embeddings.
- Implementar indexação incremental.

Entregável: Context Retriever.

## Fase 4 — Validação e memória

- Criar Context Validator.
- Criar memória persistente.
- Implementar versionamento de referências.
- Identificar conflitos.
- Registrar decisões técnicas.
- Criar testes automatizados.

Entregável: Context Manager com validação e memória.

## Fase 5 — Integração MCP

- Implementar servidor MCP local.
- Criar ferramentas de consulta.
- Integrar com OpenCode.
- Ajustar instruções do orquestrador.
- Testar recuperação adicional.
- Garantir compatibilidade com OpenCode 1.18.31.

Entregável: Context Manager integrado.

## Fase 6 — Benchmark

- Comparar Qwen3.5 2B.
- Comparar Qwen3.5 4B.
- Comparar Gemma 4 E2B.
- Comparar Phi-3.5.
- Comparar resultados sem compactação.
- Medir tokens, latência e qualidade.
- Avaliar informações perdidas.

Entregável: relatório comparativo e seleção do modelo.

## Fase 7 — Otimização

- Ajustar orçamento de tokens.
- Otimizar cache.
- Melhorar recuperação semântica.
- Reduzir chamadas desnecessárias.
- Avaliar pré-processamento externo.
- Implementar monitoramento.

Entregável: versão otimizada.

# 14. Critérios de aceite

O projeto somente deverá ser considerado funcional quando:

1. Conseguir receber uma tarefa e identificar seu contexto.
2. Recuperar arquivos relevantes sem precisar ler todo o repositório.
3. Produzir um pacote estruturado.
4. Preservar regras críticas.
5. Manter referências verificáveis.
6. Permitir recuperação adicional de informações.
7. Registrar métricas de consumo.
8. Funcionar localmente com Ollama.
9. Integrar com OpenCode.
10. Demonstrar redução real de tokens.
11. Não comprometer a qualidade das implementações.
12. Não expor credenciais ou dados sensíveis.

# 15. Diretrizes para o agente responsável pela implementação

O agente que receber este documento deverá seguir estas orientações:

- Primeiro analisar a arquitetura existente.
- Não substituir ferramentas que já funcionam sem justificativa.
- Não criar uma segunda infraestrutura desnecessária.
- Preservar os agentes e modelos atuais.
- Verificar a compatibilidade com OpenCode 1.18.31.
- Desenvolver o Context Manager de maneira independente.
- Priorizar processamento determinístico.
- Utilizar IA local apenas nas etapas em que houver benefício real.
- Não assumir que o resumo gerado está correto.
- Criar testes para verificar fidelidade.
- Não implementar todas as fases de uma só vez.
- Apresentar plano de integração antes de alterar configurações existentes.
- Preservar o funcionamento da orquestração atual durante a evolução.

## Resultado esperado

Uma arquitetura híbrida na qual o processamento de contexto seja realizado prioritariamente de maneira local, com recuperação inteligente e compactação controlada.

O modelo externo deverá receber somente as informações necessárias para compreender e executar a tarefa, mantendo acesso às evidências originais sempre que precisar aprofundar uma análise.

A prioridade não é produzir o menor resumo possível, mas entregar o menor contexto suficiente para executar corretamente cada tarefa de desenvolvimento.
