# Plano de execução da integração analítica Hub → Atlas

Revisão de **17/11/2026**. Este documento especifica trabalhos futuros; nenhum PR funcional ou benchmark de modelo foi executado aqui. [Matriz de origem e decisão](matriz-reaproveitamento-hub-atlas.md) · [Backlog](backlog-metricas-hub.md) · [Governança](governanca-e-validacao.md).

## Fases e dependências

| Fase | Pacotes e resultado revisável | Dependência real | Gate de aceite |
| --- | --- | --- | --- |
| 0. Contratos | AT-001/002/004, depois AT-005–007; credenciais, corte temporal, cobertura e proveniência | Segurança e histórico precedem publicação de novas evidências | API sem segredos; histórico sem futuro; ausente ≠ zero; testes de importação/consulta/tela |
| 1. Determinístico imediato | H02–H10, H14, H19–H22, H26–H27, H29–H32 nos serviços Atlas existentes | Fase 0 por contrato, não por AutoCapture real concluído | Fórmula, unidade, recorte e amostra em cada resposta; soma/denominador reproduzível; visão completa além de Top-N |
| 2. Goleiros e defesa | AT-024/025; H11–H17 | Cobertura por fixture e posição/minutos confiáveis | Troca de GL indeterminada; setor estimado; pares apenas co-presença até cronologia real |
| 3. Contexto e carreira | AT-008–019; tática observada, rotação, base, mercado, histórico | Dados determinísticos não dependem do diário; formação rival e estrutura dependem de observação confiável | Confirmado, estimado e desconhecido separados; comparação com amostra; plano revisável |
| 4. Relatórios e auditoria | AT-021–023; H33–H34; relatório semestral e avaliação independente | Mesmos serviços canônicos, controles cloud da fase 0 | Evidências ligadas ao indicador; avaliação humana separada da geração; revisão de custo e privacidade |
| 5. Homologação externa | AT-003 e oportunidades BL-03/08/09/10/11 | FC26/Live Editor, save e campos reais | Uma cópia segura do save para ciclos controlados; log e export por partida; pendência declarada se não executado |

AT-020 conserva seu número histórico, mas fica **adiado e fora deste ciclo**. Testes funcionais cloud controlados de AT-004/023 continuam possíveis; não são comparação de modelos nem benchmark. A fase 5 pode ocorrer em paralelo às fases analíticas; sua pendência limita alegações sobre captura, sem impedir trabalho com dados já disponíveis. Não executar replay histórico em lote nem usar banco ativo como bancada.

## PRs pequenos propostos

| PR | Corte | AT / H principal | Dependências | Teste e reversão |
| --- | --- | --- | --- | --- |
| P01 | Segurança/configuração cloud | AT-001/004 | Nenhuma | API sanitizada, migração protegida e teste cloud controlado; desabilitar cloud se necessário |
| P02 | Corte temporal histórico | AT-002 | Nenhuma | Snapshot passado não lê posição futura; reversão de código preserva dados |
| P03 | Cobertura e reconciliação canônica | AT-005–007; H01–H05, H07, H32 | P02 | Fixtures completos/parciais/ausentes, xG/pênalti, universo exibido; manter fontes originais |
| P04 | Goleiros | AT-024; H11–H13 | P03 | Um GL, dois GL, zero/ausente; ocultar indicador incompatível |
| P05 | Defesa contextual | AT-025; H14–H17 | P03 | Min/posição/xGA faltantes, corte setorial, dupla substituída; desativar painel derivado |
| P06 | Forma, função e elenco | AT-014/016/017; H06, H08–H10, H19, H22, H26, H28–H31 | P03 | Posição nominal vs observada, últimas cinco, aliases; conservar agregadores Atlas |
| P07 | Contexto tático manual | AT-008–011; H18, H35 | P02/P03 | XI parcial e rival desconhecido; dados manuais versionados e atribuídos |
| P08 | [Rotação e modelo de jogo](p08-rotacao-modelo-jogo.md) | AT-012/013/015; H20–H21 | P03; P07 só para funções táticas | Posse ausente, rival pré-jogo, grupo e amostra; regra de posse em espera |
| P09 | Base e transição | AT-018; H23–H25 | P03/P06, BL-11 para score 5x5 | 5x5 isolado não promove; plano individual revisável; score condicionado |
| P10 | Mercado e sucessão | AT-019; H27 | P03/P06 | Sem proposta explícita, saída simulada, cobertura interna; sem transferência automática |
| P11 | Comissão e semestre | AT-021–023; H33–H34 | P03–P10 aplicáveis | Semestre com fonte e exclusão, avaliação independente, custo/privacidade |
| P12 | Homologação AutoCapture | AT-003; H05/H17/H18/H20/H23 se captura alterar contrato | Ambiente real | Uma cópia do save reutilizada; ciclos e falhas documentados; não mudar dados ativos |

P04–P06 podem ser desenvolvidos em paralelo depois de P03, respeitando os contratos comuns. P07 não é pré-requisito para partes determinísticas de P08. P09 pode entregar plano/GER/POT sem score 5x5. P12 não presume conserto nem nova captura antes de registrar os fatos observados. Cada PR muda o mínimo necessário, declara cobertura e pode ser revertido sem apagar observações manuais.

## Rastreabilidade por capacidade

A origem, fórmula e classificação A–G estão na [matriz](matriz-reaproveitamento-hub-atlas.md). “Teste” nesta tabela é o **caso exigido no futuro PR**, não resultado executado. Caminhos Atlas são componentes a reutilizar ou estender; a escolha final deve ser confirmada no diff do PR.

