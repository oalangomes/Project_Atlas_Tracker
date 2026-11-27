# Plano de execução da integração analítica Hub → Atlas

Revisão de **17/11/2026**, com correção de escopo do P09 em **22/11/2026**. Este documento especifica trabalhos futuros; seus critérios não constituem homologação. [Matriz de origem e decisão](matriz-reaproveitamento-hub-atlas.md) · [Backlog](backlog-metricas-hub.md) · [Governança](governanca-e-validacao.md).

## Fases e dependências

| Fase | Pacotes e resultado revisável | Dependência real | Gate de aceite |
| --- | --- | --- | --- |
| 0. Contratos | AT-001/002/004, depois AT-005–007; credenciais, corte temporal, cobertura e proveniência | Segurança e histórico precedem publicação de novas evidências | API sem segredos; histórico sem futuro; ausente ≠ zero; testes de importação/consulta/tela |
| 1. Determinístico imediato | H02–H10, H14, H19–H22, H26–H27, H29–H32 nos serviços Atlas existentes | Fase 0 por contrato, não por AutoCapture real concluído | Fórmula, unidade, recorte e amostra em cada resposta; soma/denominador reproduzível; visão completa além de Top-N |
| 2. Goleiros e defesa | AT-024/025; H11–H17 | Cobertura por fixture e posição/minutos confiáveis | Troca de GL indeterminada; setor estimado; pares apenas co-presença até cronologia real |
| 3. Contexto e carreira | AT-008–019; tática observada, rotação, base, mercado, histórico | Dados determinísticos não dependem do diário; formação rival e estrutura dependem de observação confiável | Confirmado, estimado e desconhecido separados; comparação com amostra; plano revisável |
| 4. Relatórios e auditoria | AT-021–023; H33–H34; relatório semestral e avaliação independente | Mesmos serviços canônicos, controles cloud da fase 0 | Evidências ligadas ao indicador; avaliação humana separada da geração; revisão de custo e privacidade |
| 5. Homologação externa | AT-003 e oportunidades BL-03/08/09/10 | FC26/Live Editor, save e campos reais | Uma cópia segura do save para ciclos controlados; log e export por partida; pendência declarada se não executado |

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
| P09 | [Relatório da base e trajetória cadastral](p09-base-transicao.md) | AT-018; H24–H25 adaptados, H28 | P03; contratos P06 quando disponíveis | Relatório expansível por jovem; GER/POT por snapshot e posição profissional apenas quando observada; sem score ou minutos da base |
| P10 | Mercado e sucessão — cancelado | AT-019; H27 | — | Simulador removido do Atlas por decisão do usuário |
| P11 | [Comissão e semestre](p11-comissao-semestre.md) | AT-021–023; H33–H34 | P03–P09 aplicáveis | Semestre com fonte, exclusão e cobertura; validação posterior, cache e consentimento cloud; sem geração automática |
| P12 | Homologação AutoCapture | AT-003; H05/H17/H18/H20 se captura alterar contrato | Ambiente real | Uma cópia do save reutilizada; ciclos e falhas documentados; não mudar dados ativos |

P04–P06 podem ser desenvolvidos em paralelo depois de P03, respeitando os contratos comuns. P07 não é pré-requisito para partes determinísticas de P08. P09 usa os snapshots da base e o relatório de posição; não depende de captura de partidas 5x5 ou 11x11 da base, que não está disponível. Se P06 ainda não estiver integrado, reaproveitar apenas os contratos necessários sem incorporar sua branch divergente diretamente. P12 não presume conserto nem nova captura antes de registrar os fatos observados. Cada PR muda o mínimo necessário, declara cobertura e pode ser revertido sem apagar observações manuais.

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
| H23 | 018 | Sem fonte Atlas de partidas da base | Fora do P09/P12 | Score 5x5 do Hub não é portado; falta fonte para verificar seus insumos |
| H24 | 018 | `server_query_management.py`, snapshots e elenco | P09 | GER/POT datados; passagem ao elenco profissional só se observada; sem índice de prontidão |
| H25 | 018 | Planos manuais da base | P09 | Prioridade de minutos é intenção do treinador, sem cálculo de minutos da base |
| H26 | 017/018 | `server_query_analysis.py` | P06/P09 | Evolução e produção em dimensões separadas |
| H27 | 019 | — | P10 cancelado | Fora do escopo ativo |
| H28 | 018 | `manual_data.py`, `server_query_analysis.py` | P09 | Universo de jovens sem truncamento |
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

## Enriquecimento do Atlas com dados persistidos no save

