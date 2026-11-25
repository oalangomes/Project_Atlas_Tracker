# P08 — Rotação e modelo de jogo

Implementação de AT-012/013/015 e H20/H21. A consulta é calculada na leitura, sem migração ou gravação de partidas, escalações ou relatórios.

## Regra esportiva

- O XI inicial vem dos índices 0–10 de um MatchStats completo e ligado ao fixture. Exige onze índices e onze atletas EA distintos.
- Cada partida é comparada à **partida concluída imediatamente anterior na mesma temporada**, mesmo que o filtro de tela não a selecione. Sem XI em qualquer uma das duas, a partida atual fica fora da comparação e apresenta motivo.
- `8–11 mantidos` e `0–7 mantidos` são grupos de uso observado, não rótulos de titulares ou reservas por GER. A primeira partida da temporada não tem grupo.
- Gols, NPK-xG e chutes são valores da partida inteira. Não medem rendimento durante a presença de cada substituto. O saldo só existe quando os dois lados da métrica estão disponíveis; ausência não vira zero.
- Médias mostram cobertura por indicador. A diferença entre grupos só aparece quando cada grupo e cada indicador têm pelo menos três jogos. A comparação é descritiva, sem conclusão causal ou ajuste estatístico por adversário.
- A força rival é a diferença entre médias de GER dos elencos disponíveis em um snapshot da mesma temporada **anterior à data do jogo**: mais forte `>2`, similar `−2 a 2`, mais fraco `<−2`; caso contrário, desconhecido. A tabela e o nível da liga usam o mesmo serviço pré-jogo. A formação rival inicial só aparece quando a estimativa do P07 tem fonte atribuível.
- Posse percentual não foi confirmada nos exports ligados. NPK-xG e chutes próprios e rivais são mostrados como medidas separadas; nenhum rótulo de estilo “sem posse” é derivado deles.

## Onde consultar

`Analysis → Rotation` oferece temporada, competição, mando, força rival e formação rival inicial estimada. A tabela de jogos abre cada fixture e mostra XI mantido, grupo ou exclusão, dificuldade e indicadores disponíveis. A profundidade funcional permanece em `Squad analysis`, no contrato único de posições.

O relatório de identidade da Comissão Técnica recebe o **resumo determinístico** de rotação, com critérios, amostra, cobertura e referências de fixture. A instrução da IA permite apenas interpretação calibrada e citação desse fato. A entrega não dispara geração de análises esportivas nem apaga reports existentes. Como o conjunto de fatos mudou, leituras de identidade já salvas podem aparecer como **desatualizadas**; continuam preservadas e uma nova geração, solicitada pelo usuário ou por uma futura importação, passa a usar o recorte atualizado. Reports de partida e de jogador não recebem esse novo fato.

## Verificação no workspace ativo

Leitura do banco `ws_f5151a33099c`, carreira 1, snapshot 85, temporada 1 em 18/11/2026: 39 jogos concluídos, 35 exports detalhados ligados, 35 XI conhecidos, 31 jogos agrupados (11 com 8–11 mantidos; 20 com 0–7), 8 excluídos. A diferença média de GER rival foi `−1,44` e `+0,23`, respectivamente; a comparação bruta de produção não deve ser tratada como efeito da rotação. Os números são um exemplo verificável desse snapshot, não expectativa para outros saves.

Testes de corte temporal, filtro, XI ausente e métrica ausente em `tests/test_rotation_analysis.py`; testes de contexto competitivo e Comissão Técnica; `npm run build`. A consulta do banco ativo foi somente leitura.

## Limites e próximos contratos

AT-014 (profundidade por função) evolui no P09; esta tela reaproveita a análise do elenco. AT-025 (defesa contextual por setor) depende dos seus gates próprios no P12. Cronologia de substituições e posse real dependem de evidência adicional antes de qualquer análise on/off ou rótulo de posse. Uma amostra mínima de três jogos por grupo evita a diferença mais frágil, mas não controla competição, mando, adversário, lesões ou forma dos atletas; use os filtros e a distribuição de força para inspecionar esses fatores.
