# Relatórios mensais e consolidado da temporada

O serviço `atlas.monthly_reports.build_season_report(conn, career_id, season_index, snapshot_id)`
produz um dicionário estruturado, sem escrever no banco. `build_month_report(..., month)`
seleciona um mês `AAAA-MM` com partida concluída. A renderização Markdown fica em
`atlas.monthly_report_markdown`. No Atlas, **Season report → Evolução mensal**
mostra o consolidado e os meses da carreira, temporada e snapshot escolhidos,
incluindo partidas, jogadores, cobertura e evolução por setor.

Arquivos da implementação: `atlas/monthly_reports.py` (consulta e agregação),
`atlas/monthly_report_markdown.py` (apresentação),
`atlas/monthly_report_api.py` (projeção para a tela e download),
`atlas/server_http.py` (endpoint de leitura), `atlas/static/app.js` (interface),
`scripts/generate_monthly_reports.py` (CLI), `tests/test_monthly_reports.py`
(contratos de cálculo), este documento, a ligação no `README.md` e os Markdown
gerados em `docs/reports/plymouth-season-1-snapshot-94/`.

## Execução

Na interface, selecione a carreira e abra **Season report → Evolução mensal**.
Escolha a temporada, o snapshot de corte e o mês; **Toda a temporada** mostra
o consolidado. **Baixar Markdown** exporta exatamente o recorte visível.
**Atualizar dados** refaz a consulta, sem persistir o relatório. O endpoint
`GET /api/careers/{id}/sporting-reports?season_index={n}&snapshot_id={n}`
devolve JSON compacto; `month=AAAA-MM` limita o JSON a um mês e
`format=markdown` devolve `fileName` e `content` para download. O endpoint
abre o banco ativo em `mode=ro` e valida o vínculo carreira/temporada/snapshot
no serviço. O snapshot global do Atlas não muda ao examinar outro corte nessa aba.

### Geração por linha de comando

No diretório do repositório, escolha explicitamente o banco do workspace ativo,
carreira, temporada e snapshot. Exemplo validado para o Plymouth:

```powershell
py -3 -m scripts.generate_monthly_reports `
  --database "$env:LOCALAPPDATA\ProjectAtlasTracker\workspaces\ws_f5151a33099c\atlas_tracker.sqlite3" `
  --career 1 --season 1 --snapshot 94 `
  --out docs/reports/plymouth-season-1-snapshot-94
```

Adicione `--month 2026-01` para gerar apenas esse mês. A conexão SQLite usa
`mode=ro`. A execução completa escreve um índice, um consolidado e um Markdown
por mês com partida concluída. Para selecionar outra carreira ou snapshot, consulte
`careers` e `snapshots` no banco correspondente e passe os IDs encontrados.
Reexecutar com os mesmos argumentos sobrescreve os mesmos arquivos com conteúdo
determinístico, sem timestamp de geração.

## Fontes e regras

- `fixture_observations` e `fixtures` do snapshot selecionado definem a lista de
  jogos, data da carreira, competição, mando e placar. O fixture ID aparece uma vez;
  observações do mesmo jogo em snapshots anteriores não somam novos jogos.
  `competition_scope.competition_category` classifica a liga para o cálculo de pontos.
- `match_stats.detailed_match` escolhe o export completo, vinculado e elegível até
  a sequência de importação do snapshot. `metric_evidence.snapshot_fixture_evidence`
  preserva o estado e a origem da cobertura. Métricas avançadas e seus denominadores
  só vêm dos exports elegíveis; NPK-xG não inclui pênaltis. O xG total exibido é a
  derivação existente do Atlas: NPK-xG + 0,7 por pênalti cometido pelo adversário,
  quando há contexto para ambos os lados. Posse percentual não existe no export
  validado e fica `n/d`.
- `player_match_performances` fornece notas e minutos quando não há export; havendo
  export, a nota e minutagem dele têm precedência no mesmo jogo. O jogador e o
  fixture são deduplicados pela observação mais recente até o snapshot selecionado.
- `match_stats.aggregate_detailed_stats` soma contagens e calcula cobertura por
  campo. Indicadores por 90 usam apenas minutos dos exports com esse indicador.
  Médias de nota indicam o número de jogos avaliados. Amostra curta usa o limiar
  existente de `commission.assess_sample`.
- `match_stats.reconstruct_match_stats` atribui deltas oficiais por partida apenas
  quando exatamente um novo jogo foi concluído entre snapshots consecutivos.
  Totais acumulados de `season_stat_states` não são rateados entre meses e não são
  misturados aos exports para preencher faltas.
- `roster_states`, `player_states`, `youth_player_states` e `loan_states` dão vínculo,
  posição natural, GER, potencial e idade quando disponíveis no último snapshot
  do mês até o corte selecionado. O primeiro registro limita a presença do atleta
  nos meses anteriores; registros históricos preservam jovens e saídas.
- Divisão do adversário vem de `team_states` e `league_states` no snapshot
  selecionado. Divisão numericamente menor que a do clube é marcada como superior.
  É classificação cadastral, sem modelo de dificuldade de partida. Diferenças de
  elenco entre fechamentos mensais são mudanças cadastrais, não prova de transação.

## Caso de validação e cobertura

Em 21/11/2026, o banco do workspace `ws_f5151a33099c` continha o Plymouth
(`fc26v2-e7050151`, carreira 1), temporada 1, snapshot 94 de 03/02/2026.
O recorte contém 44 jogos únicos de julho de 2025 a janeiro de 2026, 40 exports
completos vinculados e 61 atletas vinculados à carreira, academia ou empréstimos durante o
período. [Índice dos relatórios gerados](reports/plymouth-season-1-snapshot-94/README.md).
Os 81 pontos de liga no consolidado são recalculados dos fixtures, pois o campo
de classificação armazenado não foi tomado como autoridade para esse total.

## Limitações

Quatro partidas não têm export detalhado elegível; suas métricas avançadas são
`n/d`. O recorte de notas/minutos pode ter cobertura diferente do export.
Titularidade, cronologia dos eventos, posição jogada sem proveniência confiável,
força excepcional de um adversário da mesma divisão e efeito causal de decisões
táticas não são reconstruídos. A tabela `transfer_market_events` não continha
eventos confirmados no banco validado; o relatório não converte mudança de elenco
em venda ou contratação. Meses do mesmo mês do snapshot selecionado são tratados
como parciais, pois ainda podem receber novos jogos ou correções.
O snapshot 94 tem `import_status=degraded` por aviso de lucratividade de equipes
fora da faixa esperada. Fixtures, notas e estatísticas da temporada foram
validados separadamente para este relatório.

Cobertura de escalações, eventos de mercado e MatchStats deve crescer nas fontes
do Atlas; o serviço mensal não mantém um motor paralelo para essas métricas.

## Verificação

```powershell
py -3 -m unittest tests.test_monthly_reports -v
```

Os testes exercitam recorte por snapshot, deduplicação de fixture, soma de liga,
comparação de GER e taxa por 90 calculada somente com minutos dos exports.
