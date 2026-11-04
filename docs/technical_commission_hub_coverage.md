# Atlas Technical Commission — Sheffield Hub coverage

Audit reference: `oalangomes/ea-fc-sheffield-hub` at commit `60c77b85ee528fca11678f5f83aaa6271ae71f2e` (2026-11-03). This is an incremental Atlas integration; the Hub is a metric reference, not a second runtime.

## Coverage matrix

| Hub concept / source | Atlas evidence | Atlas treatment in this increment | Coverage |
|---|---|---|---|
| Sample policy: 300+ minutes and 3+ valid appearances; reliable at 450+ and 5+ | `player_match_performances` minutes/rating; linked MatchStats goals/assists | Same thresholds and sample labels. Valid appearances use 15+ recorded minutes or a linked goal/assist. Atlas does not export starter status, so a low-minute starter cannot be identified. | Partial; threshold parity, input difference disclosed |
| Season and last-five rating, weighted by minutes | Rating history ordered by date/fixture | Season and recent rating use valid appearances only; last five valid appearances are minute-weighted. Missing ratings do not become zero. | Covered for available rows |
| Hierarchy separate from form and recommendation | No reliable squad hierarchy/status field in the selected career export | Hierarchy stays N/D. Form and deterministic recommendation remain separate; recommendations do not promote or demote a player. | Hierarchy unavailable |
| Role/function comparison | Registered position plus match position when source provenance is reliable | Atlas compares registered position to observed match-position groups. The Hub's finer functional subgroups, position-specific event attribution and starter/reserve minutes require function-by-player exports that Atlas does not currently have. | Partial |
| Defensive-player context (`gerar_defesa_por_jogador.py`) | Player minutes, team xGA, opponent shots/on-target, goals against | Could support a minutes-weighted exposure estimate. It is not presented as an individual defensive action or causal player contribution in this increment. | Not exposed in Commission yet |
| Goalkeeper context (`gerar_goleiros_profissional.py`) | MatchStats saves/ratings; team goals against, opponent shots/on-target and xGA; recorded positions | Match-level player card shows direct saved player facts. A season goalkeeper index needs reliable keeper identity/minutes per match and is not calculated here. Swapped-keeper matches must remain indeterminate. | Partial; no keeper index |
| Team style/control (`gerar_metricas_profissional.py`) | Linked team MatchStats: passes, pass accuracy, shots, NPK-xG, dribbles, crosses, through passes, tackles/interceptions | Deterministic per-match aggregates power the team identity page; Ollama describes only those aggregates. Possession percentage, pressing, line height and tactical instructions remain N/D unless exported. | Partial, evidence-limited |
| Opponent difficulty/facility profiles | Opponent team shots and recorded results from completed linked exports | Descriptive lower/upper opponent-shot-volume cohorts; each cohort requires at least five observations. Labels describe observed points and goal difference only, not opponent style or causation. | Partial, descriptive only |
| Functional rival and recommended XI (`comissao_tecnica_core.py`) | Player positions/minutes/ratings; no persisted Atlas hierarchy or Hub-style live squad roster | No Hub-style XI or decisive rival recommendation is generated. A positional map shows only match-specific recorded positions and never claims starters or formation. | Unavailable in this increment |
| Formation, load and fixture preparation | Squad positions, recent recorded minutes, fixture calendar | Existing Ollama preparation can choose only among deterministic shapes supported by the registered squad and must cite facts. The match page does not infer the formation used. | Partial |
| Goal/assist by role (`nota_posicao_funcao_core.py`) | MatchStats events and, where available, actual position | Match player reports cite individual MatchStats. Atlas does not yet attribute goals/assists to time-sliced roles; no role-specific event split is inferred. | Partial |

## Provenance boundaries

- Extracted: FC26 MatchStats fields already linked to an Atlas career, plus rating/minute/position history.
- Derived: per-match rates, sample labels, team aggregates, and descriptive opponent-shot cohorts. Derived values retain the source coverage and do not fill missing data.
- Unavailable: starter/reserve designation, saved hierarchy/status, time-sliced role minutes, possession share where not exported, and tactical instructions. These display as N/D or are omitted.
- Professional and youth 5x5 remain separate. No Lua change is required for this increment.

## Cache and import behavior

Ollama reports are stored in the existing `technical_commission_report_cache` table, scoped by career, report type, match/player/season, model and a hash of source facts. Identical facts reuse a saved report across snapshots; changed facts produce a new report. Match and team reports are queued only for newly completed fixtures or newly linked MatchStats. Existing history is not bulk-sent to Ollama on application startup. Player reports remain on demand. Offline Ollama leaves Atlas facts available and can be retried later.

## Hub files audited

- `scripts/politica_amostra_esportiva.py`
- `scripts/funcoes_esportivas.py`
- `scripts/gerar_metricas_profissional.py`
- `scripts/comissao_tecnica_core.py`
- `scripts/gerar_goleiros_profissional.py`
- `scripts/gerar_defesa_por_jogador.py`
- `scripts/nota_posicao_funcao_core.py`
- `docs/criterios-metricas-profissional.md`
- `docs/comissao-tecnica.md`

