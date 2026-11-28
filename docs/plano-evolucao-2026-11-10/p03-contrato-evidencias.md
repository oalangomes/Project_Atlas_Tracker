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
normal e no `--scan`. O [leitor](../../atlas/fc26_save_match.py) recebe os bytes
de um arquivo estável e confere o layout, as duas datas do `mxif` e os IDs e o
placar da partida mais recente no `mham`. O [importador](../../atlas/fc26_save_possession.py)
vincula uma única partida candidata na base com pelo menos 11 jogadores com
minutos registrados no snapshot Atlas.
Saves simultâneos com percentuais conflitantes para a mesma partida ficam sem
importação. Leituras repetidas não substituem uma evidência já registrada.

O comparativo da partida mostra a posse sempre que houver evidência válida do
save. A API expõe `savePossession` e o indicador `possession_pct` com origem
`fc26_save_mxif`, o hash do bloco e o snapshot usado no vínculo. A evidência
aparece desde o snapshot que identificou a partida e nos posteriores da mesma
temporada. O estado de cobertura do MatchStats continua descrevendo aquele
export. O `mxif` fornece o último jogo de cada save ainda disponível. Confira o
comparativo depois de salvar a carreira e importar o snapshot do jogo.

### Cobertura do extrator Sheffield e substituição do Live Editor

A conferência de Plymouth–Stevenage (fixture Atlas `1707`, export `53`) usou
dados binários do `CmMgr` e o MatchStats da mesma partida como controle. Com
a quantidade de slots do `mxif` lida do cabeçalho, os 30 participantes do
MatchStats foram encontrados no save. xG, chutes, chutes no alvo, passes,
passes certos, desarmes, passes-chave e faltas coincidiram para os 30 jogadores.
Essa partida não estabelece equivalência entre o xG do save e o NPK-xG em
jogos com pênaltis. O save também detalhou as enfiadas completas do Plymouth
em 32 por baixo e 3 por cima, além de 4 passes que romperam linhas, 4 pela
ponta e 6 tentativas de tabela.

O extrator do Hub gerou 66 tabelas em cada save. A execução completa terminou
no Sheffield e parou no `mflp` do Plymouth. O bloco Plymouth declara 30
registros, enquanto o Sheffield atual da amostra declara 36. O leitor original
assume 33. No primeiro par consecutivo do Sheffield, respeitar a contagem do
cabeçalho recuperou 11 titularidades e 16 aparições, diante de 9 e 14 com o
leitor fixo. No segundo par, o delta de titularidade não identificou titulares
mesmo com a contagem ajustada. A integração precisa validar os estados e os
deltas por partida, com `mham` comprovando a sequência.

