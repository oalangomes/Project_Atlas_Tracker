# Entrega 0 — Estabilização, segurança e contratos

[Índice](README.md) · [Governança](governanca-e-validacao.md) · Próxima: [Entrega 1](entrega-1-qualidade-rastreabilidade.md).

**Prioridade:** P0. **Estado:** planejada. **Dependências funcionais:** nenhuma. Homologação do AutoCapture exige FC26/Live Editor; testes reais cloud exigem provedor configurado e escopo consentido.

## Objetivo e condição de conclusão

Garantir confiança nos dados e mecanismos atuais antes de ampliar sua interpretação. Ambiente local e cloud devem ser utilizáveis sem comprometer privacidade, integridade histórica ou estabilidade conhecida. Esta entrega desbloqueia as demais; implementação parcial não equivale a conclusão do P0.

| Pacote | Implementação | Critério de aceite original |
| --- | --- | --- |
| AT-001 | Proteger credenciais e sanitizar a configuração da IA | Nenhuma chave completa em GET, logs, frontend ou exportações |
| AT-002 | Corrigir recuperação temporal de posições | Nenhum snapshot posterior influencia consultas históricas |
| AT-003 | Validar AutoCapture pós-partida | Capturas repetidas reais sem erros nativos observados no cenário de homologação |
| AT-004 | Ampliar CI e testes de integração | Importação, cloud, cache, posições e recuperação cobertos |

Arquivos centrais indicados na análise: `server_http.py`, `commission.py`, `server_query_matches.py`, `positions.py`, exporters Lua e workflows GitHub. Confirmar caminhos reais antes das alterações.

## AT-001 — Credenciais e configuração pública

### Diagnóstico a confirmar

Segundo a análise estática, `GET /api/llm/config` expõe `**config`, incluindo `keys`; o frontend as mantém em `state.llmKeys`; o backend persiste JSON em `app_settings`. O bind localhost reduz exposição, mas não torna seguro devolver segredos à interface.

### Cortes de implementação

1. **Contrato público e fronteira do segredo:** inventariar GET, respostas de atualização, estado frontend, logs, erros, exportações e cache. Definir resposta permitida por lista explícita: provedor, modelo, indicador de configuração e sufixo mascarado. Campos operacionais adicionais só se forem necessários e não secretos.
2. **Armazenamento protegido:** escolher mecanismo protegido por usuário no Windows, por exemplo Credential Manager ou proteção equivalente, após verificar compatibilidade do ambiente. Backend resolve o segredo apenas para a chamada do provedor. Se a proteção estiver indisponível, não persistir em texto puro; comunicar a condição e preservar uso local.
3. **Migração:** reconhecer configurações antigas, transferir chaves para a proteção, verificar recuperação no usuário correto e só então remover valores legíveis ativos. Falha não pode apagar o único segredo nem iniciar chamadas com configuração incoerente. Reexecução deve ser segura. Documentar que backups históricos anteriores podem continuar contendo chaves e orientar seu tratamento sem expô-las.
4. **Setup:** interface mostra presença e sufixo, permite substituir/remover e não recebe o valor completo de volta. Entrada de chave existe apenas durante a operação necessária; não reidratar o segredo em estado persistente frontend.
5. **Integração e privacidade:** erro, quota, timeout e falha de migração devem produzir mensagens sanitizadas. Separar consentimento cloud da mera existência da chave.

### Validação e aceite

- Verificar respostas públicas, logs capturados, mensagens de erro, exportações e estado persistido com um segredo sintético identificável, incluindo falhas do provedor.
- Cobrir criação, substituição, remoção, migração repetida, falha da proteção e execução com outro contexto de usuário.
- Confirmar que armazenamento ativo não mantém o segredo legível e que a chamada autorizada ainda usa o valor correto.
- Verificar frontend e build; registrar validação Windows do mecanismo escolhido separadamente dos testes simulados.
- Não usar chaves reais como fixtures ou evidência publicada.

**Reversão:** desativar cloud e manter recursos locais se necessário; não restaurar endpoints que devolvam segredos nem backups legíveis de credenciais. Documentar compatibilidade da migração e eventual necessidade de reconfigurar a chave.

## AT-002 — Corte temporal das posições

### Diagnóstico a confirmar

`historical_observed_positions()` filtra carreira e fixture, mas a consulta descrita não limita explicitamente `import_sequence` pelo snapshot selecionado. Uma consulta histórica pode incorporar informação registrada depois.

### Cortes de implementação

1. **Elegibilidade temporal:** definir snapshot selecionado como limite dentro da carreira correta; usar a sequência temporal canônica existente e tratar empates/ausências explicitamente. Não comparar identificadores de carreiras diferentes como se fossem uma linha do tempo única.
2. **Consulta e propagação:** aplicar o corte na recuperação e verificar os consumidores de posições históricas, sem trocar posição jogada por posição natural quando faltar observação.
3. **Proveniência:** retornar a origem e snapshot da observação recuperada; impedir que cache antigo contorne o corte.
4. **Regressão:** validar fronteiras e confirmar que recuperação anterior elegível continua funcionando.

### Validação e aceite

- Criar cenário com carreira A, snapshots anterior, selecionado e posterior e uma observação que só existe no posterior. No selecionado, ela deve continuar ausente; no posterior, deve ser elegível.
- Cobrir observação anterior recuperável, observação no limite, fixture diferente e carreira B com identificadores semelhantes.
- Cobrir ordenação fora da ordem física de inserção e ausência de fonte válida.
- Consultar API histórica e consumidor de relatório, além da função isolada; confirmar que a proveniência corresponde ao resultado.

