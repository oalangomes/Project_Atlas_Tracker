# Entrega 5 — Qualidade da Comissão Técnica e relatórios

[Índice](README.md) · [Governança](governanca-e-validacao.md) · Anterior: [Entrega 4](entrega-4-desenvolvimento-sucessao.md).

**Prioridade:** P2. **Estado:** planejada. **Dependências:** segurança da Entrega 0 e contratos de evidência, contexto, rotação e desenvolvimento. PR proposto 10 depende de PRs 1, 4 e 6–9.

## Objetivo e condição de conclusão

Tornar a IA útil como analista esportivo, com interpretações concretas e sem inventar causas, estatísticas ou evidências. Sua função é interpretar os resultados determinísticos, formular hipóteses qualificadas e recomendações específicas.

| Pacote | Implementação | Critério de aceite original |
| --- | --- | --- |
| AT-020 | Benchmark de modelos locais e cloud | Mesmas evidências e cenários, resultados comparáveis |
| AT-021 | Avaliação esportiva independente | Identificar conclusões genéricas, contraditórias ou não sustentadas |
| AT-022 | Evoluir relatórios periódicos | Pós-jogo, evolução recente, rotação, elenco e temporada |
| AT-023 | Controlar chamadas, custo e privacidade | Limites, cache, logs sem segredos e consentimento cloud |

Preservar a base registrada na análise: `REPORT_VERSION = 34`, concorrência para cloud e serialização das chamadas locais. Verificar o estado efetivo antes de alterar versão ou executor. Não introduzir LangChain, LangGraph ou plataforma multiagente.

## Corte 5A — Conjunto de avaliação e protocolo (AT-020)

1. Selecionar cenários reais do workspace confirmado e casos controlados de fronteira: dados completos, amostra pequena, ausência, fontes divergentes, formação indeterminada, observação manual e consulta histórica.
2. Fixar pacote de evidências, versão dos contratos, período e resultados determinísticos esperados por cenário. Não enviar ao modelo informação futura ou de outra carreira.
3. Usar as mesmas evidências e perguntas para os modelos locais e cloud; registrar diferenças de template exigidas pelo provedor sem mudar a base factual.
4. Registrar modelo/provedor, versão identificável, parâmetros, limites, duração, chamadas, falhas, tokens/custo quando disponíveis e resposta bruta sanitizada.
5. Distinguir geração nova de reuso de cache. Um acerto de cache não é execução real de outro modelo e não serve como medição de sua latência ou qualidade.
6. Definir amostra e critérios antes de executar; registrar execuções malsucedidas sem selecionar apenas bons resultados.

**Aceite verificável:** cada comparação pode ser reproduzida com o mesmo pacote de evidências e contexto de execução, com limites explícitos para versões de provedor que mudem.

## Corte 5B — Avaliação esportiva independente (AT-021)

1. Separar produção e avaliação dos relatórios. A mesma resposta não deve se autoaprovar apenas por declarar conformidade.
2. Definir referência factual e rubrica revisável, com avaliação humana e/ou mecanismo separado devidamente identificado. O plano não exige infraestrutura multiagente.
3. Avaliar exatidão numérica, atribuição de fonte, contradição, causalidade inventada, generalidade, coerência de função/adversário e qualificação da amostra.
4. Usar casos negativos conhecidos para verificar que o avaliador detecta contradições críticas e vazamento temporal/entre carreiras.
5. Registrar achado, trecho afetado, evidência de referência, gravidade, decisão e revisão necessária. `review_required` é sinal operacional; sua taxa isolada não mede qualidade.

### Critérios obrigatórios de liberação do conjunto

- **100%** das afirmações factuais numéricas rastreáveis às fontes.
- **Zero** contradições factuais críticas não detectadas.
- Hipóteses explicitamente qualificadas.
- Recomendações específicas ao papel, adversário e amostra.
- Ausência de vazamento entre carreiras e datas históricas.

Definir como contar afirmações, contradições e cenários antes do benchmark. Se não houver afirmação numérica, rastreabilidade pode ser não aplicável ao caso, mas não conta como cobertura numérica do conjunto. Detecção de contradição deve bloquear liberação automática da resposta afetada e encaminhar revisão, sem apresentá-la como aceita.

**Aceite verificável:** avaliação encontra casos genéricos/contraditórios introduzidos no conjunto e distingue relatório numericamente correto de interpretação esportivamente útil.

## Corte 5C — Relatórios periódicos (AT-022)

