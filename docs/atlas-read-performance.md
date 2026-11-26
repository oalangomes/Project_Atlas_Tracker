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

### Agendamento de relatórios da Comissão

`queue_auto_commission_reports` abre uma transação de leitura para checar a partida e os atletas. A carreira, a partida e o snapshot selecionado delimitam o contexto, incluindo a sequência de importação que define os exports elegíveis. Calendário, diário, contexto do adversário, histórico coletivo e MatchStats da partida são carregados uma vez. Cada relatório conserva seus fatos individuais, a comparação por atleta e o hash de evidências.

O contexto compartilhado dura apenas durante a checagem do lote. A transação termina antes de os jobs entrarem na fila. Cada worker abre sua própria conexão e revalida os fatos e o cache persistente usando os dados disponíveis naquele momento. Isso inclui edições do diário ou importações confirmadas enquanto o job aguarda.

No SQLite ativo em modo somente leitura, a checagem da partida 1707 no snapshot 113 processou 17 relatórios, todos já no cache persistente. Em três execuções por revisão, a mediana passou de **0,586 s para 0,168 s**. O contador do SQLite passou de **2.062 para 159 instruções**, incluindo os comandos da transação. Os 17 hashes de evidências foram idênticos. A medição fixou o idioma, substituiu o agendador por um registrador local e excluiu o relatório de identidade da temporada. Ela cobre a decisão de agendamento e não mede a geração de texto.

Para guardar projeções completas entre requisições, a invalidação precisaria acompanhar vínculos e supersessões de MatchStats, edições manuais e configurações de apresentação.

### Finanças e dinâmica do Elenco

A rota de Elenco consulta a dinâmica e os dados financeiros em lote. Depois de verificar a simulação uma vez, lê os estados individuais do snapshot, os vínculos de elenco e os contratos em consultas agrupadas. O cálculo usa uma data efetiva por snapshot e um contexto de mercado por clube durante a requisição. Os salários observados, as avaliações e a ordem da resposta continuam vinculados a cada atleta. As chamadas de perfil individual reutilizam o cálculo com um único ID.

No snapshot 113, com 30 atletas no Elenco e 21.359 estados de jogador no banco, a mediana de quatro leituras passou de **3,852 s para 0,189 s**. As instruções SQL passaram de **545 para 19**, as conexões de **121 para 5** e a verificação da simulação de **30 para 1**. O JSON teve o mesmo SHA-256 nas oito execuções. A medição usou o SQLite ativo em modo somente leitura, com a mesma resposta vazia de mídia nas duas versões. Mede a montagem do Elenco com os estados já calculados.

### Página de Clube

Clube usa o mesmo lote de finanças e dinâmica. Para clubes com jogadores no elenco, a chamada em lote prepara os estados antes de o Clube ler as estatísticas simuladas. Uma consulta ao Clube sem jogadores só prepara a simulação mundial, usada na classificação e nas estatísticas coletivas.

No snapshot 113 do banco ativo, a resposta do Clube com 30 atletas teve o mesmo SHA-256 nas oito execuções. A mediana passou de **4,430 s para 0,546 s**, as instruções SQL de **501 para 60** e as conexões de **129 para 11**. A medição chamou a consulta do Clube sobre SQLite em modo somente leitura, com respostas de mídia vazias e sem decorar o JSON com os filtros da API.

### Primeira abertura do Elenco

`GET /api/snapshots/{id}/squad?view=roster` devolve os dados importados do elenco sem disparar o modelo financeiro ou a simulação. A interface começa pela consulta completa. Se ela ainda estiver pendente após 300 ms, pede a prévia e disponibiliza a lista e os filtros assim que ela chega. Os valores são preenchidos na mesma tabela quando a consulta completa termina. Se ela falhar após a prévia, a lista fica disponível e a interface permite tentar novamente. O GET sem `view` continua devolvendo a resposta completa.

Uma cópia seletiva do banco manteve os estados calculados do snapshot anterior (112) e iniciou o snapshot 113 com a simulação e a dinâmica pendentes. A prévia devolveu as 30 linhas **0,376 s após o início da abertura**, incluindo a espera de 300 ms e concorrendo com a consulta completa. A consulta completa levou **14,097 s**, dos quais **7,284 s** foram da simulação mundial do snapshot. A segunda consulta completa levou **0,193 s** e apresentou o mesmo JSON da primeira. A medição isola mídia e decoração da API. O cenário de vários snapshots anteriores pendentes fica fora desse recorte. O custo e as dependências da simulação estão na [auditoria de armazenamento](atlas-storage-optimization.md).

### Relógio da carreira

A inicialização e o polling usam `GET /api/careers/{id}/clock?view=summary`, que devolve a data efetiva, a fonte e os identificadores. A página de Importações continua usando o formato completo, com contagem e até 20 pulsos recentes. Quando o polling detecta um snapshot novo, o carregamento dos seletores reaproveita o status já recebido e faz uma leitura do relógio.

A versão anterior executava seis instruções SQL para atualizar o relógio. O resumo executou **duas** no mesmo banco, e o relógio completo passou a executar **quatro**, com o mesmo JSON. A carreira medida tinha zero pulsos gravados. O teste com pulsos confirma a seleção da data mais recente e a preservação da lista. O resumo também evita a resolução de nomes e o filtro de apresentação, pois devolve apenas metadados do relógio.

## Verificação

Execute `py -3 -m unittest discover -s tests -q` e `npm.cmd run build --prefix frontend`. Para reproduzir a medição SQL do elenco, use a consulta de `_squad` em `atlas/server_query_dashboard.py`, compare `EXPLAIN QUERY PLAN` com a revisão anterior e confira o resultado completo no mesmo snapshot. Para as projeções de análise, compare os campos consumidos pela tela com a resposta agregada no mesmo banco e período. As listas de movimentações da visão geral e do relatório usam o recorte do clube gerido.

Em Chrome headless com APIs locais simuladas, a inicialização e o polling buscaram o resumo do relógio. Importações buscou o histórico completo. O teste do Elenco confirmou a prévia, a preservação do foco e do filtro ao chegar o financeiro, além da recuperação após uma falha simulada.
