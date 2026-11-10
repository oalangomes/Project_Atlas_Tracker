# Entrega 2 — Contexto tático e Diário do Treinador

[Índice](README.md) · [Governança](governanca-e-validacao.md) · Anterior: [Entrega 1](entrega-1-qualidade-rastreabilidade.md) · Próxima: [Entrega 3](entrega-3-rotacao-profundidade.md).

**Prioridade:** P1. **Estado:** planejada. **Dependências:** Entrega 0, especialmente AT-002; compatibilidade com o contrato de evidência AT-007. O núcleo de observações pode evoluir em paralelo à Entrega 1 após definição dos contratos comuns. PRs propostos 5 e 6.

## Objetivo e condição de conclusão

Recuperar informações qualitativas que o save não fornece de forma confiável. O relatório deve identificar o que veio do jogo, do treinador e de método inferencial.

| Pacote | Implementação | Critério de aceite original |
| --- | --- | --- |
| AT-008 | Registrar observações por partida | Notas persistidas, editáveis e vinculadas ao fixture |
| AT-009 | Registrar escalação, funções e substituições observadas | Dados manuais separados dos extraídos |
| AT-010 | Estimar formações adversárias | Hipótese, alternativa, evidências e grau de sustentação exibidos |
| AT-011 | Integrar observações ao relatório técnico | Comissão considera contexto confirmado sem tratá-lo como extraído |

Arquivos centrais: `server_query_matches.py`, `manual_data.py`, `views_matches.ts` e `commission.py`. Criar módulos separados para anotações e estimativas quando houver necessidade técnica, sem nova plataforma de orquestração.

## Corte 2A — Diário persistente (AT-008, PR 5)

1. Inspecionar a infraestrutura manual existente e definir identidade carreira/fixture, vínculo opcional com snapshot e autoria/origem.
2. Persistir nota, data do evento, data do registro e revisão. Edição deve permitir identificar que o conteúdo mudou, sem reclassificá-lo como extração do jogo.
3. Definir contrato de criar, ler, editar e remover/invalidar observação conforme o padrão atual. Preservar isolamento e responder explicitamente a fixture inexistente ou vínculo incorreto.
4. Integrar ao Match Center em aba/contexto existente. Reabrir a partida deve recuperar o registro; troca de carreira não pode exibi-lo.
5. Definir visão histórica: contexto conhecido à época deve respeitar a data/versão do registro. Enriquecimento retrospectivo deve ser indicado como tal, sem contaminar silenciosamente avaliações históricas.

**Aceite verificável:** registrar e editar uma nota, recarregar aplicação, consultar fixture correto e alternar carreira; o conteúdo persiste somente no escopo correto. Edição posterior não altera silenciosamente a evidência de relatório histórico já versionado.

## Corte 2B — Escalação e observações estruturadas (AT-009, PR 5)

1. Permitir registrar participantes, titularidade quando conhecida, posição jogada, função/papel, sistema observado e substituições.
2. Marcar completude por campo. Não exigir escalação completa para salvar observação parcial nem completar ausências por posição natural.
3. Registrar minuto somente quando conhecido; minuto desconhecido permanece ausente. Diferenciar jogador que participou de jogador com titularidade confirmada.
4. Preservar valores extraídos e manuais em camadas separadas; divergência deve aparecer com ambas as fontes e política de uso explícita.
5. Vincular alterações a revisão/registro para invalidar apenas relatórios ou comparações afetados conforme cache existente.

**Aceite verificável:** escalação parcial e substituição sem minuto continuam incompletas e utilizáveis dentro dos limites; conflito entre extraído e observado não sobrescreve o dado original.

## Corte 2C — Formações adversárias (AT-010, PR 6)

### Classificação obrigatória

