# Governança, validação e execução do plano

[Voltar ao índice](README.md).

Base documental original: análise estática de 10/11/2026, commit `8f063cf`. Revisão de 17/11/2026: Atlas `2737b53a8bcfaebd0be813f92250b14ddc3a3969` e Hub `6f235e70746fe014b3a8aa92f1cbba2e7ca7d2d2`. AT-001/002 estão parcialmente implementados, sem aceite integral; AT-020 está adiado. O plano registra decisões futuras, não resultados de homologação ou benchmark.

## Unidade de trabalho e conclusão

Cada corte de implementação deve entregar um comportamento observável, seu contrato, validação pertinente, limites e reversão. Migração, backend, interface e integração podem estar em commits separados; um recurso só deve ser liberado quando o fluxo necessário estiver completo.

Estados sugeridos para acompanhamento: planejado, em implementação, implementado aguardando validação, validado no escopo descrito e aceito. Dependências externas pendentes devem ser identificadas pelo nome e pela evidência ausente. Não transformar testes de contrato em homologação real nem alteração de código em aceite esportivo.

Para cada pacote, registrar no futuro:

| Campo | Conteúdo obrigatório |
| --- | --- |
| Identificação | AT correspondente, PR, commit efetivamente validado |
| Escopo | Comportamento e superfícies alteradas |
| Dependências | Contratos usados e gates pendentes |
| Contexto | Ambiente, carreira, snapshot, período e fixture quando aplicável |
| Evidência | Comandos, resultados, amostra, artefatos e limitações |
| Reversão | Código, migrações, configuração, dados e caches afetados |
| Aceite | Critérios cumpridos, não cumpridos e responsável pela avaliação necessária |

Não preencher esses campos com resultados presumidos. Dados de teste devem preservar separação entre carreiras, fontes e datas. Não reutilizar resultados de um workspace para comprovar comportamento de outro.

## Sequência recomendada de PRs

A sequência vigente é [P01–P12 no plano de execução](plano-execucao-integracao-hub.md#prs-pequenos-propostos), com matriz individual H → AT → componente → PR → teste → aceite. São identificadores de planejamento, sem correspondência automática com PRs existentes. A sequência original de dez PRs, cujo último incluía benchmark AT-020, foi substituída. Os ATs originais permanecem nas seis entregas; AT-024/025 foram acrescidos.

P01/P02 fecham segurança e temporalidade; P03 fixa cobertura e fórmula; P04–P06 podem evoluir em paralelo depois disso. P07 tático só bloqueia alegações que precisam de XI/observação. P12 é homologação externa com uma cópia do save e não impede cálculos determinísticos baseados em dados já disponíveis. AT-004 acompanha cada contrato e teste cloud controlado. AT-020 permanece fora do ciclo.

Cada PR registra IDs H/AT/BL, amostra, diferenças de fórmula e estado dos bloqueios. O fluxo API → tela → Comissão → relatório semestral usa um serviço canônico por métrica, sem gerador Hub paralelo.

## Checklist obrigatório por PR

Estado desta revisão: **nenhum PR funcional novo validado por este documento**. Copiar para cada PR e marcar somente com evidência correspondente.

- [ ] Não modifica o save nem depende de escrita na memória do FC26.
- [ ] Preserva isolamento por carreira, snapshot e período histórico.
- [ ] Reutiliza métricas e serviços existentes antes de criar novos.
- [ ] Possui testes unitários e de integração para os contratos alterados.
- [ ] Distingue fonte extraída, derivação, observação e estimativa.
- [ ] Trata dados ausentes como ausentes, não como zero.
- [ ] Mantém a aplicação funcional sem provedor de IA.
- [ ] Verifica build TypeScript e JavaScript gerado.
- [ ] Documenta limitações e não apresenta hipóteses como fatos.
- [ ] Inclui evidência de validação e estratégia de reversão.

Em PR exclusivamente documental, explicar os itens não aplicáveis sem afirmar execução funcional. O checklist de implementação permanece pendente até a entrega correspondente.

## Camadas de validação

| Camada | O que deve comprovar | O que não comprova sozinha |
| --- | --- | --- |
| Estática | Contratos de código, uso de fontes e superfícies de segredo | Funcionamento no Windows ou estabilidade do jogo |
| Unitária | Regras determinísticas, fronteiras temporais e estados ausentes | Persistência, frontend e provedor real |
| Integração | API, banco de teste, importação, cache e provedores simulados | Quotas reais, qualidade esportiva ou ausência de crash nativo |
| Interface | Fluxo visível, persistência e apresentação da proveniência | Causalidade esportiva ou dados que não foram capturados |
| Execução controlada | Windows/Live Editor e provedores reais no escopo testado | Estabilidade universal ou homologação de outro cenário |
| Avaliação esportiva | Conclusões específicas, rastreáveis e qualificadas | Generalização além das amostras e cenários avaliados |

A CI deve validar o conjunto afetado pelo PR. Workflows específicos do frontend e da Comissão Técnica não substituem regressão do Atlas. Definir comandos reais na implementação, com base na suíte existente, e registrar o SHA dos resultados; não inventar nomes de testes ou comandos neste planejamento.

## Contrato transversal de evidência

AT-007 consolida a implementação do catálogo. As demais entregas devem usar a mesma semântica desde o início:

- **Extraído:** valor observado em uma fonte do jogo/importação, com identificação da origem.
- **Derivado:** cálculo determinístico com fórmula, entradas, período e versão.
- **Observação manual:** registro atribuído ao treinador, datado e separado do extraído.
- **Estimado:** hipótese documentada, com evidências, alternativas e sustentação qualitativa.
- **Indisponível:** ausência ou cobertura insuficiente; nunca substituir por zero.

Referências de carreira, snapshot elegível, fixture/período, fonte, unidade e versão devem acompanhar os indicadores. Distinguir data do evento, data de observação e data de registro/importação, especialmente em avaliações históricas. Um registro inserido mais tarde não pode aparecer silenciosamente como informação conhecida na época.

## Reversão e preservação dos dados

Antes de migrações persistentes, confirmar workspace e banco ativo, produzir backup consistente e verificável e definir restauração. Em SQLite ativo com WAL, usar mecanismo consistente de backup; não presumir que copiar apenas o arquivo principal é suficiente.

Migrações devem preservar originais, proveniência e vínculo de identidade. Documentar compatibilidade ao voltar o código. Quando um downgrade não puder consumir o esquema novo, declarar a necessidade de restaurar backup em vez de sugerir reversão parcial insegura.

Credenciais exigem tratamento próprio: não criar cópias legíveis para rollback. Retorno a uma versão que exponha segredos não é estratégia válida de segurança. Preferir desativar cloud e solicitar reconfiguração protegida conforme o plano AT-001.

Alterações em cálculo, contexto ou observações podem invalidar cache. Usar a política/versionamento existente e registrar a necessidade de regeneração, sem reprocessamento histórico completo automático antes dos gates da Entrega 5.

## Liberação e limites externos

Testes reais cloud precisam de provedor configurado, escopo controlado e consentimento aplicável ao envio. Sem chave ou conexão, executar a cobertura simulada e registrar o teste real pendente; manter modo offline funcional.

AutoCapture exige cópia segura do save e ambiente FC26/Live Editor adequado. Sem esse ambiente, concluir apenas o que foi efetivamente validado e manter AT-003 e a liberação P0 correspondente pendentes. O plano não autoriza automações mais agressivas antecipadamente.

Relatórios históricos completos só devem ser liberados depois de avaliação real da qualidade e isolamento. Aceites são específicos ao cenário, modelo, versão e amostra registrados.