**Proposta de 26/11/2026.** Reaproveitar o extrator binário do Sheffield Hub
para publicar campos do `CmMgr` nas telas atuais do Atlas. A posse já importada
é a referência de integração. O primeiro resultado será um comparativo de
passes por equipe que funciona mesmo em partidas sem MatchStats. A validação
dos campos usa os bytes do save, pares de saves e invariantes verificáveis.
Dados de imagem, OCR e transcrição ficam fora do escopo. [Evidência atual no Atlas](p03-contrato-evidencias.md#posse-persistida-no-save-da-carreira).

**Entrega 1 implementada em 27/11/2026.** [Contrato e operação dos passes no Match Center](p03-contrato-evidencias.md#passes-detalhados-do-save-no-match-center).

### Reuso entre os projetos

- O **Sheffield Hub** mantém o código-fonte do decodificador e os testes do
  formato. Isolar o núcleo de leitura de `mxif`, `mham` e `mflp`, com entradas
  em bytes e saída independente de clube. Reaproveitar a leitura das tabelas
  e a identidade de carreira do Hub nas etapas que precisarem delas. Fixar
  a revisão de origem e registrar a versão na evidência. O ponto de partida
  verificado é `325481c596e05cca5cee15049012a216af16618d`. [Extrator do Hub](https://github.com/oalangomes/ea-fc-sheffield-hub/blob/325481c596e05cca5cee15049012a216af16618d/scripts/fc26_save_extract.py).
- O **Atlas** usa um leitor próprio de `mxif` e `mham` adaptado dos
  mapeamentos do Hub. O leitor recebe bytes, deriva os limites dos blocos
  das contagens declaradas e funciona offline em qualquer carreira com o
  formato compatível. O Atlas mantém o vínculo com a partida, o SQLite, as
  consultas e a apresentação. A posse e os passes passam pelo mesmo leitor.
  [Leitor de partidas](../../atlas/fc26_save_match.py) · [Watcher](../../atlas/watcher.py) · [Importação atual de posse](../../atlas/fc26_save_possession.py) · [Contrato de evidências](../../atlas/metric_evidence.py).

### Ordem de entrega e critérios de aceite

| Ordem | Entrega | Aceite |
| --- | --- | --- |
| 1 | **Leitor compartilhado e passes no Match Center.** Compatibilizar `mxif` de 36 e 40 slots, usar `mham` para validar o placar e publicar posse, enfiadas completas por baixo e pelo alto, passes que rompem linhas, passes pela ponta e tentativas de tabela. | Sheffield e Plymouth decodificam com a mesma versão. No Plymouth–Stevenage, aparecem 46% a 54% de posse, 32 enfiadas por baixo e 3 pelo alto do Plymouth, 4 passes que rompem linhas e 6 tentativas de tabela. A API e o comparativo mostram a fonte e funcionam quando só há dados do save. |
| 2 | **Participação e rotação com `mflp`.** Ler a quantidade de registros declarada no cabeçalho. Entregar titulares, reservas utilizados, posição registrada e minutos internos quando comprovados. Parear substituições quando a evidência identifica quem entrou e quem saiu. | Cobrir as variantes conhecidas de 30, 33 e 36 registros com evidência de layout. Reproduzir o par Sheffield com 11 titulares e 16 participantes. Em casos com delta de titularidade inconclusivo, publicar somente os campos confirmados. Verificar reset de contador, salto de jogos, substituição simultânea ambígua e troca de posição. |
| 3 | **Tática gravada e gestão.** Começar pelas escalações e mentalidades salvas, histórico do técnico e lesões com data e duração. Priorizar pré-contratos e histórico agregado da academia após confirmar IDs, unidades e os estados de cada registro. | Vincular cada linha ao clube ou jogador correto no snapshot selecionado e testar carreiras diferentes e mudança de temporada. Mostrar a tática como configuração gravada. Publicar dados de lesão, mercado e academia apenas com campo e significado verificados. |
| 4 | **Snapshot do save como alternativa ao Lua.** Normalizar as tabelas persistidas no contrato atual do Atlas e rodar as duas ingestões em paralelo para medir cobertura. | Reconciliar identidade, elenco, contratos, empréstimos, academia, notas, calendário global e estatísticas de temporada por competição. Registrar diferenças por campo, valor e cobertura. Habilitar o snapshot sem Lua após aceite dos campos obrigatórios em carreiras, temporadas e competições representativas. [Contrato atual](../../schemas/FC26_CareerTracker_Snapshot_Contract_v1.2.0.json). |

### Regras de vínculo e publicação

- Ler o save em modo somente leitura a partir de uma cópia estável e
  reaproveitar a decodificação enquanto o arquivo estiver igual. Resolver a
  carreira e uma partida única com data, clubes, placar e participantes.
  Registrar a versão do leitor, o hash do save ou bloco, a origem do campo
  e o corte de snapshot. Layout desconhecido ou vínculo ambíguo ficam
  registrados como indisponíveis e preservam os dados já importados.
- Publicar dados diretos e deltas com origem, unidade e recorte no mesmo
  contrato usado pela API, pelo Match Center e pelos relatórios. Um zero
  confirmado entra na cobertura. Campo ausente fica indisponível. Quando
  duas fontes trazem o mesmo dado, contar a partida uma vez. Registrar
  divergências para revisão e preservar as versões de origem. Manter o xG
  do save identificado pela fonte até concluir o caso com pênalti.
- Deltas de gols, assistências, titularidades e aparições exigem dois saves
  da mesma carreira com sequência de um jogo comprovada pelo `mham`.
  Mudanças de elenco, contadores reiniciados e intervalos com múltiplos
  jogos precisam de testes próprios. O `mxif` sustenta apenas o último
  jogo concluído de cada save disponível. [Regra de sequência do Hub](https://github.com/oalangomes/ea-fc-sheffield-hub/blob/325481c596e05cca5cee15049012a216af16618d/docs/fc26-professional-match-assembler.md#one-match-sequence-proof).

### Liberação

Validar primeiro em base isolada, com saves locais de Plymouth e Sheffield.
Por partida e por campo, registrar a entrada, o valor esperado, o valor
obtido e o motivo de ausências. Cobrir repetição de save, partidas com gols
contra ou pênaltis, lado visitante, importação fora de ordem, versões
incompatíveis e ausência de MatchStats. Verificar que o histórico preexistente
e os resultados de consultas por snapshot permanecem íntegros e medir a
varredura com os arquivos inalterados. Liberar passes e participação em
cortes independentes.

O MatchStats segue como complemento para xA, pré-assistências, passes sob
pressão, perdas de posse e cartões enquanto esses campos não tiverem leitura
persistida validada. A decisão de retirar o Live Editor por completo fica
para depois da avaliação da paridade do snapshot e da cobertura avançada.
