# Auditoria de armazenamento do Atlas

Data da medição: 2026-11-16. Escopo: código desta árvore e banco da carreira em
`%LOCALAPPDATA%/ProjectAtlasTracker/workspaces/ws_f5151a33099c/atlas_tracker.sqlite3`.
Não foi encontrado `AGENTS.md` nesta árvore. O SQLite original foi aberto apenas
com `mode=ro` e `PRAGMA query_only=ON`. Não houve migração, `VACUUM` nem mudança
no esquema de produção. As alterações neste repositório são somente o protótipo,
seus testes e este relatório.

A [medição das consultas interativas](atlas-read-performance.md) cobre o Elenco,
a Análise e a Comissão Técnica no workspace ativo em 26/11/2026.

## 1. Fluxo confirmado pelo código

| Etapa | Implementação e efeito |
| --- | --- |
| Entrada | `HotFolderWatcher.scan_once` identifica pacotes prontos e chama `SnapshotImporter.import_ready_root` (`atlas/watcher.py:43-70`, `atlas/importer.py:124-148`). |
| Validação e transação | `SnapshotImporter.import_validated` rejeita `external_snapshot_id` ou `content_hash` já importado e, numa transação, cria o snapshot, importa arquivos e recalcula a sequência (`atlas/importer.py:159-188`). O hash impede reimportação do *pacote inteiro*, não reutiliza linhas iguais entre pacotes. |
| Fato importado | `_import_core_files` lê todos os `players.csv`, grava `player_states` por snapshot, inclusive colunas extraídas e `raw_json` completo (`atlas/importer.py:326-358`). A chave é `(snapshot_id, ea_player_id)` (`atlas/db.py:101-120`). |
| Simulação mundial | `WorldSimulationService.ensure_snapshot` retorna se há execução com `MODEL_ID`; caso contrário apaga os resultados daquele snapshot, lê jogadores/elencos/tabelas e grava `atlas_simulated_player_stats` e `atlas_world_simulation_runs` (`atlas/world_simulation.py:559-590`, `atlas/world_simulation.py:843-922`). Chave dos resultados: `(snapshot_id, player_ea_id, league_ea_id)` (`atlas/db.py:1006-1030`). |
| Estado dinâmico | `PlayerDynamicsService.ensure_snapshot` primeiro garante a simulação mundial, depois garante recursivamente o snapshot anterior da mesma temporada, consulta fatos e simulações e grava um `player_dynamic_states` para cada jogador (`atlas/player_dynamics.py:595-680`, `atlas/player_dynamics.py:683-735`, `atlas/player_dynamics.py:967-974`). A chave é `(snapshot_id, player_ea_id)` (`atlas/db.py:945-969`). |
| Leitura | `analyze` lê o estado dinâmico e decodifica os dois JSONs (`atlas/player_dynamics.py:976-1005`). `scouting_board` lê os estados ordenados e decodifica `stats_json` de cada candidato, além de `breakdown_json` dos itens exibidos (`atlas/player_dynamics.py:1021-1086`). A análise financeira chama `analyze` (`atlas/player_finance.py:244-252`). |
| Endpoints | Perfil do jogador e clube chamam `ensure_snapshot` e consultam `player_states` e estatísticas simuladas; rotas em `atlas/server_http.py:336-355`, consultas em `atlas/server_query_entities.py:392-447` e `atlas/server_query_entities.py:732-782`. Competições chamam `simulated_leagues` (`atlas/server_query_competitions.py:141-148`); a liga chama `league_table` (`atlas/server_http.py:353-355`, `atlas/world_simulation.py:955-998`). |

**Outros consumidores diretos de `player_states`:** comparação e histórico
(`atlas/server_query_history.py:26-35`, `atlas/server_query_history.py:420-428`),
análise e dashboard (`atlas/server_query_analysis.py:170-176`,
`atlas/server_query_dashboard.py:185-198`), comissão técnica
(`atlas/commission.py:669-670`, `atlas/commission.py:1223-1226`), dados financeiros
e manuais (`atlas/financial.py:342-354`, `atlas/manual_data.py:182-190`),
MatchStats (`atlas/match_stats.py:460-463`, `atlas/match_stats_importer.py:446-449`),
força da equipe (`atlas/team_strength.py:18-39`) e filtros de apresentação
(`atlas/settings.py:169-174`). A tabela também é consultada por
`atlas/dynamic_revenue.py:604-608`, `atlas/media_sources.py:407-407`,
`atlas/server_query_management.py:28-30` e
`atlas/server_query_matches.py:139-142`. `match_competitive_context` verifica a
existência da tabela (`atlas/match_competitive_context.py:60-65`). Por isso uma eventual
normalização de `player_states` exigirá compatibilidade ampla de consultas.

