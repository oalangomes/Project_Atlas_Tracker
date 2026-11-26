# Plano de evolução do Project Atlas Tracker

Replanejado em **17/11/2026** com Atlas em `2737b53a8bcfaebd0be813f92250b14ddc3a3969` e Sheffield Hub em `6f235e70746fe014b3a8aa92f1cbba2e7ca7d2d2`. A base original de 10/11/2026 analisava `8f063cf`; suas seções abaixo são histórico de requisitos onde a revisão não as substitui.

Repositório: [oalangomes/Project_Atlas_Tracker](https://github.com/oalangomes/Project_Atlas_Tracker).

**Estado:** esta revisão é documental. AT-001/002 já têm implementação parcial anterior no commit `c0f1736`, mas os gates integrais permanecem abertos; AT-003 exige homologação real; AT-020 fica adiado fora deste ciclo. Nenhum outro AT é declarado implementado por este plano. As conclusões da base de 10/11 não equivalem a falhas reproduzidas ou aceite esportivo.

As seis entregas e AT-001–AT-023 permanecem rastreáveis. A investigação do Hub adiciona AT-024 (goleiros) e AT-025 (defesa contextual), sem duplicar os serviços atuais. Os estados e a ordem vigentes estão na [matriz Hub → Atlas](matriz-reaproveitamento-hub-atlas.md), no [backlog de bloqueios](backlog-metricas-hub.md), no [plano de execução](plano-execucao-integracao-hub.md) e nas seções de revisão de cada entrega. Regras antigas de sequência de PR e AT-020 abaixo são substituídas por esses documentos.

Para este ciclo, este conjunto é a referência de planejamento. O [roadmap anterior de integração cloud](../roadmap_cloud_integration.md) permanece como documento histórico: suas propostas de infraestrutura, modelos ou armazenamento não substituem os requisitos de segurança e reaproveitamento aqui definidos. Documentos existentes continuam como contexto e evidência a verificar, sem atualização retroativa de seus resultados.

## Documentos e ordem de leitura

| Etapa | Prioridade | Documento | Pacotes | Resultado esperado |
| --- | --- | --- | --- | --- |
| Experiência do treinador | Produto | [Auditoria de UX e análise funcional de 26/11/2026](../auditoria-ux-funcional-2026-11-26.md) | Proposta | Inventário atual, verificação na carreira e prioridades para navegação e relatórios |
| Regras comuns | Todas | [Governança e validação](governanca-e-validacao.md) | Transversal | Critérios, evidências, rollback e sequência de PRs |
| Reuso Hub | Todas | [Matriz Hub → Atlas](matriz-reaproveitamento-hub-atlas.md) | H01–H35 | Origem, fórmula, estado, destino e decisão |
| Impedimentos | Todas | [Backlog](backlog-metricas-hub.md) | BL-01–BL-13 | Bloqueio, custo, benefício e condição de desbloqueio |
| Execução vigente | Todas | [Plano de integração](plano-execucao-integracao-hub.md) | P01–P12 | Fases, PRs, testes e rastreabilidade |
| Entrega 0 | P0 | [Estabilização, segurança e contratos](entrega-0-estabilizacao-seguranca-contratos.md) | AT-001–AT-004 | Proteger segredos, história e execução |
| Entrega 1 | P1 | [Qualidade e rastreabilidade dos dados](entrega-1-qualidade-rastreabilidade.md) | AT-005–AT-007 | Contrato comum de evidências e métricas |
| Entrega 2 | P1 | [Contexto tático e Diário do Treinador](entrega-2-contexto-tatico-diario.md) | AT-008–AT-011 | Contexto qualitativo persistente e atribuído |
| Entrega 3 | P1 | [Rotação e profundidade funcional](entrega-3-rotacao-profundidade.md) | AT-012–AT-015, AT-025 | Comparar composições e defesa contextual com amostra |
| Entrega 4 | P2 | [Desenvolvimento e funções](entrega-4-desenvolvimento-sucessao.md) | AT-016–AT-018 | Comparação contextual e desenvolvimento da base |
| Entrega 5 | P1/P2 | [Comissão Técnica e relatórios](entrega-5-comissao-relatorios.md) | AT-020–AT-024 (020 adiado) | Goleiros, interpretação e semestre rastreáveis |

## 1. Diagnóstico inicial: o que mudou desde a última revisão

A análise de 6 de novembro usava `2fc44e3`; a revisão recebida usa `8f063cf`. As mudanças relevantes descritas são:

- **Contextualização da dificuldade dos adversários:** `atlas/match_competitive_context.py` usa informações do save anteriores à partida, incluindo força média disponível do elenco, nível da liga e posição na tabela quando reconstruível.
- **Recuperação de posições efetivamente jogadas:** duas fontes verificadas de posição e observações de snapshots anteriores, sem substituir indiscriminadamente posição real por posição cadastrada.
- **Documentação dos provedores de IA:** [mapa do banco e configuração](../database_map.md) descreve Ollama, Gemini, Groq, cache, failover e limites de execução.
- **Testes específicos:** contexto competitivo e proveniência posicional.

Essas mudanças alteram o planejamento: consolidar, validar e ampliar a comparação de dificuldade e a camada de IA existentes, sem reconstruí-las do zero.

Referências de implementação da análise: [frontend](https://github.com/oalangomes/Project_Atlas_Tracker/tree/8f063cf/frontend/src), [Comissão Técnica](https://github.com/oalangomes/Project_Atlas_Tracker/blob/8f063cf/atlas/commission.py) e [posições e adequação](https://github.com/oalangomes/Project_Atlas_Tracker/blob/8f063cf/atlas/positions.py). As referências usam o commit analisado para evitar que mudanças futuras de `master` alterem a base documental.

## 2. Diretriz do produto

Evoluir de um tracker de carreira com relatórios para uma plataforma de inteligência esportiva baseada em evidências, preservando o propósito original:

> Acompanhar o save, explicar desempenhos, registrar decisões e apoiar a comissão técnica — sem controlar ou modificar a carreira no EA FC.

O plano não prevê reescrita, plataforma multiagente ou reformulação completa da navegação. A aplicação já possui 21 entradas de navegação segundo a análise recebida; a prioridade é ampliar capacidades nos menus atuais.

## 3. Matriz de cobertura da master analisada

| Área | Já implementado na análise recebida | Lacuna prioritária |
| --- | --- | --- |
| Dashboard | Resultados, calendário, indicadores, principais jogadores | Alertas esportivos contextualizados |
| Match Center | xG, xA, passes, ações defensivas, ratings, relatórios | Formação adversária, contexto tático e cronologia confiável |
| Analysis | Tendências, médias móveis, divisão por competição e mando | Rotação e desempenho conforme dificuldade |
| Elenco | Jogadores, atributos, GER/POT, estatísticas | Profundidade funcional e cobertura real de posições |
| Player Profile | Radar, perfil de função, desenvolvimento e comparações | Avaliação por papel desempenhado e adversário |
| Comissão Técnica | Relatórios estruturados, amostras, comparações e IA | Qualidade interpretativa, observações persistentes e calibração |
| Base | Jovens, potencial e histórico disponível | Plano individual e transição ao profissional |
| Gestão | Contratos, empréstimos, transferências | Histórico e vínculos do elenco |
| Sistema | Importação, snapshots, comparação, cobertura | Auditoria de consistência e estabilidade ponta a ponta |

## 4. Riscos prioritários da análise estática

Os três riscos concretos apontados e a dívida de validação têm prioridade sobre novos gráficos. Devem ser confirmados no início da Entrega 0.

| Prioridade | Achado recebido | Encaminhamento |
| --- | --- | --- |
| P0 | `GET /api/llm/config` retorna `**config`, incluindo `keys`; frontend carrega `state.llmKeys`; JSON em `app_settings` mantém segredos legíveis | AT-001: resposta pública sanitizada, armazenamento protegido por usuário Windows e migração |
| P0 | `historical_observed_positions()` filtra carreira/fixture sem corte explícito de `import_sequence` pelo snapshot selecionado | AT-002: impedir observações futuras em consultas históricas |
| P0 | Histórico documentado de falhas nativas pós-partida e correções dos handlers Lua; testes de contrato não provam estabilidade com Live Editor | AT-003: homologação controlada em cópia segura do save |
| P0 | Gemini/Groq, failover, cache e limites ampliam contratos além da cobertura existente | AT-004: integração simulada, segurança, offline e testes reais controlados |

O vínculo a localhost reduz a superfície de exposição das credenciais, mas não resolve o problema descrito. A análise original não executou aplicação ou testes no Windows e não atribui falhas de execução não comprovadas.

## 5. Arquitetura-alvo: evoluir o que já existe

Fluxo de responsabilidades:

1. **Frontend Atlas existente:** Dashboard, Match Center, Elenco, Analysis, Comissão e Base.
2. **Análise determinística:** métricas, comparação, contexto competitivo, adequação e validação.
3. **Comissão Técnica + IA:** interpretação, hipóteses, recomendações e perguntas ao treinador.
4. **Camada compartilhada de evidências e proveniência:** extraído, derivado, observação manual, estimado e indisponível.
5. **SQLite, importadores e snapshots existentes:** save FC26 somente leitura, MatchStats, histórico e dados manuais.

A IA interpreta resultados; não calcula nem valida métricas canônicas. Preservar `atlas/match_stats.py`, `atlas/positions.py`, `atlas/match_competitive_context.py` e consultas existentes como fontes de cálculo. Extrair responsabilidades de `commission.py` gradualmente, apenas quando houver vantagem técnica demonstrável.

Não introduzir LangChain, LangGraph ou outro orquestrador. Os relatórios são fluxos definidos e devem continuar apoiados no executor existente, com confiabilidade comprovada. A análise registra `REPORT_VERSION = 34`, concorrência cloud e serialização local como base a preservar; verificar esses valores antes de alterar contratos.

## 6. Dependências e unidades plausíveis de entrega

- Segurança e corte temporal da Entrega 0 não têm dependência funcional anterior e precedem a liberação das novas evidências. AT-003 é gate específico da captura real com FC26/Live Editor; a sua pendência não bloqueia trabalho determinístico sobre dados já disponíveis.
- Após contratos básicos da Entrega 0, Entregas 1 e 2 podem ser desenvolvidas em linhas independentes. A liberação completa continua sujeita aos gates comuns.
- Entrega 3 depende da qualidade da Entrega 1; os segmentos de composição e tática dependem adicionalmente dos registros da Entrega 2. AT-025 pode avançar sobre fixtures elegíveis sem esse contexto manual.
- Entrega 4 depende da Entrega 1. A comparação individual reutiliza o modelo de profundidade funcional.
- Entrega 5 depende da segurança e dos contratos analíticos das anteriores. Controles mínimos de chamadas pertencem desde já à Entrega 0; sua ampliação e avaliação ficam na Entrega 5.

As entregas são marcos de produto; cada corte deve permanecer revisável e reversível. A sequência vigente de P01–P12 e a distribuição de testes estão no [plano de execução](plano-execucao-integracao-hub.md#prs-pequenos-propostos).

## 7. Integração com os menus atuais

| Menu atual | Evolução planejada |
| --- | --- |
| Match Center | Abas de contexto tático, escalações, formações rivais e Diário do Treinador |
| Analysis | Subaba de rotação, dificuldade e confronto contra sistemas rivais |
| Squad | Profundidade funcional, cobertura e risco |
| Player Profile | Comparação contextual, evolução de atributos e papel desempenhado |
| Technical Commission | Relatórios consolidados, evidências e acompanhamento de recomendações |
| FC26 Youth | Evolução dos jovens, metas e plano de integração |
| Imports / Snapshots | Qualidade, reconciliação e proveniência |
| Setup | Segurança e preferências dos provedores de IA |

Não adicionar menus principais nesta etapa nem espalhar a mesma análise por telas concorrentes. Alertas contextualizados no Dashboard devem consumir os contratos e achados dessas entregas, sem criar um mecanismo analítico paralelo; o momento de exposição depende de evidências suficientes.

## 8. Fora deste ciclo

- Reconstruir o sistema financeiro.
- Adicionar scouting automatizado.
- Criar novo frontend ou plataforma multiagente.
- Construir simulador completo de partidas.
- Reescrever todos os importadores Lua.

Captura espacial e eventos detalhados por minuto podem receber um spike separado. Só entram em produção após comprovar disponibilidade e estabilidade no Live Editor. Não são pré-requisito oculto da primeira versão de rotação.

Uma funcionalidade estatística confiável tem mais valor que relatórios dependentes de dados que o jogo não fornece.

## 9. Ordem de valor esportivo revisada

Após segurança, corte temporal e contrato de cobertura:

1. **Métricas determinísticas e goleiros:** reconciliar fórmulas e medir apenas fixtures cobertos.
2. **Defesa contextual e forma funcional:** expor estimativas, posição observada e amostra.
3. **Rotação e profundidade:** comparar grupos usando dificuldade pré-jogo; acrescentar tática manual quando confirmada.
4. **Base, mercado e histórico:** planos revisáveis com fonte e linha temporal.
5. **Comissão e semestre:** consumir serviços canônicos, avaliar interpretação e registrar decisões.

O Diário tático pode avançar em paralelo às etapas determinísticas. A ordem técnica detalhada está no [plano de execução](plano-execucao-integracao-hub.md#fases-e-dependências).

## 10. Parecer de arquitetura e produto preservado

A master analisada já apresenta base funcional e analítica desenvolvida. A lacuna principal é fechar o ciclo **Partida → Evidências → Contexto → Interpretação → Decisão esportiva**.

No Plymouth, a pergunta é se Providence, Oseni, Dale, Watts e os demais reservas sustentam o rendimento em condições diferentes. O caminho é conectar dados extraídos, contexto real e decisões do treinador, sem presumir que esses exemplos já foram demonstrados pelos dados.

A recomendação original é aprovar as seis entregas, começar por estabilização e qualidade e tratar a rotação contextual como primeiro grande objetivo esportivo. O registro do plano não constitui esse aceite. A evolução deve permanecer incremental, auditável, compatível com a base existente e fiel à carreira, sem transformar o jogo em um processo artificial de engenharia.

## 11. Rastreabilidade do conteúdo recebido

| Seção original | Destino nesta documentação |
| --- | --- |
| 1. Diagnóstico e diretriz | Este índice, seções 1–2 |
| 2. Cobertura da master | Este índice, seção 3 |
| 3. Riscos prioritários | Este índice, seção 4, e Entrega 0 |
| 4. Arquitetura-alvo | Este índice, seção 5 |
| 5. Roadmap e seis entregas | Seis documentos de entrega, AT-001–AT-023 preservados e AT-024/025 acrescidos |
| 6. Menus atuais | Este índice, seção 7 |
| 7. Sequência de PRs | Plano de execução P01–P12; a sequência original foi substituída |
| 8. Política de qualidade | Governança, checklist de dez critérios e gates |
| 9. Fora do ciclo | Este índice, seção 8 |
| 10. Valor esportivo | Este índice, seção 9 |
| Parecer final | Este índice, seção 10 |
