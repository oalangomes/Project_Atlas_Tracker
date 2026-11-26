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

## Investigação de campos ainda fora do MatchStats — 26/11/2026

Foram conferidos 59 pacotes em `MatchStats/imported` com `MATCH_READY` e
status `complete_participant_export`. Todos usaram `production_clean` com
70 contadores nomeados de MatchAnalysis, dois valores `float` e dois contadores
do MatchEventTracker. Os CSVs de participantes tinham 99 colunas e os de equipes
90. Nenhum pacote reteve linhas brutas. A posse disponível se limita às
contagens `possession_won` e `possession_lost`. O histórico consultado não cobre
percentual de posse, tempo de recuperação, cronologia, distâncias ou mapas.

A API pública do Live Editor documenta a leitura genérica de memória e os
eventos da carreira. `GetPlayersStats()` devolve acumulados de temporada. A
issue sobre exportação de estatísticas trata do CSV de temporada. Nenhuma das
referências consultadas fornece um mapeamento Lua da posse percentual ou dos
minutos da tela de eventos. [API de memória do Live Editor](https://github.com/xAranaktu/FC-26-Live-Editor/wiki/LUA-API-v2-MEMORY) · [Eventos](https://github.com/xAranaktu/FC-26-Live-Editor/wiki/LUA-API-v2-Events#careermodeevent) · [API de temporada](https://github.com/xAranaktu/FC-26-Live-Editor/wiki/LUA-API#getplayersstats) · [Issue 22](https://github.com/xAranaktu/FC-26-Live-Editor/issues/22).

O post público de apresentação do Atlas menciona posse. O ZIP local de
distribuição `Project_Atlas_Tracker_v1.2.7.zip` confirma `possession_won` e
`possession_lost` como os únicos campos de posse nos dois scripts de captura.
[Publicação do Atlas no r/FifaCareers](https://www.reddit.com/r/FifaCareers/comments/1wkqlmq/project_atlas_tracker_and_automatic_match_stats/).

Uma inspeção somente de leitura do `FC26.exe` instalado (versão de produto
`26.0.9129885.0`) encontrou as seguintes superfícies do jogo. Os nomes vêm do
executável. A disponibilidade efetiva de valores via Lua ainda requer prova
durante o jogo.

| Candidato | Evidência no FC 26 | Como validar a leitura |
| --- | --- | --- |
| Percentual de posse e tempo de recuperação da bola, por equipe | `MF_SUMMARY_POSSESSION`, `HOME_TEAM_POSSESSION_PCT`, `AWAY_TEAM_POSSESSION_PCT`, `MF_SUMMARY_BALL_RECOVERY_TIME` e `MatchAnalysisMatchFactsData` | Comparar os dois lados com Match Facts da mesma partida. Confirmar unidade do tempo de recuperação e verificar a definição de posse quando há bola disputada, a partir dos campos `HomePossessionWithoutContested`, `AwayPossessionWithoutContested` e `ContestedPossession`. |
| Minuto, tipo e jogadores dos eventos principais | `MatchAnalysisKeyEventsData`, `ListEventTime`, `ListHomePlayerId`, `ListAwayPlayerId`, `ListHomeEventType`, `ListAwayEventType` e campos de jogador que saiu. O Live Editor também lista `MatchJournalInterface`, `MatchEventsDB` e `MatchStatesDB`. | Confrontar gols, cartões e substituições com a tela. Confirmar identidade de quem entra e sai, lado, acréscimos e quais tipos o registro efetivamente retém. |
| xG total segundo o jogo | `MF_SUMMARY_EXPECTED_GOALS`, `HomeXG` e `AwayXG`. O Atlas já importa `npk_expected_goals` e calcula uma estimativa de xG total. | Comparar o valor exibido com a leitura em partidas com e sem pênaltis. Manter a origem do xG direto distinta da estimativa do Atlas. |
| Distância por jogador | `DISTANCE_TRAVELED`, `DISTANCE_SPRINTED` e `PP_POSSESSION_DISTANCE_DRIBBLED` | Comparar total, sprint e condução com Player Performance. Determinar a escala e repetir com titulares e reservas antes de definir unidade e cobertura. |
| Passes que quebram linhas, tipo de passe e tipo de chute | `MF_SUMMARY_LINEBREAK_DF_*`, `PP_PASSING_TYPE_*` e `PP_SHOOTING_TYPE_*`. Há rótulos para romper a linha defensiva por dentro, por fora e por cima, além do total de tentativas. | Testar ações diferenciáveis em jogo. Verificar se os tipos são contagens ou subgrupos e se a unidade é tentativa ou acerto. O Atlas já captura o total agregado de passes em profundidade completos, incluindo os pelo alto. |
| Mapas de chutes, passes e calor | `HomeMapData`, `AwayMapData`, `HomeHeatMapData`, `AwayHeatMapData`, `MF_PITCH_SHOOTING_*` e `MF_PITCH_PASSING_*` | Verificar se a superfície expõe registros com coordenadas ou apenas dados de visualização. Conferir a orientação por lado e tempo e testar alguns lances conhecidos antes de importar. |

O [AutoCapture](../../exporter/FC26_AutoCapture_v1.1.1.lua) já lê valores
MatchAnalysis entre as chaves `0` e `174`. Dessas 175 posições, 105 ficam fora
das colunas diretas e podem incluir lacunas, duplicatas ou outros tipos. Os
pontos de escrita de `06_team_getter_values.csv`, `07_player_getter_values.csv`
e `10_tracker_nested_key_values.csv` servem de referência para a sonda.
`open_diagnostic_csv` devolve um destino nulo na versão instalada, portanto
mudar apenas `EXPORT_DIAGNOSTICS` não recupera esses CSVs. O MatchEventTracker
lido pelo exportador contém contagens por jogador e chave. Para a cronologia,
investigar os dados de eventos principais do jogo. O
[Match Center](../../atlas/match_stats.py) hoje constrói eventos a partir das
contagens e deixa o minuto ausente.

O primeiro ensaio pode rodar em uma partida de teste, com os dados diagnósticos
limitados ao intervalo e ao pós-jogo, antes da volta ao Hub. Começar por posse
e recuperação, registrar os valores de Match Facts e confirmar a associação de
mandante e visitante. Para os campos que passarem na comparação em mais de uma
partida, registrar fonte, unidade, recorte da partida e cobertura no contrato de
evidências. Nesta investigação a sessão aberta estava na Central da carreira,
sem evidência numérica pós-jogo para a comparação.

### Posse persistida no save da carreira

O Sheffield Hub lê o bloco `BNRY/mxif` do save `CmMgr`. A posse é o `uint32`
little-endian do slot 3 de cada equipe (`mxif + 0x1D` para o mandante e
`mxif + 0xDD` para o visitante). O contrato foi calibrado no Hub com três
partidas e a tela do jogo. A porcentagem permanece no save até outra partida
concluída substituir o registro. [Especificação do Hub](https://github.com/oalangomes/ea-fc-sheffield-hub/blob/master/docs/fc26-mxif-reverse-spec.md).

O mesmo campo retornou **46% Plymouth Argyle e 54% Stevenage** em um save
local. A data `2026-03-17` e os IDs de mandante `1929` e visitante `361`
no fim do bloco correspondem à partida `1774` do snapshot Atlas. Os 16 IDs
dos jogadores do Plymouth desse jogo apareceram no lado mandante do bloco.
O bloco de Plymouth mede `6341` bytes com 36 registros de jogadores, enquanto
o layout de Sheffield documentado mede `6925` com 40. A posição das estatísticas
coletivas se manteve. O leitor inteiro do Hub usa o deslocamento fixo do
segundo layout para os dados finais e não devolveu a identidade da partida
na variante mais curta. Para essa variante, os 677 bytes finais preservam a
data duplicada e os dois IDs de equipe.

O [watcher do Atlas](../../atlas/watcher.py) lê automaticamente os arquivos
`CmMgr*` de `%LOCALAPPDATA%/EA SPORTS FC 26/settings` durante a varredura
normal e no `--scan`. O [leitor](../../atlas/fc26_save_possession.py) trabalha
com os bytes de um arquivo estável e verifica o layout, as duas datas do `mxif`,
o placar de `mham`, os IDs dos clubes e pelo menos 11 jogadores com minutos
registrados no snapshot Atlas. Requer uma única partida candidata na base.
Saves simultâneos com percentuais conflitantes para a mesma partida ficam sem
importação. Leituras repetidas não substituem uma evidência já registrada.

O comparativo da partida mostra a posse sempre que houver evidência válida do
save. A API expõe `savePossession` e o indicador `possession_pct` com origem
`fc26_save_mxif`, o hash do bloco e o snapshot usado no vínculo. A evidência
aparece desde o snapshot que identificou a partida e nos posteriores da mesma
temporada. O estado de cobertura do MatchStats continua descrevendo aquele
export. O `mxif` fornece o último jogo de cada save ainda disponível. Confira o
comparativo depois de salvar a carreira e importar o snapshot do jogo.