1. Evoluir os relatórios existentes com contratos compartilhados; evitar duplicar cálculos de `match_stats.py`, `positions.py` e `match_competitive_context.py`.
2. Definir entradas e cobertura por tipo de relatório:

| Relatório | Entradas e foco | Limite obrigatório |
| --- | --- | --- |
| Pós-jogo | Partida, adversário pré-jogo, papéis e observações | Sem cronologia ou formação inventadas |
| Evolução recente | Período explícito, produção, atributos e amostra | Produção e desenvolvimento sem causa presumida |
| Rotação | Composição, dificuldade e continuidade | Sem impacto causal do banco sem captura temporal |
| Elenco | Profundidade, alternativas e sucessão | Priorizar cobertura interna e diferenças funcionais |
| Temporada | Recortes comparáveis e cobertura histórica | Não misturar fontes/períodos nem esconder lacunas |

3. Vincular cada afirmação factual a referências de evidência; separar dado, inferência, observação do treinador e recomendação.
4. Persistir acompanhamento de recomendações/decisões quando suportado pelo fluxo existente, com autoria e revisão. Recomendação não vira ação automática na carreira.
5. Manter relatórios determinísticos úteis sem IA. Erro do modelo não deve indisponibilizar métricas e observações.
6. Aplicar versão/cache apropriados e reavaliar cenários afetados após alterações de prompt, modelo ou contratos.

**Aceite verificável:** os cinco tipos respeitam seus recortes e mantêm interpretação concreta, atribuída e revisável.

## Corte 5D — Chamadas, custo e privacidade (AT-023)

Controles básicos de segurança, timeout, failover e offline pertencem à Entrega 0. Este corte amplia visibilidade e uso sustentado, sem postergar requisitos P0.

1. Mostrar preferência e consentimento cloud antes do envio, com informação clara sobre os dados incluídos. Chave configurada não implica consentimento para todos os relatórios históricos.
2. Aplicar limites de chamadas/tokens e orçamento de execução conforme capacidades reais, incluindo concorrência e failover sem multiplicação descontrolada.
3. Exibir uso/custo observável e distinguir valor medido de estimativa. Ausência de preço ou contagem não deve aparecer como custo zero confirmado.
4. Reutilizar cache com chave/versionamento e isolamento adequados a carreira, snapshot, período, evidência, observações e política de modelo/provedor.
5. Manter logs operacionais sem segredos e com minimização de conteúdo privado. Integrar os testes de vazamento da Entrega 0.
6. Garantir que revogar consentimento impeça novos envios cloud e preserve a aplicação local/determinística.

**Aceite verificável:** contadores, limites, fallback, cache e consentimento correspondem às chamadas efetivamente observadas, com teste negativo de envio não autorizado.

## Gate específico: geração histórica completa

Não liberar replay/geração histórica completa apenas com testes sintéticos de contrato. Exigir avaliação real do conjunto, isolamento temporal, amostra inspecionada e controle de chamadas/custo. A aceitação vale para modelos, cenários e versão efetivamente avaliados, sem homologação genérica da camada local ou cloud.

Antes de execução em lote, registrar carreira, intervalo, quantidade prevista, política de cache, limites, critérios de parada e tratamento de `review_required`. Relatórios antigos não se tornam válidos só porque a versão nova do validador passou em teste; identificar quais precisam de regeneração e revisão.

## Validação e artefatos

Entregar manifesto do conjunto, referências factuais, respostas sanitizadas, avaliação por cenário, matriz comparativa de modelos e registro dos gates. Verificar API, persistência, interface da Comissão, build e comportamento sem IA.

Simulados comprovam contratos e falhas controladas; resultados reais comprovam apenas o cenário executado. Não substituir o executor solicitado por outro nem usar texto produzido manualmente como resultado de modelo.

## Reversão e saída

Permitir desativar provedor ou relatório novo e conservar visão determinística. Preservar relatórios, evidências e avaliações por versão; não reclassificar resultado antigo como novo. Reverter prompt/modelo requer revisar compatibilidade de cache e aceite, sem restaurar exposição de credenciais.

- [ ] AT-020 executado com evidências iguais e modelos identificados.
- [ ] AT-021 avaliado de forma independente e com casos negativos.
- [ ] AT-022 validado nos cinco tipos de relatório.
- [ ] AT-023 comprova limites, cache, custo observável e consentimento.
- [ ] Critérios factuais e esportivos de liberação cumpridos.
- [ ] Geração histórica permanece condicionada ao gate real.
- [ ] PR 10 possui evidência, reversão e checklist transversal.
