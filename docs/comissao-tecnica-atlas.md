# Comissão Técnica no Atlas — primeiro incremento

Este painel é uma extensão do Atlas existente. A leitura é calculada por carreira e snapshot, gravada em cache derivado com versão/hash das fontes e refeita quando o conteúdo de origem muda. O save do EA FC permanece somente leitura.

## Matriz de cobertura

| Dependência esportiva | Evidência no Atlas | Tratamento deste incremento |
|---|---|---|
| Identidade, clube e posição cadastral | `player_states` do snapshot | Extraído; carreira e clube conferidos pelo `career_id` e `managed_team_ea_id` |
| Partida, data e adversário | `player_match_performances` e `fixture_observations` | Atuações importadas no snapshot selecionado; chave do jogo preservada |
| Minutos e nota por atuação | `player_match_performances` | Extraídos; base para notas de temporada e momento recente |
| Últimas cinco atuações válidas | Minutos e nota individuais | Derivado como média ponderada por minutos nas até cinco atuações recentes com 15+ minutos |
| Corte de amostra | Minutos totais e atuações válidas | Mesmo contrato Hub: utilizável com 300+ min e 3+ atuações; confiável com 450+ min e 5+ atuações |
| Cameo de 1–14 min | Minutos e nota existem, mas eventos individuais não são completos | Mantido na minutagem; não pesa no recorte recente. O Atlas não consegue aplicar a exceção Hub de gol/assistência sem evidência individual |
| Hierarquia de elenco | `roster_states` registra elenco/slot observado, sem hierarquia estrutural confiável | N/D; não inferida de titularidades observadas ou minutos |
| Gols, assistências, NPK-xG, xA, chutes, passes, desarmes, interceptações e ações | `match_player_detailed_stats.stats_json` em exportações completas ligadas ao fixture e à carreira | Extraídos por jogador, somente nas partidas exportadas; a cobertura aparece como jogos exportados / jogos concluídos e não é apresentada como temporada completa |
| Posição principal e comparação | `player_states.primary_position` | Coortes separadas por posição cadastrada; cada grupo mostra jogos, minutos e selo de amostra |
| Função/subgrupo observado | `player_match_performances.actual_position` com provenance `career_playermatchratinghistory_position` | Comparação apenas quando a posição foi registrada por atuação; registros de última escalação são excluídos |
| Clean sheet por exposição individual | Resultado coletivo por fixture e minutos individuais | Não incluído na leitura individual inicial |
| Métricas de goleiro/defesa | Exportações detalhadas ligadas em parte das partidas | Ações presentes no `stats_json` (por exemplo, saves, goals conceded, tackles, interceptions, blocks e clearances) são somadas apenas no recorte exportado; nenhuma taxa ausente é estimada |
| Base 5x5 | Estado jovem/tournament probe separado do futebol profissional | Fora do cálculo profissional; nenhuma estatística 5x5 inferida |

## Regras de decisão

- Hierarquia, momento e recomendação permanecem em campos distintos.
- A nota recente é a média ponderada por minutos das cinco atuações válidas mais recentes do jogador, e não das cinco partidas mais recentes do clube.
- Uma amostra abaixo dos cortes é exibida como sinal e sugere ampliar a observação. Ela não altera hierarquia, elenco ou escalação.
- Com amostra utilizável, a variação recente de pelo menos 0,3 ponto indica alta/queda; a recomendação permanece de acompanhamento porque falta hierarquia formal e comparação confiável por função.
- Campos ausentes aparecem como N/D. O painel não grava no save e não transforma resultados de equipe em eventos individuais.

## Persistência e IA local

O cache `technical_commission_cache` é derivado, separado do dado bruto, versionado e idempotente por carreira/snapshot. O resumo esportivo é recalculado por carreira, temporada e snapshot solicitado; o backfill é repetível. A tabela `technical_commission_ai_cache` guarda somente respostas estruturadas que passaram pela validação, com hash das evidências.

Ollama é opcional e local. `ATLAS_OLLAMA_URL` pode trocar o endereço (padrão `http://127.0.0.1:11434`) e `ATLAS_OLLAMA_MODEL` fixa um modelo; sem isso, o Atlas escolhe o primeiro modelo local disponível. `GET /api/ollama/models` verifica o serviço. O botão da tela envia fatos somente-leitura, usa timeout e schema JSON; o modelo escolhe sinais enumerados e os textos finais são montados pelo Atlas a partir de campos verificados. Respostas inválidas/offline mantêm o relatório determinístico. A IA não preenche N/D nem grava dados brutos ou no save.

## Validação Hub

O painel preserva os cortes e a ponderação do Hub para atuações. No workspace ativo ARGILA / Plymouth Argyle (snapshot 48, 25/10/2025), há 32 jogadores, 318 atuações no histórico e 31 jogadores com MatchStats. Os exports cobrem 19 de 21 jogos concluídos (90,5%) e 308 linhas do Plymouth. Gols e assistências abaixo refletem somente esse recorte; a função por atuação é limitada aos registros com proveniência confiável. Os resultados do Sheffield Hub ainda não são equivalência ponta a ponta, pois são de outra carreira e composição.

O workspace Plymouth foi confirmado como carreira ativa; não foi misturado com Sheffield United. A carreira e os arquivos de save permanecem somente leitura. O módulo jovem 5x5 continua separado do futebol profissional.
