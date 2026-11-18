# P03 — Contrato de evidências e verificação

## Contrato implementado

`atlas/metric_evidence.py` produz o mesmo objeto `evidence` para o detalhe da
partida, a cobertura do snapshot e os fatos de partida da Comissão Técnica.
O contrato `atlas-match-evidence-v1` é calculado sob consulta; nenhuma tabela
nova ou migração de dados foi necessária.

| Campo | Significado |
| --- | --- |
| `careerId`, `snapshotId`, `seasonIndex`, `fixtureId` | Identidade e recorte selecionados |
| `period`, `eventDate` | Partida e data registrada do evento, se presente |
| `selectedSnapshotCareerDate` | Data do estado de carreira escolhido |
| `source.sourceSnapshotId` | Snapshot que recebeu o MatchStats |
| `source.exportId`, `importedAt`, `captureId` | Registro de importação e captura, quando disponíveis |
| `state`, `reason` | `complete`, `partial`, `unlinked` ou `absent` e motivo |
| `teams[].indicators[]` | Valor, unidade, origem, fórmula, entradas e ausência por equipe |
| `positions[]` | Posição observada com fonte e snapshot de origem; posição natural separada |

Uma exportação é elegível somente se pertence à carreira e temporada,
foi importada até a sequência do snapshot selecionado, está vinculada e tem
status de participantes completo. Duas linhas de equipe são exigidas para
publicar o detalhe. A consulta do painel de snapshots abrange todas as
partidas concluídas do time no estado selecionado; um Top-N não é usado como
denominador de cobertura. A lista e o detalhe de partidas seguem a mesma
regra. Um export substituído por correção futura continua elegível no snapshot
anterior à correção. Campos ausentes permanecem `null`; zero registrado é
disponível.

## Dicionário inicial de indicadores de partida

| Chave | Origem | Unidade | Regra |
| --- | --- | --- | --- |
| `npk_expected_goals` | FC26 direto | gols esperados sem pênalti | Não equivale a xG total |
| `expected_goals_derived` | Atlas derivado | gols esperados | NPK-xG + 0,7 × pênaltis cometidos pelo adversário, apenas com ambas as entradas |
| `expected_assists` | FC26 direto | assistências esperadas | xA do MatchStats; não reconciliar com outra fonte sem mesmo recorte e definição |
| `shots`, `shots_on_target` | FC26 direto | chutes | Sem preenchimento de ausentes |
| `key_passes` | FC26 direto | passes | Sem preenchimento de ausentes |
| `tracker_completed_through_passes_including_lobbed` | FC26 direto | passes | Inclui passes em profundidade pelo alto |
| `passes`, `passes_completed` | FC26 direto | passes | Taxa apenas com numerador e denominador comparáveis |

Os agregadores expõem `metricCoverage` com jogos cobertos por campo. Médias
por partida dividem pelo número de jogos com o campo. Taxas que exigem duas
ou mais entradas são bloqueadas quando as entradas não cobrem a mesma amostra
completa. Taxas por 90 minutos exigem minutos conhecidos em todos os jogos
que contribuíram para o numerador. A Comissão Técnica expõe
`metric_coverage` para seu perfil de equipe e calcula precisão de passes
somente com pares observados na mesma partida. `METRIC_VERSION=4` e
`REPORT_VERSION=35` invalidam resultados antigos com semântica diferente.
Na interface, o idioma selecionado define separadores numéricos e monetários;
contagens aparecem sem casas decimais e NPK-xG, xG derivado e xA exibem três.

## Reconciliação e limites

- GER, POT e salário preservam os dois valores importados e só geram delta
  quando ambos existem. A resposta de comparação inclui `delta_source`
  com carreira e snapshots de origem e destino.
- O xA identificado neste corte tem origem direta em MatchStats. Não foi
  encontrada uma segunda fonte xA comprovadamente equivalente para comparar
  numericamente. Valores de outros modelos, como `xg_sheffield`, ficam
  separados até definição e período serem validados.
- O manifesto por partida informa posição jogada apenas quando há fonte
  confiável da partida; `primary_position` nunca substitui observação.
- `eventDate`, `captureId` e `importedAt` têm significados distintos. Ausência
  do identificador de captura não autoriza inferir sua data.
- O contrato cobre os indicadores listados e o perfil MatchStats. O catálogo
  universal de indicadores manuais, estimados e modelos de entregas futuras
  ainda precisa de extensão antes de declarar AT-007 concluído para todo o Atlas.

## Verificação e reversão

Na branch `codex/p03-qualidade-evidencias`: `py -3 -m unittest discover -s
tests -q` (160 testes) e `npm run build` passaram; `git diff --check` passou. Testes
novos cobrem exportação completa, parcial e ausente; carreira e importação
futura; correção posterior; zero versus ausência; denominadores, posição e
deltas GER/POT.
Não houve medição de desempenho nem inspeção visual sistemática automatizada.
O usuário inspecionou o Match Center e aprovou o visual em 18/11/2026; os
demais cenários não foram confirmados visualmente nessa revisão. Reverter os
commits restaura o contrato anterior; não há migração
para desfazer. Caches anteriores perdem elegibilidade pela versão.
