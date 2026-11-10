# Entrega 3 — Análise de rotação e profundidade funcional

[Índice](README.md) · [Governança](governanca-e-validacao.md) · Anterior: [Entrega 2](entrega-2-contexto-tatico-diario.md) · Próxima: [Entrega 4](entrega-4-desenvolvimento-sucessao.md).

**Prioridade:** P1. **Estado:** planejada. **Dependências:** Entregas 0, 1 e 2 para segurança, evidência e composição/contexto. PR proposto 7 depende de PRs 4 e 5. Formação rival estimada depende adicionalmente de PR 6; essa dimensão não pode bloquear comparações que já possuem dados suficientes em outros eixos.

## Objetivo e condição de conclusão

Responder com dados se a utilização do banco preserva o nível da equipe. Mostrar se a produção muda com a rotação, indicando dificuldade do adversário, amostra e diferenças táticas conhecidas.

| Pacote | Implementação | Critério de aceite original |
| --- | --- | --- |
| AT-012 | Comparar rendimento por composição utilizada | Separar partidas com escalação conhecida das incompletas |
| AT-013 | Contextualizar por dificuldade | Usar contexto pré-jogo, competição, mando e força disponível do rival |
| AT-014 | Evoluir profundidade por função | Identificar cobertura suficiente, adaptação e lacuna funcional |
| AT-015 | Criar relatório de continuidade de desempenho | Comparar produção, criação e proteção defensiva entre grupos utilizados |

AT-014 participa deste resultado esportivo, mas sua evolução estrutural é implementada no PR 8, junto à sucessão da Entrega 4. PR 7 deve consumir a profundidade existente em `positions.py` e incorporar o contrato evoluído quando disponível; não criar outra lógica de adequação.

## Limites obrigatórios da primeira versão

Sem titularidade e minutos de substituição confiáveis, não é possível calcular impacto causal das entradas do banco. Comparar jogos e períodos cuja composição seja conhecida. Não atribuir gols ou xG do jogo inteiro ao intervalo de um substituto.

Métricas on/off ficam condicionadas à captura temporal confiável e à disponibilidade das estatísticas no mesmo intervalo. Captura detalhada por minuto pertence a investigação separada quando indisponível; não presumir esse dado para viabilizar o relatório.

Não criar ranking automático de “titulares” e “reservas” com base em reputação ou GER. A composição precisa ser definida por uso observado ou seleção explícita do treinador, com critério documentado.

## Corte 3A — Composições e elegibilidade (AT-012)

1. Inventariar titularidade, participação, posição jogada, minutos e completude por partida usando os contratos AT-005/007/009.
2. Definir grupos comparados e sua regra de inclusão. Se seleção manual, atribuir ao treinador; se regra derivada do uso, versionar e explicar o período.
3. Separar composição conhecida, parcial e desconhecida. Partida com lista de participantes sem titularidade não deve entrar silenciosamente como onze inicial confirmado.
4. Produzir grupos comparáveis e lista de exclusões com motivo. Permitir inspecionar os fixtures e evidências que sustentam cada agregado.
5. Usar apenas períodos com cobertura compatível; informar quantidade de partidas e exposição conhecida. Dado insuficiente pode impedir conclusão sem impedir consulta aos jogos.

**Aceite verificável:** grupos conhecidos e incompletos aparecem separados; alteração de composição muda apenas o recorte correspondente e suas evidências.

## Corte 3B — Contexto competitivo pré-jogo (AT-013)

1. Reutilizar `match_competitive_context.py`, sem comparador paralelo.
2. Associar competição, mando, força média disponível do elenco rival, nível da liga e posição de tabela quando reconstruível com informação anterior à partida.
3. Registrar limites e dados faltantes do contexto. Não usar tabela final, transferências posteriores ou forma atual para explicar retrospectivamente uma partida antiga.
4. Definir estratos/recortes explicáveis a partir do contexto existente. Comparações devem expor desequilíbrio de adversários e amostra, sem atribuir precisão indevida a um ajuste.
5. Incluir sistema rival somente quando observado ou estimado com sustentação, preservando a classificação e separando indeterminados.

**Aceite verificável:** contexto permanece o mesmo ao acrescentar snapshot posterior; comparações revelam quando um grupo enfrentou adversários mais fortes ou mando distinto.

## Corte 3C — Cobertura funcional consumida (AT-014)

Usar grupos de posições, profundidade desejada e adequação já existentes em `positions.py`. Exibir função coberta, adaptação e lacuna, com origem do papel e limitações. Capacidade cadastral e desempenho observado não são intercambiáveis.

A implementação única de AT-014 está detalhada na [Entrega 4, corte 4A](entrega-4-desenvolvimento-sucessao.md#corte-4a--profundidade-funcional-at-014-pr-8). Se o relatório depender de estados novos desse contrato, executar PR 8 antes de concluir esse trecho do PR 7.

## Corte 3D — Relatório de continuidade (AT-015)

Estrutura proposta; não representa medições já disponíveis:

| Perspectiva | Indicadores candidatos | Restrições |
| --- | --- | --- |
| Ofensiva | Gols, xG, chances e criação | Usar somente campos efetivamente disponíveis e comparáveis |
| Defensiva | xGA, finalizações concedidas e ações defensivas | Não inventar métricas ausentes nem confundir ação com eficácia |
| Funcional | Compatibilidade das peças com o modelo | Reutilizar adequação e separar observado de cadastral |

1. Publicar comparação determinística no Analysis, com contexto, amostra, composição e cobertura.
2. Mostrar valores, diferença descritiva e limitações; indicar quando não há base para concluir manutenção, melhora ou queda de rendimento.
3. Relacionar diferenças táticas conhecidas sem afirmar causa. Composição, adversário e contexto podem variar juntos.
4. Integrar a Comissão Técnica como interpretação dos resultados, com referências por afirmação, sem recálculo de métricas pelo modelo.
5. Suportar filtros por competição, mando, dificuldade e sistema rival quando coberto. Informar explicitamente o tamanho do recorte filtrado.

## Validação esportiva e técnica

| Cenário | Resultado esperado |
| --- | --- |
| Composição conhecida versus parcial | Inclusão e exclusão justificadas |
| Grupos com adversários de níveis diferentes | Diferença de exposição visível |
| Snapshot futuro altera força/tabela | Contexto histórico permanece isolado |
| Minutos de substituição desconhecidos | Nenhum on/off ou causalidade de entrada |
| Métrica ausente em parte dos jogos | Cobertura exposta; ausência não vira zero |
| Mesma composição, filtros diferentes | Agregados refletem fixtures elegíveis e fonte comum |
| Sistema rival indeterminado | Recorte separado, sem formação presumida |
| Sem IA | Comparação e relatório determinístico utilizáveis |

Escolher amostra real do workspace confirmado e confrontar os agregados com os fixtures. Providence, Oseni, Dale e Watts são exemplos de perguntas do treinador, não resultados antecipados. Registrar insuficiência da amostra quando existir.

## Reversão e saída

Reverter apresentação/consulta nova sem alterar dados de origem, observações ou posição canônica. Se grupos forem persistidos, preservar critérios e exportação; versionar derivados e invalidar cache quando mudar a seleção.

- [ ] AT-012 identifica composição e completude.
- [ ] AT-013 usa apenas contexto elegível pré-jogo.
- [ ] AT-014 é reutilizado sem implementação concorrente.
- [ ] AT-015 explica continuidade com evidências, amostra e limites.
- [ ] Fluxo Analysis → fixtures → Comissão, build e checklist validados.

Este é o primeiro grande objetivo esportivo do roadmap após segurança, estabilidade e qualidade dos dados.