| H | AT | Componente Atlas | PR | Teste e critério de aceite |
| --- | --- | --- | --- | --- |
| H01 | 005/007 | `server_query_dashboard.py`, `server_query_matches.py` | P03 | Fixture completo/parcial; campo ausente fica indisponível |
| H02 | 006/007 | `match_stats.py`, `commission.py` | P03 | Soma G/A por fonte e período sem dupla contagem |
| H03 | 007/016 | `match_stats.py` | P03 | /90 e min/gol com zero/ausência e amostra |
| H04 | 006/007 | `match_stats.py` | P03 | xG e NPK-xG identificados; pênalti não mistura fórmulas |
| H05 | 005/007 | `match_stats.py` | P03/P12 | Enfiadas/cruzamentos reais; quebra-linhas fica pendente |
| H06 | 007/016 | `commission.py`, `server_query_history.py` | P06 | Últimas cinco em ordem esportiva; nota ponderada |
| H07 | 007 | `commission.py`, `match_stats.py` | P03 | 300/3 e 450/5 preservados para Comissão; demais cortes rotulados |
| H08 | 016 | `positions.py`, `commission.py` | P06 | Função e peso explicados; índice Sheffield não copiado |
| H09 | 012/016 | `commission.py` | P06 | Hierarquia ausente gera abstenção |
| H10 | 014/016 | `commission.py`, `positions.py` | P06 | Rival ativo, mesma função, amostra elegível |
| H11 | 024 | `match_stats.py`, `server_query_entities.py` | P04 | Defesas/chutes no alvo, denominador e fonte expostos |
| H12 | 024 | `match_stats.py` | P04 | xGA−GA e /90 só com GL contextual elegível |
| H13 | 024 | `server_query_matches.py` | P04 | Dois GL no fixture não recebem contexto duplicado |
| H14 | 005/007/025 | `match_stats.py` | P03/P05 | Ações individuais somadas só onde há cobertura |
| H15 | 025 | `match_stats.py`, `server_query_analysis.py` | P05 | Contexto por minutos rotulado estimado |
| H16 | 025 | `positions.py`, `server_query_analysis.py` | P05 | Setor com posição confiável e corte ≥270 min |
| H17 | 025 | `server_query_analysis.py` | P05/P12 | Co-presença distinta de minutos juntos reais |
| H18 | 009/015 | `server_query_matches.py`, dados manuais | P07 | XI parcial não confirma estrutura |
| H19 | 016 | `positions.py`, `commission.py` | P06 | Sem minutos por função, não dividir nota entre papéis |
| H20 | 013/015 | `commission.py`, `match_stats.py` | P08/P12 | Posse ausente não gera rótulo “sem posse” |
| H21 | 013 | `match_competitive_context.py` | P08 | Contexto pré-jogo usa apenas snapshot anterior |
| H22 | 014/016 | `positions.py`, `server_query_entities.py` | P06 | Posição cadastrada e observada distinguíveis |
| H23 | 018 | `server_query_management.py` | P09/P12 | Score 5x5 só após mapeamento de eventos |
| H24 | 018 | `server_query_management.py` | P09 | 5x5 isolado não qualifica pré-profissional |
| H25 | 018 | `server_query_management.py` | P09 | Prioridade de minutos revisável, com amostra |
| H26 | 017/018 | `server_query_analysis.py` | P06/P09 | Evolução e produção em dimensões separadas |
| H27 | 019 | `player_finance.py`, `positions.py` | P10 | Pressão externa só com registro explícito |
| H28 | 018/019 | `manual_data.py`, `server_query_analysis.py` | P09/P10 | Plano revisável e universo >40 sem truncamento |
| H29 | 006/017 | `server_query_history.py` | P06 | Alias/ID por carreira sem informação futura |
| H30 | 017/022 | `server_query_entities.py` | P06/P11 | Histórico completo com amostra e fonte |
| H31 | 006/022 | `server_query_analysis.py` | P06/P11 | Competição canônica e estação sem duplicata |
| H32 | 007/022 | `server_query_dashboard.py`, frontend existente | P03/P11 | Universo aplicável = universo exibido; Top-N separado |
| H33 | 022 | `server_query_analysis.py` | P11 | Recorte semestral com fonte e cobertura |
| H34 | 021/022 | `commission.py`, `views_analysis.ts` | P11 | Revisão independente e ficha integral |
| H35 | 009/010 | `positions.py`, `server_query_matches.py` | P07 | Formação própria não atribuída ao rival |

## Risco, pendência e aceite global

1. **Risco de semântica:** nenhuma métrica com fonte, unidade, denominador ou amostra divergente entra sob o mesmo nome. Exemplos de fronteira obrigatórios estão em BL-02/05/06/08/10/11.
2. **Risco temporal:** agregados devem respeitar carreira, snapshot e ordem esportiva. Testar contra observação futura e alias de competição.
3. **Risco de cobertura:** dados faltantes permanecem ausentes. API e tela expõem universo aplicável, linhas cobertas e exclusões. Relatório semestral reutiliza os agregadores do Atlas; não recalcula no texto de IA.
4. **Risco operacional:** AT-003 só é homologado em FC26/Live Editor com export e logs reais. Usar uma cópia segura do save para todos os ciclos controlados, preservando o original.
5. **Risco de interpretação:** relatórios separam fato, estimativa, hipótese e observação do treinador. AT-021 usa revisão independente; AT-023 registra chamadas cloud controladas, limite, privacidade e custo observado. Não inferir resultado de benchmark AT-020.

Aceite global requer matriz H01–H35 resolvida por AT/PR/teste, BL fechado ou explicitamente pendente, novos indicadores consumidos nos menus existentes, testes de contrato e integração, e revisão esportiva do semestre com casos negativos. Os PRs funcionais terão seus próprios aceites; esta revisão documental não os antecipa.
