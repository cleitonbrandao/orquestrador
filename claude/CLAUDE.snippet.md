## Orquestração local (run_tests, kb, triagem)

- Testes: use a ferramenta MCP `run_tests` (comando literal + `cwd` do diretório com `phpunit.xml`/`package.json`). Ela devolve só falhas + resumo; use `only_failures: false` apenas se precisar da saída completa.
- Veredito `passou` = exit 0 real. `bloqueado` = **não verificado** (nunca trate como sucesso).
- Conhecimento do projeto (docs, runbooks, decisões, onde algo é feito): consulte `search_kb(query)` antes de ler vários arquivos (o app padrão é o projeto atual). Se responder `não está indexado`, avise o usuário para rodar `orq-kb index` na raiz do projeto. Se o trecho não bastar, leia o arquivo apontado.
- Exploração ampla (onde X é feito, mapear vários arquivos): delegue ao subagente `triagem` e peça caminho:linha.
