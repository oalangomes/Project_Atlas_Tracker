# Governança, validação e execução do plano

[Voltar ao índice](README.md).

Base documental: análise estática de 10/11/2026, commit `8f063cf`. Estado inicial de todos os pacotes: **planejado**. Este documento detalha a política recebida; não registra testes executados nem autoriza publicação, merge, homologação do jogo ou execução de provedores externos por si só.

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

Numeração proposta, sem correspondência automática com PRs existentes. Complexidade expressa dependências e risco; não é estimativa de prazo.

| Ordem | PR proposto | Pacotes principais | Dependência | Complexidade |
| --- | --- | --- | --- | --- |
| 1 | Segurança de credenciais e chamadas cloud | AT-001; parte de AT-004 | Nenhuma | Média |
| 2 | Corte temporal e proveniência histórica | AT-002; parte de AT-004 | Nenhuma | Baixa–média |
| 3 | Homologação e correções do AutoCapture | AT-003; testes pertinentes de AT-004 | Ambiente FC26/Live Editor | Alta |
| 4 | Qualidade de dados e reconciliação de métricas | AT-005–AT-007; consolidação de AT-004 | PR 2 | Média |
| 5 | Diário do Treinador e observações estruturadas | AT-008, AT-009 e integração inicial de AT-011 | PR 2 | Média |
| 6 | Formação adversária estimada/confirmada | AT-010 e conclusão de AT-011 | PR 5 | Média–alta |
| 7 | Análise contextual de rotação | AT-012, AT-013, AT-015; consumo de AT-014 existente | PRs 4 e 5 | Alta |
| 8 | Profundidade funcional e sucessão | AT-014 e AT-019 | PR 4 | Média |
| 9 | Comparador individual e desenvolvimento | AT-016–AT-018 | PRs 4 e 8 | Média–alta |
| 10 | Benchmark de IA e relatórios consolidados | AT-020–AT-023 | PRs 1, 4 e 6–9 | Alta |

PRs 1, 2 e parte dos testes do PR 4 podem evoluir independentemente, sem implicar delegação automática a agentes. Recursos analíticos esperam a definição dos seus contratos de dados. O gate P0 completo continua obrigatório para a liberação das entregas dependentes.

A numeração não exige execução estritamente serial: PR 8 pode preceder PR 7 se a comparação funcional depender de seu contrato novo. PR 7 pode inicialmente consumir a profundidade já existente em `positions.py`, sem duplicá-la. Os documentos de Entregas 3 e 4 compartilham AT-014 por referência; sua implementação pertence ao PR 8. AT-004 é transversal, com validação entregue junto aos comportamentos e consolidação no PR 4; não adiar segurança ou regressões de posições até esse PR.

As subdivisões descritas nos documentos de entrega podem virar PRs menores quando necessário. Preservar as dependências, atualizar a matriz e manter cada mudança revisável e reversível.

## Checklist obrigatório por PR

Estado inicial: **0/10 verificados para uma implementação deste plano**. Copiar para cada PR e marcar somente com evidência correspondente.

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
