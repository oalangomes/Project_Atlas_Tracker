# Performance das consultas do Atlas

Medição de 26/11/2026 no workspace ativo, carreira 1, snapshot 111, banco SQLite de 19,5 GB. As medições diretas usaram `mode=ro`. Os tempos abaixo são locais e dependem do cache de páginas do Windows e da carga concorrente.

| Caminho medido | Antes | Depois | Verificação |
| --- | ---: | ---: | --- |
| SQL de estatísticas do elenco | 3,36–3,77 s | 0,078–0,087 s | Três execuções por versão, linhas e SHA-256 idênticos. O plano passou de `SCAN` para `SEARCH` por snapshot no índice existente. |
| Tela de dados da partida em Análise | 27,37 s e 1,96 MB na resposta agregada | 1,03 s e 396 kB na projeção | Mesmos campos de MatchStats, contexto defensivo e seleção de temporada. |
| Visão geral de Análise | 27,37 s e 1,96 MB na resposta agregada | 6,23 s e 353 kB na projeção | Mesmas métricas, histórico, atividade, qualidade e resumo de MatchStats. |
| Cache da Comissão para uma atuação | 0,286 s e 1.569 SQL | 0,071 s e 122 SQL | Mesmo JSON salvo, incluindo estado e hash de evidências. |
| Cache da Comissão para a partida | 0,337 s e 1.569 SQL | 0,233 s e 122 SQL | Mesmo JSON salvo, incluindo estado e hash de evidências. |

Os tempos do elenco abrangem a consulta principal. A rota também calcula finanças, dinâmica e mídia. O log de produção `%LOCALAPPDATA%/ProjectAtlasTracker/logs/atlas_performance.log` registra requisições a partir de 0,75 s e ajuda a localizar picos. A distribuição desse arquivo descreve somente requisições registradas.

Nas medições diretas de Análise, a resolução de mídia foi substituída pela mesma referência vazia nas duas versões. Os campos usados pelas seis telas coincidiram com a versão agregada anterior, considerando o filtro de clube nas listas de movimentações. As seis projeções também responderam HTTP 200 no servidor isolado. O Chromium confirmou a navegação entre abas, a leitura individual sob demanda e o reuso de GETs concorrentes. As respostas de jogador e de geração da Comissão nessa verificação de interface vieram de fixtures locais.

## Caminhos de leitura

- **Elenco.** A agregação de `season_stat_states` recebe o snapshot antes do agrupamento. A associação continua usando o clube representado pelo atleta, inclusive em elencos com empréstimos e múltiplas competições.
- **Análise.** `GET /api/careers/{career_id}/analysis` aceita `view=overview|performance|squad|seasons|records|season-report`. As telas pedem sua projeção. Desempenho usa MatchStats e contexto defensivo. Elenco usa composição, evolução e resumo de MatchStats. Comparação calcula a tabela por temporada. Visão geral, recordes e relatório limitam movimentações aos clubes geridos no período. O formato agregado continua disponível ao omitir `view`. `season_index=-1` seleciona todas as temporadas disponíveis.
- **Movimentações.** Uma comparação restrita ao clube parte dos jogadores vinculados a ele em cada lado do par de snapshots. Isso cobre entradas e saídas mesmo quando o atleta pertencia a outro clube no início do par. O perfil restringe a comparação pelo ID do atleta. A deduplicação de acordos e a exclusão de transferências explicadas por empréstimos continuam no caminho comum.
- **Comissão.** Os antecedentes coletivos reutilizam a seleção de export elegível e a normalização de métricas de equipe. As métricas individuais são hidratadas apenas quando consumidas, com uma junção para nome, posição registrada e clube no snapshot de origem. A partida agenda relatórios em segundo plano e consulta o relatório individual ao expandir o atleta. No perfil, apenas Análise e Comissão fazem a consulta à Comissão.

## Cache e próximos pontos de medição

O frontend compartilha a promessa de um GET idêntico em curso para Análise, Rotação, Elenco e status de relatório da Comissão. Ao concluir, o próximo GET consulta novamente a API. A invalidação já usada pelas importações e alterações da interface também limpa essas promessas.

A próxima oportunidade é compartilhar o contexto comum da partida durante o agendamento de vários relatórios. O reuso pode ficar restrito ao lote, com carreira, fixture, snapshot e sequência de importação como escopo. Para guardar projeções completas entre requisições, a invalidação também precisaria acompanhar vínculos e supersessões de MatchStats, edições manuais e configurações de apresentação. O cache persistente da Comissão continua revalidando as evidências.

Os próximos caminhos para perfil separado são a abertura do elenco com simulação ainda pendente, o cálculo de finanças por atleta e o polling do relógio, que também carrega o histórico recente de transfer pulses. O custo e as dependências da simulação estão na [auditoria de armazenamento](atlas-storage-optimization.md).

## Verificação

Execute `py -3 -m unittest discover -s tests -q` e `npm.cmd run build --prefix frontend`. Para reproduzir a medição SQL do elenco, use a consulta de `_squad` em `atlas/server_query_dashboard.py`, compare `EXPLAIN QUERY PLAN` com a revisão anterior e confira o resultado completo no mesmo snapshot. Para as projeções de análise, compare os campos consumidos pela tela com a resposta agregada no mesmo banco e período. As listas de movimentações da visão geral e do relatório usam o recorte do clube gerido.
