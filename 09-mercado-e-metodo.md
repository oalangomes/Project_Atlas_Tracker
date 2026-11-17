# Mercado, decisões e método

[Índice](plymouth-argyle-relatorio-temporada-atual.md)

## Fatos de cadastro versus planos

O snapshot 81 confirma 29 atletas no elenco e as saídas/empréstimos descritos em [base e saídas](07-base-e-saidas.md). A negociação Jeju SK FC por Ítalo Moreira Barcelos, com Caleb Roberts e €1 milhão e salário proposto de €4,2 mil/semana, é **plano relatado pelo treinador**; não há evento concluído no banco. Ronan Curtis está **colocado à venda**, sem venda confirmada. A busca por ponta/meia veloz e por veterano livre é intenção, sem aquisição registrada.

**Folha observada:** 29 atletas do elenco atual, salários registrados de €48.100/semana; os 33 contratos vinculados ao clube no cadastro somam €52.600/semana e incluem emprestados. Roberts: €600/semana; Curtis: €1.600/semana. Se a troca por Barcelos fosse concluída nos termos relatados e apenas o salário de Roberts deixasse a folha, a variação nominal seria +€3.600/semana, antes de bônus, impostos e outros movimentos.

**Impacto condicional.** Se Roberts sair, o meio perde reserva com minutos profissionais e a academia não oferece substituto comprovado. Se Curtis sair, a rotação de lado direito fica mais dependente de Amaechi, Benarous e dos recém-promovidos. Barcelos não é comparado tecnicamente: seus atributos e vínculo não constam no snapshot. €1 milhão é desembolso proposto, não despesa realizada; €4,2 mil semanais equivalem a cerca de €218,4 mil em 52 semanas, sem bônus ou encargos. A viabilidade financeira não pode ser concluída sem orçamento disponível.

**Prioridades práticas:** (1) registrar testes de Benarous, Providence e Watts nas faixas antes de fechar o perfil de MD/ME; (2) preservar cobertura de lateral esquerdo, pois Stopira tem validade contratual cadastrada até 2026; (3) avaliar Issa Mane na zaga sem retirar uma peça do duplo pivô antes de confirmar prontidão; (4) condicionar a troca por Barcelos à avaliação de seus atributos e ao custo real. Uma venda de Curtis só reduz a folha após confirmação; a cifra de €1 milhão continua proposta.

## Divergências entre camada oficial e exports

| Jogador | Aparições oficiais | Exports | G oficiais/rastreados | A oficiais/rastreadas | Leitura |
|---|---:|---:|---:|---:|---|
| Lorent Tolaj | 28 | 26 | 33/31 | 13/13 | camadas com cobertura distinta |
| Owen Oseni | 19 | 17 | 15/13 | 3/3 | camadas com cobertura distinta |
| Xavier Amaechi | 31 | 28 | 8/8 | 16/14 | camadas com cobertura distinta |
| Nishan Velupillay | 29 | 28 | 12/11 | 13/12 | camadas com cobertura distinta |
| Ruben Providence | 22 | 17 | 5/5 | 8/7 | camadas com cobertura distinta |
| Ayman Benarous | 26 | 22 | 3/2 | 2/1 | camadas com cobertura distinta |
| Joe Ralls | 27 | 24 | 0/0 | 4/3 | camadas com cobertura distinta |
| Alisson Bueno | 1 | 0 | 0/n/d | 1/n/d | sem export na estreia |
| Flávio Brandao | 1 | 0 | 0/n/d | 0/n/d | sem export na estreia |
| Owen Dale | 28 | 26 | 6/6 | 5/4 | camadas com cobertura distinta; oficial preservado antes da saída |

O número oficial pode incluir partidas sem export; a camada detalhada pode divergir até em jogo coberto. Os gols derivados de um export não são ajustados para fechar com o placar. Para atletas que saíram, usa-se a última linha oficial registrada por competição antes da saída.

## Rastreabilidade e correções

- Banco aberto por URI SQLite `mode=ro`; carreira `fc26v2-e7050151`, snapshot 81, data 2026-01-02. Nenhum banco/save foi alterado.
- Resultados: `fixture_observations` + `fixtures` do snapshot 81. Dados avançados: 32 `match_stat_exports` vinculados; export 31 ambíguo excluído. Estatísticas oficiais: `season_stat_states`, apenas clube representado 1929.
- Médias de nota: soma das notas dividida pelo número de aparições com nota. Onde há export e `player_match_performances` para a mesma partida, a nota/minuto do export tem precedência; partidas sem export acrescentam apenas nota/minutos. Indicadores por 90: soma da ação × 90 / soma dos minutos dos exports. xG é `npk_expected_goals` sem pênaltis. Conversão = gols rastreados / finalizações rastreadas.
- As comparações por setor incluem todos os atletas, inclusive os sem minutos. Nenhum ranking de notas usa corte de minutos variável; cada valor aparece com o próprio denominador, e a confiança cai com a amostra.
- Titularidade versus entrada: não derivada de minutos; o banco não oferece escalação histórica completa para todos os jogos. `player_match_performances` tem 361 linhas e posição efetiva em parte delas; posições vazias não foram preenchidas pelo teamsheet atual.
- Correção: 22 partidas × 3 = **66 pontos restantes**, não 44. Invencibilidade da temporada = 36 jogos; sequência atual de vitórias na liga = 3, máximo consecutivo = 15, ambos derivados da ordem dos fixtures.
- Estatística oficial e rastreada têm cobertura e semântica distintas; não somar nem ajustar uma para forçar igualdade. O export de 01/01 não está disponível. Gols derivados do rastreador podem divergir do placar em um jogo; para campanha usa-se o placar.
- **Correção do relatório anterior:** `player_dynamic_states` também contém 29 atletas do Plymouth no snapshot 81 (não apenas no 78). Seus `form_score`, `morale_score` e `fitness_score` são saídas do modelo Atlas v12, inclusive quando `performance_source=observed` indica entradas estatísticas observadas. Moral é proxy; fitness 100 pode significar ausência de penalidade, não medição física. Não foram usados como prova de desempenho ou escalação. GER inicial compara snapshot 1 quando presente; para recém-chegados usa-se o primeiro registro e identifica-se a base.
- Tabelas `transfer_market_events` e `finance_*` consultadas não trazem registros neste banco; por isso não há confirmação financeira das negociações nem orçamento utilizável. O salário é cadastro de `contract_states`, não fluxo de caixa.
- Atributos e secundárias vêm de `player_states.raw_json`; idade usa data de nascimento EA e data da carreira. A academia exporta apenas GER, potencial, posição e campos de permanência. PlayStyles, GER projetado por posição, plano de desenvolvimento e tempo de conversão não estão no dataset consultado.
- `team_league_states` do Plymouth está zerada; pontos e sequência da liga vêm dos fixtures. Sem dados de vídeo, mapa de ações, instruções históricas, forças dos adversários ou orçamento, interpretações táticas e financeiras são hipóteses identificadas.
- A qualidade dos indicadores de dribles, faltas e clearances do export é incerta; eles não determinam recomendações. As taxas de desarme e interceptação são contagens, não eficiência contextual.