**Reversão:** preservar dados importados; reverter código somente com o limite temporal garantido ou desativar a recuperação afetada. Invalidar caches incompatíveis conforme o mecanismo existente.

## AT-003 — AutoCapture pós-partida

### Limite da evidência atual

A documentação registra falhas nativas do FC26 em transições pós-partida e mudanças sucessivas no ciclo de handlers Lua. Testes atuais de contrato não comprovam estabilidade real no Live Editor. Não atribuir crash a uma causa específica sem reprodução.

### Cortes de implementação e homologação

1. **Preparação verificável:** confirmar versões, configuração, cópia segura do save, backup e roteiro de restauração. Consultar o [histórico de hotfix pós-partida](../autocapture-postmatch-hotfix-2026-11-06.md). Definir antecipadamente quantidade de ciclos e cenários do lote de homologação, justificando a amostra.
2. **Linha de base:** executar captura, final de partida, retorno ao Career Hub, reativação e importação com a configuração atual. Registrar ciclos bem-sucedidos e falhas, sem alterar automação antes de observar a base.
3. **Correção restrita, se necessária:** modificar apenas handlers/ciclo relacionados ao problema reproduzido, preservando a leitura do jogo. Repetir o roteiro após cada alteração relevante.
4. **Homologação repetida:** verificar arquivos produzidos, completude, vínculo correto de carreira/fixture, duplicação, reativação e importação no Atlas. Interrupção ou crash permanece resultado do lote, sem apagá-lo com uma nova tentativa.
5. **Liberação do escopo comprovado:** documentar o cenário validado e manter automações mais agressivas desabilitadas até evidência correspondente.

### Evidência e aceite

Registrar versão FC26/Live Editor/exporter, configuração, sequência dos passos, quantidade de ciclos, horários, arquivos, logs disponíveis e resultados de importação. Ausência de erro nativo observado vale apenas para esse cenário e amostra.

Sem execução real, AT-003 permanece pendente, mesmo com testes Lua de contrato verdes. Não substituir essa homologação por CI ou teste simulado.

**Reversão:** restaurar scripts/configuração conhecidos, desativar a automação afetada e usar o backup verificado se a cópia de homologação exigir restauração. Não testar alterações arriscadas no único save de carreira.

## AT-004 — Integração, cloud e CI

### Cortes de implementação

1. **Inventário da suíte:** mapear testes e workflows existentes, identificar lacunas e estabelecer a bateria afetada por cada PR. Preservar assertions; não mascarar falhas com skips ou retries.
2. **Provedores simulados:** testar respostas válidas e inválidas, erro de autenticação, indisponibilidade, quota, timeout, falha de rede e resposta incompleta. Simulações devem controlar o resultado sem depender da internet.
3. **Políticas de execução:** cobrir ordem e limites de failover, encerramento após o orçamento, cancelamento/timeout e execução offline. Falha de provedor não deve produzir laço de chamadas nem mudança silenciosa para cloud sem consentimento.
4. **Cache e concorrência:** testar acerto, invalidação por versão/contexto, isolamento por carreira/snapshot/período e política de modelo/provedor. Preservar concorrência cloud e serialização local descritas no plano, verificando limites com chamadas instrumentadas.
5. **Importação e recuperação:** cobrir fluxo de importação, consultas históricas, posições e comportamento com dados parciais. Somar testes de segurança do AT-001 e de história do AT-002.
6. **CI consolidada:** ligar os contratos às verificações de Python, frontend e JS gerado conforme estrutura existente. Workflows parciais não substituem a regressão necessária.
7. **Testes reais controlados:** após simulados, executar por provedor disponível com escopo pequeno, dados apropriados, consentimento e limites. Registrar provedor/modelo, cenário, chamadas, falhas e custos quando observáveis.

### Matriz mínima

| Eixo | Casos necessários | Evidência esperada |
| --- | --- | --- |
| Segurança | GET, erro, log, exportação, migração | Segredo sintético não exposto |
| Cloud | Sucesso, timeout, quota, autenticação, resposta inválida | Resultado e fallback corretos, com limite |
| Offline | Sem chave, sem rede, sem provedor | Aplicação determinística utilizável |
| Cache | Acerto, mudança de entrada/versão, carreiras e datas | Reuso válido sem contaminação |
| Execução | Cloud concorrente, local serial, cancelamento | Contagem e simultaneidade controladas |
| Dados | Importação parcial, posições e fronteira temporal | Ausência explícita e origem correta |
| Interface | Setup, erro e estado mascarado | Build e fluxo integrado verificados |

**Reversão:** reverter integração defeituosa e desabilitar provedor afetado, preservando testes que demonstraram a falha e uso local. Não declarar testes reais executados quando só houve simulação.

## Sequência e fronteira de saída

PRs propostos 1 e 2 podem seguir linhas independentes; AT-003 depende do ambiente real. AT-004 acompanha cada mudança e consolida a regressão no PR 4, sem postergar os testes necessários aos PRs iniciais.

- [ ] AT-001 validado, incluindo proteção Windows e migração.
- [ ] AT-002 validado na função e nos consumidores históricos.
- [ ] AT-003 homologado no escopo real registrado.
- [ ] AT-004 integrado à CI e testes reais disponíveis identificados.
- [ ] Checklist transversal aplicado, limitações e reversão documentadas.

Nenhuma caixa está marcada nesta fase documental.