**Consumidores diretos de `atlas_simulated_player_stats`:** agregação para o
modelo dinâmico (`atlas/player_dynamics.py:153-199`), perfil e líderes de clube
(`atlas/server_query_entities.py:407-410`, `atlas/server_query_entities.py:762-782`),
liga e consulta de estatísticas simuladas (`atlas/world_simulation.py:982-998`,
`atlas/world_simulation.py:1120-1130`). `player_dynamic_states` é produzido e
lido diretamente em `atlas/player_dynamics.py:595-1086`; os endpoints o alcançam
pelos serviços, especialmente `atlas/server_query_entities.py:392-393` e
`atlas/player_finance.py:244-252`.

## 2. Tempo, aleatoriedade e invalidação

- **Dependência temporal confirmada:** o modelo dinâmico encontra o snapshot
  anterior por `import_sequence` dentro da temporada e o calcula primeiro;
  usa `dynamic_delta` e `breakdown_json` anteriores para suavização e
  recuperação (`atlas/player_dynamics.py:597-619`,
  `atlas/player_dynamics.py:653-679`, `atlas/player_dynamics.py:814-818`,
  `atlas/player_dynamics.py:888-915`). Não é seguro descartar um estado histórico
  só porque o `players.csv` atual é igual.
- **Aleatoriedade determinística confirmada:** a camada dinâmica usa SHA-256
  com `NOISE_SEED_ID`, `external_snapshot_id`, jogador e canal
  (`atlas/player_dynamics.py:18-19`, `atlas/player_dynamics.py:108-111`,
  `atlas/player_dynamics.py:683-683`). A simulação mundial usa SHA-256 e
  `random.Random` com `MODEL_ID` e sementes de carreira/temporada/liga/equipe,
  entre outras (`atlas/world_simulation.py:18-32`,
  `atlas/world_simulation.py:776-776`, `atlas/world_simulation.py:874-874`). Mesmo
  quando os fatos atuais coincidem, a trajetória dinâmica pode mudar.
- **Versionamento confirmado:** os identificadores atuais são
  `atlas-dynamic-performance-v12` e `atlas-world-simulation-v6`
  (`atlas/player_dynamics.py:18-19`, `atlas/world_simulation.py:18-18`). A camada
  mundial valida apenas `model_version` na tabela de execução, e a dinâmica
  verifica contagem de jogadores com o modelo vigente
  (`atlas/world_simulation.py:559-570`, `atlas/player_dynamics.py:600-610`). Não há
  impressão digital de todas as entradas nessa decisão.
- **Risco de invalidação confirmado pelo código, impacto ainda não testado:**
  mudar a visibilidade apaga `atlas_world_simulation_runs`
  (`atlas/settings.py:94-108`); a próxima leitura refaz a simulação mundial,
  enquanto `ensure_snapshot` dinâmico pode retornar pela contagem/modelo já
  existente (`atlas/player_dynamics.py:595-610`). Uma futura reutilização de
  cache exigirá versionar também entradas, configuração e dependências anteriores.

## 3. Problemas comprovados no SQLite original

`PRAGMA page_size=4096`, `page_count=3427154`, `freelist_count=0` e
`journal_mode=wal` na leitura. Arquivo principal: **14.037.622.784 bytes
(13,07 GiB)**; 80 snapshots importados, até 2026-01-02. Não havia WAL lateral
no diretório no momento da inspeção. `dbstat` foi executado por APSW 3.54.1.0
em modo somente leitura, porque o `sqlite3` do Python instalado não inclui
`ENABLE_DBSTAT_VTAB`.

Consultas de auditoria reproduzíveis numa conexão somente leitura (a última
requer `dbstat`):

```sql
PRAGMA page_size;
PRAGMA page_count;
PRAGMA freelist_count;
PRAGMA journal_mode;
SELECT name, SUM(pgsize) AS bytes FROM dbstat GROUP BY name ORDER BY bytes DESC;
SELECT name, pagetype, COUNT(*) AS pages, SUM(unused) AS unused_bytes
FROM dbstat
WHERE name IN ('player_dynamic_states', 'player_states', 'atlas_simulated_player_stats')
GROUP BY name, pagetype;
```

| Objeto `dbstat` | Bytes | % do arquivo | Linhas |
| --- | ---: | ---: | ---: |
| `player_dynamic_states` | 6.841.069.568 | 48,7% | 1.665.990 |
| `player_states` | 3.508.260.864 | 25,0% | 1.708.714 |
| `atlas_simulated_player_stats` | 1.895.157.760 | 13,5% | 1.384.567 |

As três tabelas somam **87,2%** do arquivo, sem contar seus índices. Em suas
páginas folha, `dbstat.unused` soma **3.921.572.093 bytes**; a tabela dinâmica
usa 1.665.990 páginas folha para 1.665.990 linhas. Esse `unused` é folga
*dentro de páginas ocupadas*, diferente de `freelist_count`. Um `VACUUM` com a
mesma página e o mesmo layout não tem redução equivalente garantida.

