# Entrega 1 — Qualidade e rastreabilidade dos dados

[Índice](README.md) · [Governança](governanca-e-validacao.md) · Anterior: [Entrega 0](entrega-0-estabilizacao-seguranca-contratos.md) · Próxima: [Entrega 2](entrega-2-contexto-tatico-diario.md).

**Prioridade:** P1. **Estado:** planejada. **Dependências:** contratos e gates da Entrega 0, especialmente AT-002. PR proposto 4, dependente do PR 2.

## Objetivo e condição de conclusão

Criar uma fonte de evidências consistente e compartilhada por todas as análises. Uma métrica apresentada em Player Profile, Match Center e Comissão Técnica deve manter significado, período e origem.

| Pacote | Implementação | Critério de aceite original |
| --- | --- | --- |
| AT-005 | Consolidar cobertura dos MatchStats e posições | Cada partida mostra dados disponíveis, ausentes e respectivas origens |
| AT-006 | Reconciliar indicadores e evolução entre snapshots | Divergências de xA e GER/POT identificadas, explicadas ou bloqueadas |
| AT-007 | Criar catálogo de evidências reutilizável | Todo indicador possui carreira, partida/período, fonte, unidade e versão |

Arquivos centrais: `match_stats.py`, `server_query_analysis.py`, `server_query_history.py`, `db.py`, `views_analysis.ts` e `views_history.ts`. Reutilizar o painel de qualidade existente; não criar outro painel concorrente.

## Corte 1A — Inventário e contrato compartilhado (AT-007)

1. Mapear indicadores atuais, fontes, períodos, unidades, agregações e consumidores. Incluir divergências entre telas e distinguir valores brutos de derivados.
2. Definir representação reutilizável de evidência, preferindo estender contratos existentes. Decidir o mínimo de persistência necessário após inspecionar esquema e volume; o plano não exige nova tabela para cada indicador.
3. Vincular referências de carreira, snapshot elegível, fixture ou período, origem e versão. Para derivados, incluir fórmula/método e entradas; para indisponibilidade, motivo.
4. Distinguir data do evento, captura e importação. Registrar revisões sem atribuir a um snapshot informação que só chegou depois.
5. Documentar dicionário e compatibilidade dos consumidores antes de ampliar análises.

### Contrato mínimo proposto

| Informação | Regra |
| --- | --- |
| Identidade | Carreira e entidades de origem sem colisão entre workspaces |
| Recorte | Snapshot elegível, fixture/período e competição quando aplicável |
| Indicador | Nome semântico e unidade explícita |
| Valor | Ausente separado de zero real |
| Proveniência | Extraído, derivado, manual, estimado ou indisponível |
| Fonte | Importação/registro e referência verificável |
| Versão | Contrato/método usado para cálculo ou interpretação |
| Cobertura | Amostra, completude e limitações para comparações |

O formato exato deve resultar da implementação; a semântica acima é obrigatória. Evidência manual e estimada deve ser compatível com a Entrega 2, sem fundir suas origens.

## Corte 1B — Cobertura por partida (AT-005)

1. Inventariar MatchStats recebidos, importações parciais e fontes verificadas de posição por participante.
2. Produzir cobertura reutilizável por partida e indicador, apontando origem, ausência e limite temporal.
3. Distinguir posição cadastrada, efetivamente jogada e recuperada de snapshot anterior elegível. Recuperação não transforma posição natural em observação de jogo.
4. Ampliar painel de qualidade e consumidores existentes com os mesmos estados. Não publicar indicador agregado sem informar amostra quando há partidas incompletas.
5. Propagar o contrato ao Match Center e à Comissão Técnica, para impedir interpretações sobre campos ausentes.

**Aceite verificável:** uma partida completa, uma parcial e uma sem MatchStats mostram cobertura coerente entre API, painel e relatório. Ausência permanece ausência em consultas e agregações.

## Corte 1C — Reconciliação sem apagamento de fontes (AT-006)

1. Definir quais indicadores são comparáveis: mesma carreira, identidade, intervalo, unidade, significado e fonte compatível.
2. Para xA, comparar origens e períodos antes de procurar diferença numérica. Manter valores distintos quando representarem conceitos ou recortes diferentes; não forçar igualdade.
3. Para GER/POT e atributos, validar sequência, identificação do jogador e disponibilidade. Calcular deltas auditáveis apenas entre observações elegíveis; não interpolar ausência como zero.
4. Classificar divergência como explicada por origem/recorte, inconsistente ou sem evidência suficiente. Bloquear a comparação afetada quando não houver base defensável, mantendo valores originais acessíveis.
5. Mostrar diagnóstico e sua justificativa no histórico/qualidade. Alimentar consumidores com o mesmo estado de reconciliação.

**Aceite verificável:** dois valores xA diferentes por origem continuam preservados e explicados; inconsistência não resolvida é visível e não vira conclusão automática. Deltas GER/POT identificam snapshots de origem e destino.

## Corte 1D — Integração e regressão comum

Consolidar AT-005–AT-007 no fluxo importação → consulta → telas → Comissão. Somar a cobertura restante de AT-004 relativa a importação, recuperação, cache e consistência, sem declarar que esse PR substitui testes dos anteriores.

| Cenário | Resultado exigido |
| --- | --- |
| Carreiras diferentes com jogador/fixture semelhante | Nenhuma mistura de valor, cobertura ou cache |
| Snapshot anterior e registro futuro | Registro futuro inelegível no histórico |
| Estatística ausente e estatística zero | Estados e agregações diferentes |
| xA de fontes ou períodos distintos | Valores preservados; comparação qualificada |
| GER/POT faltante num extremo | Delta indisponível, sem evolução artificial |
| Mesmo indicador em três superfícies | Mesmo significado, recorte e fonte |
| Reimportação/duplicata conforme contrato existente | Sem contagem duplicada ou perda de proveniência |

Verificar TypeScript, JS gerado e fluxo da interface para os contratos alterados. Registrar testes automatizados e inspeção visual separadamente.

## Artefatos, reversão e saída

Entregar dicionário de indicadores/fontes, contrato de evidência, diagnóstico de cobertura/reconciliação e validação do PR 4. Se houver migração, produzir backup consistente e estratégia compatível de restauração; preservar valores originais. Invalidar caches cujos significados ou versões mudarem.

- [ ] AT-005 apresenta disponibilidade e origem por partida.
- [ ] AT-006 explica ou bloqueia divergências sem apagar fontes.
- [ ] AT-007 é consumido pelas telas e Comissão, sem lógica paralela.
- [ ] Regressão histórica, integração e build comprovados.
- [ ] Checklist transversal e rollback documentados.

Esta entrega libera contratos para rotação, comparação individual e sucessão. Não comprova precisão esportiva apenas por melhorar cobertura.