| Estado | Regra | Apresentação |
| --- | --- | --- |
| Confirmada | Fonte direta ou observação explícita do treinador | Identificar quem/fonte, partida e momento; confirmação do treinador continua manual |
| Estimada | Combinação plausível de posições efetivamente observadas e participantes conhecidos, com evidências suficientes | Exibir hipótese, alternativa, método, evidências e sustentação qualitativa |
| Indeterminada | Evidência insuficiente para uma proposta defensável | Explicar o dado ausente e permitir complementar observação |

1. Inventariar fontes realmente disponíveis antes de desenhar o método. Distribuição de posições naturais isolada não prova formação e não basta para propor uma estimativa defensável.
2. Definir requisitos mínimos e condições de abstenção. Sem suporte, retornar indeterminada em vez de escolher o sistema mais comum.
3. Registrar hipótese principal e alternativa quando sustentáveis, distinguindo fase/momento da partida se essa informação existir.
4. Exibir sustentação descritiva, sem percentuais artificiais como “87% de chance de 5-4-1” sem modelo calibrado.
5. Permitir confirmação ou correção pelo treinador como nova observação manual, mantendo o histórico da estimativa e a origem da confirmação.

### Caso Wigan

A observação do treinador de uma linha de cinco deve complementar o Atlas. Se apenas essa linha foi observada, registrar a linha de cinco sem inventar o restante do sistema. Uma formação completa só é confirmada quando a observação/fonte sustenta essa informação. A posição natural dos jogadores não se converte automaticamente em escalação confirmada.

Este é um cenário de validação proposto; o plano não afirma que os dados atuais comprovam a formação do Wigan.

## Corte 2D — Relatório técnico e contexto (AT-011, PRs 5–6)

1. Integrar primeiro notas e fatos observados do PR 5, com atribuição e recorte temporal.
2. Após PR 6, acrescentar formações com seu estado e limitações. Uma hipótese não pode virar premissa factual em recomendações.
3. Separar evidência extraída, observação do treinador e inferência no contrato enviado ao modelo e na apresentação do relatório.
4. Atualizar versão/cache conforme a política existente quando contexto relevante mudar. Não regenerar toda a história automaticamente.
5. Manter resumo determinístico e acesso às observações sem IA configurada.

**Aceite verificável:** o relatório considera observação confirmada e a atribui ao treinador; mantém hipótese qualificada; reconhece formação indeterminada; não inventa cronologia, minutos ou mudanças táticas.

## Validação integrada

| Cenário | Resultado esperado |
| --- | --- |
| Nota criada/editada e aplicação reaberta | Persistência e revisão corretas |
| Carreira/fixture diferentes | Isolamento total |
| Nota registrada após a data histórica consultada | Exclusão da visão “conhecido à época” ou enriquecimento retrospectivo explícito |
| Escalação parcial/minuto ausente | Campos ausentes mantidos e comparação limitada |
| Extraído diverge do manual | Ambas as fontes preservadas e conflito visível |
| Somente posições naturais disponíveis | Formação indeterminada |
| Linha de cinco observada contra Wigan | Registro manual atribuído, sem sistema completo inventado |
| Estimativa e posterior confirmação | Revisões e estados distinguíveis |
| Provedor de IA indisponível | Diário e resumo determinístico funcionais |

Cobrir persistência/API, contratos do relatório, frontend e build. A qualidade das estimativas exige revisão de casos reais com evidências; testes de enumeração de estados não comprovam acurácia.

## Reversão e saída

Adicionar persistência compatível e backup verificável antes de migrar. Desativar a estimativa sem apagar diário ou fontes; preservar exportabilidade das observações e revisões. Documentar compatibilidade de downgrade e invalidação dos relatórios afetados.

- [ ] AT-008 persiste notas e revisões no fixture/carreira corretos.
- [ ] AT-009 preserva dados extraídos e campos desconhecidos.
- [ ] AT-010 exibe estados, evidências, alternativas e abstenção.
- [ ] AT-011 mantém atribuição e recorte temporal em relatórios.
- [ ] PRs 5 e 6 possuem evidência e checklist transversal.

A entrega habilita contexto para rotação e análise por sistema rival, somente nas partidas com classificação defensável.