Comparação completa das colunas semânticas de snapshots adjacentes, excluindo
`snapshot_id` e, para derivados, identificador interno e timestamps:

| Tabela | 81 contra 80 | 80 contra 79 |
| --- | ---: | ---: |
| `player_states` | 21.373 / 21.373 iguais | 20.927 / 21.373 iguais |
| `atlas_simulated_player_stats` | 17.728 / 17.728 iguais | 17.479 / 17.728 iguais |
| `player_dynamic_states` | 5.880 / 21.373 iguais | 5.444 / 21.373 iguais |

Isso comprova potencial de reutilização de fatos e resultados mundiais, mas
também mostra por que **reutilização automática dos estados dinâmicos com base
apenas em `player_states` seria incorreta**. O banco pode mudar após esta
medição; estes números descrevem somente o arquivo observado nesta data.

## 4. Protótipo isolado: compactação sem perda dos JSONs dinâmicos

`scripts/storage_codec_prototype.py` abre a origem com `mode=ro` e copia por
lotes somente os snapshots selecionados para dois SQLite temporários. Ambos
mantêm as colunas e os dois índices relevantes de `player_dynamic_states`;
um armazena os JSONs em `TEXT`, o outro em `BLOB` com zlib nível 6. O protótipo
não altera consultas nem esquema do Atlas: representa o custo potencial de
uma futura camada de codec. Não replica FKs externas nem o restante do banco.

Ensaio executado com todos os estados dinâmicos dos snapshots **1, 40 e 81**
(início, meio e fim dos dados disponíveis), `page_size=4096`. Todos os
**64.082 registros** foram comparados coluna por coluna após descompactação;
ambas as bases temporárias passaram em `PRAGMA quick_check`.

| Medida executada | Texto, layout atual | JSONs compactados | Diferença |
| --- | ---: | ---: | ---: |
| Arquivo temporário, com índices | 266.973.184 B | 96.575.488 B | **−63,83%** |
| Carga dos três snapshots, uma execução | 6,906 s | 6,318 s | −0,588 s |
| 300 buscas pontuais + parse JSON, mediana de 5 | 26,196 ms | 30,869 ms | +4,673 ms |
| Leitura/parse de todo o snapshot anterior, mediana de 5 | 509,233 ms | 694,608 ms | +185,375 ms |
| 300 linhas ordenadas de quadro + parse, mediana de 5 | 6,513 ms | 9,950 ms | +3,437 ms |

As consultas temporárias reproduzem os padrões essenciais de ponto, estado
anterior e quadro de `atlas/player_dynamics.py:669-679`,
`atlas/player_dynamics.py:976-990` e `atlas/player_dynamics.py:1021-1050`.
**Não são medições ponta a ponta dos endpoints**: não incluem joins com
`player_states`, cálculos do modelo, rede ou renderização. O quadro temporário
limita o SQL a 300 linhas, enquanto o método atual busca todas antes de
selecionar até 300 (`atlas/player_dynamics.py:1033-1059`). A carga foi medida
uma vez, sujeita à variação de cache de disco. As leituras tiveram aquecimento
e cinco repetições; o aumento de 185 ms na varredura completa precisa ser
avaliado no fluxo real antes de qualquer adoção.

Para reproduzir o ensaio, com o caminho da carreira desejada:

```powershell
py -3 -m unittest tests.test_storage_codec_prototype -v
py -3 scripts/storage_codec_prototype.py --database "<caminho-do-atlas_tracker.sqlite3>" --snapshots 1 40 81
```

As bases de comparação ficam em um diretório temporário e são removidas ao
fim. O código lê no máximo 500 linhas da origem por lote; nunca copia nem
carrega os 13 GiB completos em memória.

## 5. Recomendação e limites

**Recomendação arquitetural:** estudar um codec versionado e sem perda para
`stats_json`/`breakdown_json` de `player_dynamic_states`, preservando todas as
linhas e chaves de snapshots, as colunas numéricas indexadas e a versão do
modelo. O protótipo demonstra redução expressiva nesse recorte sem perda de
dados. A implementação de produção precisaria de leitura retrocompatível,
tratamento explícito de BLOBs inválidos e migração reversível a partir de
backup consistente. Nada disso foi aplicado aqui.

**Hipóteses não validadas:** economia percentual no banco completo ou em dez
temporadas; impacto ponta a ponta na UI; benefício de páginas de 8/16 KiB;
vantagem de zstd ou outro codec; economia de normalização temporal de
`player_states` e `atlas_simulated_player_stats`. A repetição observada torna
essas opções candidatas, mas exige ensaios próprios. O esquema de versões
precisaria reconstruir exatamente o estado de qualquer `snapshot_id` e cobrir
todos os consumidores SQL listados acima. Não se deve descartar ou regenerar
estados dinâmicos históricos com uma chave de cache que ignore o snapshot
anterior, as sementes, as configurações e o `MODEL_ID`.
