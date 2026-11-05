# Atlas Technical Commission — Sheffield Hub coverage

Audit reference: `oalangomes/ea-fc-sheffield-hub` at commit `60c77b85ee528fca11678f5f83aaa6271ae71f2e` (2026-11-03). Hub calculations are references for incremental integration, not a second runtime.

## Coverage matrix

| Hub concept / source | Atlas evidence | Current treatment | Coverage / limit |
|---|---|---|---|
| Sample policy and last-five form | `player_match_performances`, linked MatchStats | Retains 300+ min/3 appearances usable, 450+ min/5 reliable; last five valid individual appearances weighted by minutes | Threshold parity; no reliable starter flag, so short starters cannot be identified |
| Season/last-five player performance | Rating and MatchStats by fixture, selected career/snapshot | Match report receives up to five valid prior MatchStats appearances and evidence counts | Partial where exports are missing |
| Collective season and recent references | Linked team exports, fixtures, snapshot import sequence | Match report receives all eligible pre-date exports, last-five averages, venue split and per-metric counts | Descriptive only; temporal order must be present in fixture dates |
| Hierarchy separate from form/recommendation | No reliable formal hierarchy source | Hierarchy stays N/D; rating/minutes never imply rank | Unavailable |
| Position and function comparisons | Registered position; trusted `actual_position` provenance | Separate nominal peers from recorded observed position; no tactical role asserted from CM/CB etc. alone | Partial; no role-specific per-period event attribution |
| Defensive-player context | MatchStats actions, team exposure, minutes | Direct actions can be interpreted with source coverage; no individual causal defensive index is inferred | Partial |
| Goalkeeper context | Saves, rating, goals conceded, shots faced, recorded position | Match-level direct fields remain available | No season index if keeper identity/minutes or swaps are ambiguous |
| Team style/control | Pass, shot, xG, dribble, cross, through-pass, duel and defensive metrics | Existing deterministic team profile and Match Intelligence reused; LLM may contextualize references | Possession share, pressing, line height and instructions remain unavailable unless exported |
| Opponent difficulty/facility profile | Opponent shots and recorded results | Existing descriptive cohorts require minimum observations and do not imply opponent style or cause | Partial, descriptive only |
| Functional rival / recommended XI | Player positions, minutes, ratings | No hierarchy or XI invented; next-match shape proposals remain limited to deterministic roster-position counts | Unavailable beyond data-supported options |
| Goal/assist by role | MatchStats events and sometimes observed position | Match/player reports use cited records; no time-sliced role split | Unavailable without granular event and role minutes |

## Provenance and safety

- Extracted records, Atlas-derived rates/averages, and unavailable categories are distinct. Missing values stay absent/N/D.
- Historical match context excludes the target match and same/later dates and constrains source exports to the selected career snapshot import sequence.
- Every query is career scoped. Plymouth Argyle and Sheffield United careers are never combined.
- Position observations require `career_playermatchratinghistory_position`; they do not prove starting status, tactical function or movement.
- Professional MatchStats and youth 5x5 remain separate. Lua exporters and EA FC save files are unchanged/read-only.

## Report pipeline and quality claims

Reports use the existing Atlas-local Ollama integration and `technical_commission_report_cache`, scoped by career, mode, target, model, source hash and report contract version. Reports contain cited fact IDs, item types (`fact`, `inference`, `hypothesis`) and limitations for hypotheses. Local validation checks source references, numerical values against cited facts, known source boundaries and objective conflicts; it is not an independent sports-quality score. Coverage and filtered counts are not labeled as interpretation confidence or a 9/10 quality score.

The twelve reproducible cases in `tests/fixtures/commission_intelligence_cases.json` are synthetic validator scenarios, not model outputs. A live model-quality comparison requires Ollama and the selected local model to be available. If Ollama is offline, Atlas statistical modules remain usable and no real model-quality result should be claimed.