Os próximos campos de alto valor são a decomposição dos passes e o estado de
participação do `mflp`. As tabelas de tática gravada, histórico do técnico,
lesão, pré-contrato e academia podem alimentar outras áreas após normalização
dos campos. Para substituir o snapshot Lua, falta materializar e reconciliar
os contratos do Atlas, em particular calendário global e estatísticas de
temporada por competição. Para substituir MatchStats, falta uma leitura
persistida validada de xA, pré-assistências, passes sob pressão, perdas de
posse, cartões e outros contadores avançados. A primeira migração pode usar o
save como fonte principal dos campos com paridade e conservar MatchStats como
fonte complementar. [Extrator do Hub](https://github.com/oalangomes/ea-fc-sheffield-hub/blob/master/scripts/fc26_save_extract.py) · [Contrato Atlas](../../schemas/FC26_CareerTracker_Snapshot_Contract_v1.2.0.json).

### Passes detalhados do save no Match Center

O [leitor de partidas do Atlas](../../atlas/fc26_save_match.py) reaproveita os
mapeamentos `mxif` e `mham` do Hub na revisão
`325481c596e05cca5cee15049012a216af16618d` sob a
[Unlicense](../../atlas/fc26_save_match.UNLICENSE). A revisão emitida em novos
registros é `atlas-fc26-match-v1`.

A quantidade de registros declarada nos dois blocos determina onde ficam os
jogadores, a identidade da partida e o limite de cada bloco. Os marcadores
seguintes confirmam os limites calculados. O leitor aceita outras contagens
quando os bytes seguem a estrutura conhecida, incluindo a divisão igual dos
slots de jogadores entre mandante e visitante. Os offsets de cada campo e os
tamanhos dos registros pertencem à versão do formato. Uma estrutura diferente
ou com evidência inconsistente fica indisponível. A seleção do jogo usa a
data, os clubes, o placar e os participantes lidos de cada carreira.

| Campo da API | Comparativo da partida |
| --- | --- |
| `through_passes_attempted`, `lobbed_through_passes_attempted` | Tentativas de enfiada rasteira e pelo alto |
| `through_passes_completed` | Enfiadas rasteiras completas |
| `lobbed_through_passes_completed` | Enfiadas pelo alto completas |
| `line_breaking_passes` | Passes que rompem linhas |
| `wing_passes` | Passes pela ponta |
| `one_two_attempted` | Tentativas de tabela |
| `one_two_completed`, `one_two_success_pct` | Tabelas completas e taxa de acerto |
| `lobbed_passes_attempted`, `lobbed_passes_completed` | Passes pelo alto tentados e completos |
| `set_piece_passes_attempted`, `set_piece_passes_completed` | Passes de bola parada tentados e completos |

Para enfiadas rasteiras e pelo alto, passes pelo alto e passes de bola parada,
o comparativo exibe a taxa `100 × completos ÷ tentados`, com uma casa decimal.
A API e a área **Cobertura e proveniência** registram a taxa como derivada,
com os dois campos de origem. A API mantém a taxa ausente quando faltam
tentativas, acertos ou um denominador positivo. Nas linhas exibidas do
comparativo, a interface mostra 0% para o lado sem valor. Zero acertos em
tentativas registradas produz 0% também na API.

O detalhe da partida expõe `savePasses.home` e `savePasses.away` e mostra a
decomposição de passes no comparativo normal de **Estatísticas da partida**.
O comparativo funciona também com dados exclusivamente do save. A origem é
identificada em **Cobertura e proveniência**. A API registra a revisão do leitor,
o hash `mxif` e o snapshot do vínculo. Totais gerais, precisão, passes-chave
e cruzamentos continuam no contrato já existente do MatchStats. Zero
publicado indica um valor lido no save. Valores inválidos ou indisponíveis
permanecem ausentes.

O Atlas publica tabelas completas quando o valor é menor ou igual ao de
tentativas e a porcentagem inteira gravada no save corresponde à divisão
truncada de acertos por tentativas. A taxa da ficha usa uma casa decimal.
Nos saves reais consultados, todas as tentativas observadas resultaram em
acertos. A regressão de quatro acertos em seis tentativas usa dados sintéticos.

Na primeira varredura da versão atualizada, `fc26_save_passes` recebe os
campos ligados à posse. Uma posse já gravada ganha os passes quando o mesmo
bloco `mxif` ainda estiver disponível. Saves que divergem nos passes da mesma
partida ficam sem nova publicação desses campos. A releitura do mesmo bloco
acrescenta campos novos às observações históricas e é idempotente. A cobertura
depende dos saves disponíveis localmente, pois cada `mxif` fornece uma partida
concluída.

Em 27/11/2026, o leitor foi executado nos saves reais de Plymouth e Sheffield.
Em base isolada, o endpoint e o navegador exibiram os passes de Plymouth–
Huddersfield com o save real e sem MatchStats. Da esquerda para a direita,
o comparativo mostrou 30–30 nas enfiadas rasteiras, 3–3 pelo alto, 5–3 nos
passes que rompem linhas, 11–4 nos passes pela ponta e 1–0 nas tentativas de
tabela. O caso Plymouth–Stevenage é coberto por regressão sintética com os
valores registrados na investigação anterior.

#### Tipos de passe por jogador

A ficha expansível de cada jogador nas **Atuações** exibe, em **Passes e
criação**, enfiadas rasteiras e pelo alto completas, passes pelo alto
completos, passes de bola parada completos e passes rasteiros completos.
O contador de passes rasteiros segue o campo do save. O Atlas testa seu
limite pelo total individual de passes completos e pela conciliação desse total
com a equipe. A relação entre rasteiros e enfiadas segue sem validação de
abrangência. Os dois campos são apresentados separadamente.
O leitor fornece os campos por ID EA. Para os demais recortes, o Atlas valida
cada métrica
pela soma dos jogadores da equipe e só a associa a uma atuação confirmada
com o mesmo lado da partida. Nos passes pelo alto e de bola parada completos,
a publicação dos valores coletivos e individuais também exige que o total de
passes completos dos jogadores coincida com o da equipe. A confirmação de
atuação pode vir dos minutos registrados
no snapshot do clube gerenciado ou dos participantes do MatchStats. Assim,
os jogadores com atuação confirmada podem receber os campos mesmo quando
o MatchStats estiver ausente. Uma posição no banco do save sozinha não gera
uma atuação.

O detalhe da partida retorna `performances[].savePasses` para atuações
elegíveis. A fonte inclui revisão, hash `mxif` e snapshot do vínculo. O
valor zero permanece distinguível de um campo indisponível. A tabela
`fc26_save_player_passes` é preenchida na varredura normal, inclusive para
partidas com passes coletivos já importados quando o bloco de origem ainda
estiver disponível.

#### Comparação opcional com o Live Editor

`ATLAS_SAVE_PASSING_COMPARISON=1` no processo do Atlas ativa a coleta de
campos que já têm equivalente no MatchStats. A opção começa desativada.
Ela pode ser habilitada em uma sessão PowerShell com
`$env:ATLAS_SAVE_PASSING_COMPARISON = '1'` antes de iniciar o Atlas. Para voltar
ao padrão, retire a variável dessa sessão e reinicie o Atlas.

A leitura inclui passes tentados e completos, passes-chave, cruzamentos,
passes interceptados, passes para impedimento e enfiadas completas agregadas.
As taxas usam o mesmo cálculo de acertos sobre tentativas do MatchStats.
Os cruzamentos por jogador e os cruzamentos completos por equipe exigem
conciliação com os registros individuais. Interceptações de passe e passes
para impedimento por equipe são a soma dos jogadores quando os totais de passe
da equipe conciliam. Campo sem evidência suficiente fica ausente.

A conclusão de uma varredura com a opção ligada pode acrescentar evidência à
tabela `fc26_save_passing_comparison` enquanto o bloco de origem estiver
disponível. `GET /api/snapshots/{snapshotId}/matches/{fixtureId}` expõe
`savePassingComparison` com os valores `careerFile` e `liveEditor` lado a lado.
A ficha mostra esses mesmos valores em **Cobertura e proveniência → Comparação
de fontes dos passes**, com as duas equipes e a lista expansível de jogadores.
A comparação individual exige o mesmo ID e o mesmo clube no MatchStats
vinculado. Com a opção desligada, o comparativo fica fora da API e a coleta
para. O MatchStats segue como fonte das métricas normais da aplicação.

Em uma instância isolada, Wycombe–Plymouth (fixture `357224`, export `55`)
forneceu as dez métricas pelos dois lados, todas com os mesmos valores, e 28
jogadores com vínculo individual. A conferência cobriu a API antes de ativar,
com a opção ativa e depois de desativar. O resultado coletivo vale para essa
partida e serve de referência para novas comparações.

#### Comparação opcional de finalizações e defesa

`ATLAS_SAVE_SHOOTING_DEFENDING_COMPARISON=1` no processo do Atlas ativa a
coleta adicional. Ela começa desligada e pode ser usada independentemente
da comparação de passes. A ficha mostra os valores em **Cobertura e
proveniência → Comparação de finalizações e defesa** quando houver evidência.
A API de detalhe expõe `saveShootingDefendingComparison` com os campos
`careerFile` e `liveEditor` por equipe e por jogador vinculado ao mesmo lado.

| Recorte | Campos |
| --- | --- |
| Equipe | Finalizações, finalizações no alvo, bloqueios defensivos, cortes, duelos aéreos ganhos e defesas do goleiro |
| Jogador | Finalizações, finalizações no alvo, finalizações para fora, finalizações bloqueadas, bloqueios defensivos, cortes e duelos aéreos disputados e ganhos |

Finalizações bloqueadas por jogador são calculadas com `total − no alvo −
para fora`, quando os três contadores do `mxif` são coerentes. Um campo
indisponível permanece ausente para a origem correspondente. A coleta
acrescenta um grupo ao JSON da linha de auditoria já existente, na tabela
`fc26_save_passing_comparison`, sem exigir outra tabela. A adição exige
o mesmo bloco `mxif` que validou a partida e preserva o conteúdo de passes
já gravado. O comparativo é de auditoria. Os indicadores normais e o xG
continuam nos contratos preexistentes.

Na validação isolada de Wycombe–Plymouth (fixture `357224`, export `55`), os
seis valores de cada equipe e os oito valores de cada um dos 28 jogadores
vinculados coincidiram. Na ficha, o Plymouth mostrou 17 finalizações nas
duas fontes. Owen Oseni mostrou duas finalizações, ambas no alvo, nas duas
fontes. O resultado descreve apenas essa partida.

#### Preenchimento opcional de finalizações e defesa pelo arquivo da carreira

`ATLAS_SAVE_SHOOTING_DEFENDING_FALLBACK=1` no processo do Atlas ativa esse
preenchimento na ficha de partidas sem MatchStats elegível. A opção começa
desligada e independe dos comparativos de auditoria. Ela reutiliza a mesma
linha de evidência do `mxif`, inclusive quando a varredura ainda precisa
importar os campos. Um MatchStats elegível segue como fonte principal e
preenche a ficha por inteiro assim que chega.

O preenchimento inclui finalizações, finalizações no alvo, bloqueios
defensivos, cortes e duelos aéreos ganhos. Para cada lado e métrica, o total
registrado pela equipe deve coincidir com a soma dos jogadores do save.
Finalizações no alvo exigem também a conciliação das finalizações totais.
As linhas individuais exigem atuação, minutos e lado confirmados no snapshot
do clube gerenciado. A API de detalhe expõe `saveShootingDefendingFallback`
para os times e `performances[].saveShootingDefending` para os jogadores
elegíveis, com a origem do dado. O cálculo de xG, a cobertura histórica e
os agregados de temporada conservam o contrato atual.

Na conferência binária, os cinco campos conciliaram nos 14 lados de sete
saves distintos. Só Wycombe–Plymouth também tinha MatchStats vinculado.
Defesas do goleiro permaneceram na auditoria, pois a comparação entre defesas,
chutes no alvo e gols foi inconclusiva em quatro lados da amostra.

Em uma instância isolada de Wycombe–Plymouth, o navegador mostrou 2 a 17
finalizações por equipe e `2/2` na linha de Owen Oseni, com a origem do
arquivo da carreira. Após importar o MatchStats real na base de teste, a
API voltou a usar o export vinculado e recolheu o preenchimento opcional.

#### Participação do clube gerenciado

O [leitor de participação](../../atlas/fc26_save_participation.py) usa a
contagem declarada no `mflp` e confirma o limite do bloco pelo marcador
`mglp`. O bloco registra a equipe gerenciada, a condição de titular ou
reserva utilizado, a posição, os minutos internos e o minuto interno de
entrada. O Atlas verifica o lado no `mxif`, os 11 titulares e a coincidência
do conjunto completo de IDs e minutos com a observação do jogo no snapshot.
Quando houver posição confirmada do último jogo no snapshot, o leitor também
exige que as duas posições coincidam. Um código desconhecido ou um vínculo
inconsistente mantém essa evidência indisponível.

As atuações elegíveis trazem `performances[].saveParticipation` com a origem
`fc26_save_mflp`, os hashes dos blocos e o snapshot do vínculo. Na ficha, a
seção **Participação na partida** mostra o papel e os minutos internos do
atleta. Um pareamento de substituição exige um único jogador de entrada e
um único de saída na mesma posição registrada e no mesmo minuto interno.
O vínculo é uma derivação dos registros e a tela identifica o seu método.
Contadores de carreira, como titularidades acumuladas e assistências, ainda
dependem de uma sequência comprovada de dois saves.

Em Wycombe–Plymouth, o arquivo real e o snapshot vinculado conciliam os 16
jogadores do Plymouth, com 11 titulares e cinco reservas utilizados. Os cinco
pareamentos por posição e minuto aparecem na API. O navegador exibiu a taxa
de bola parada de 0% a 50%, a atuação de Owen Oseni e a comparação das fontes.

#### Feed da carreira na Linha do tempo

O [leitor do feed](../../atlas/fc26_save_feed.py) adapta o mapeamento do Hub
em `af13616bf3f4e0d98cb17f95cf21edcc46420e69`. A leitura registra as chaves
de notícias e publicações no `mcos` e de conversas no `mvlp`. A
**Linha do tempo → Feed da carreira** mostra as categorias, a contagem de
ocorrências e os códigos do jogo. As ocorrências são chaves, incluindo
partes de mensagens e opções de resposta.

Uma partida vinculada identifica a carreira do arquivo. A varredura escolhe
o arquivo elegível mais recente pela última partida e pela modificação do
arquivo. O registro se torna visível a partir do snapshot mais recente da
carreira no momento em que o Atlas o observa. O snapshot indica o recorte
de leitura. Os códigos ficam fora dos eventos datados da Linha do tempo.
O Atlas guarda uma linha por snapshot em `fc26_save_career_feed` e expõe o
registro mais recente elegível em `saveCareerFeed` no endpoint da cronologia.

A verificação em uma instância isolada usou dois saves reais e vínculos
montados a partir dos registros de partida. O navegador exibiu cinco passes
rasteiros completos para Bradley Ibrahim contra o Bradford City, três tabelas
completas e 100% de acerto para o Sheffield United contra o Crystal Palace e
135 chaves no feed do Plymouth (9 de notícias, 25 de publicações e 101 de
conversas). Uma taxa de 66,7% com quatro acertos em seis tentativas foi
verificada por teste automatizado. Os saves da amostra tinham 100% de acerto
sempre que havia tentativas de tabela.

#### Tática gravada e limite da leitura de torneios da base

O [leitor da carreira](../../atlas/fc26_save_career_setup.py) usa o diretório
e os campos das tabelas embutidas no save. Ele adapta o mecanismo de leitura
do Hub em `325481c596e05cca5cee15049012a216af16618d`. Uma partida concluída
vinculada pelo importador identifica a carreira e o snapshot. O clube
gerenciado gravado em `mPrV` precisa coincidir com o clube do snapshot.
Uma linha em `fc26_save_career_setup` registra a tática. A leitura do
painel exige o snapshot exato, sem carregar o estado
gravado para outros cortes. Dois arquivos empatados por modificação e com
conteúdo divergente ficam fora da importação daquele corte.

- **Elenco → Tática gravada** mostra as escalações personalizadas (`zdMM`)
  e os presets (`emmj`) associados por clube e identificador interno. Abre
  o XI e as posições gravadas quando todos os jogadores são identificados
  no elenco do corte. A posição de cada vaga usa a correspondência dos
  campos das formações, conferida com os 11 pares jogador/posição do XI do
  Plymouth no snapshot 119. As posições são da configuração do treinador.
  Os códigos de nome da formação, funções e instruções ainda precisam de
  calibração. Um nome livre, como `3421`, permanece o nome do preset.

No save vinculado ao Bradford City–Plymouth em 28/03/2026, o leitor retornou
duas escalações e dez presets.

O Atlas não usa `TcEm` como fonte de resultados da base. No corte de
29/03/2026, os números de `TcEm` coincidem com o bloco `mflp` profissional
do mesmo save e com os totais da EFL League One e da Vertu Trophy no Atlas.
Alisson Bueno soma 9 jogos e 6 gols, Flávio Brandao 7 jogos e 1 gol, e
Miloš Stepanović 1 jogo e 0 gols. O teste controlado do Hub em um torneio
5x5 também observou que `TcEm` permaneceu igual antes e depois da partida.
O leitor de tática ignora contadores que versões anteriores possam ter
gravado no mesmo registro. [Teste do torneio no Hub](https://github.com/oalangomes/ea-fc-sheffield-hub/blob/325481c596e05cca5cee15049012a216af16618d/docs/fc26-youth-5x5-reverse-checkpoint-2026-08-22.md#embedded-db-changes)
