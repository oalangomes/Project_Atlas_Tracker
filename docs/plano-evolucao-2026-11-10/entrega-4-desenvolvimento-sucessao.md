# Entrega 4 — Desenvolvimento, funções e sucessão

[Índice](README.md) · [Governança](governanca-e-validacao.md) · Anterior: [Entrega 3](entrega-3-rotacao-profundidade.md) · Próxima: [Entrega 5](entrega-5-comissao-relatorios.md).

**Prioridade:** P2 para AT-016–AT-019. AT-014 permanece P1 e é compartilhado com a Entrega 3. **Estado:** planejada. **Dependências:** Entregas 0 e 1. PR 8 depende de PR 4; PR 9 depende de PRs 4 e 8.

## Objetivo e condição de conclusão

Apoiar escolha de jogadores e planejamento do elenco sem converter números brutos em hierarquia automática. Identificar opções internas, diferenças e riscos esportivos, sem tratar contratação como resposta padrão.

| Pacote | Implementação | Critério de aceite original |
| --- | --- | --- |
| AT-016 | Comparador contextual de jogadores | Mesmo papel, período e exposição comparáveis, com ressalvas |
| AT-017 | Evolução detalhada de atributos | Deltas auditáveis entre snapshots, sem atribuir causa inexistente |
| AT-018 | Planos de desenvolvimento da base | Metas, minutos, evolução e histórico de empréstimos |
| AT-019 | Planejamento de sucessão | Simular saídas e mostrar cobertura interna antes de sugerir mercado |

AT-014 conserva o critério da Entrega 3: cobertura suficiente, adaptação e lacuna funcional. Arquivos/serviços candidatos: `positions.py`, consultas existentes de jogadores/histórico, Player Profile, Squad, Base e gestão manual. Confirmar caminhos e contratos antes de implementar.

## Corte 4A — Profundidade funcional (AT-014, PR 8)

1. Reutilizar grupos de posições, profundidade desejada e adequação de `positions.py`; inventariar quais papéis já são expressos.
2. Exibir cobertura suficiente, adaptação e lacuna por função. Justificar adequação com atributos/posições disponíveis e separar função observada da cadastrada.
3. Tratar indisponibilidade, empréstimo e vínculo conforme dados realmente disponíveis, distinguindo projeção do treinador de situação extraída.
4. Considerar que um atleta pode cobrir múltiplas funções, mas não ocupa várias vagas simultâneas na mesma composição. Exibir esse limite em cenários de cobertura.
5. Disponibilizar contrato único para Squad, sucessão e rotação; não criar uma avaliação alternativa para cada tela.

**Aceite verificável:** função com cobertura, função apenas adaptável e função sem alternativa são identificadas e explicadas; um único jogador multifuncional não mascara duas lacunas simultâneas.

## Corte 4B — Simulação de sucessão (AT-019, PR 8)

1. Permitir selecionar saídas hipotéticas e retornos/fim de empréstimo conforme vínculo conhecido, preservando o estado real.
2. Recalcular cobertura interna usando AT-014, incluindo alternativas da base quando a evidência permitir.
3. Apresentar diferenças entre cenário atual e simulado: funções perdidas, adaptações, dependências de um único atleta e opções internas.
4. Explicar incerteza de retorno, disponibilidade e papel; não assumir renovação ou desenvolvimento futuro.
5. Só depois das alternativas internas apontar necessidade esportiva eventualmente atendível no mercado, sem scouting automatizado ou contratação automática.

**Aceite verificável:** cenário com saída/retorno de dois zagueiros emprestados mostra impacto e cobertura restante sem alterar contratos, empréstimos ou save.

## Corte 4C — Comparador contextual (AT-016, PR 9)

1. Usar função efetivamente observada quando disponível; se houver apenas adequação cadastral, exibir limitação e não afirmar desempenho naquele papel.
2. Alinhar carreira, período, competição, posição/papel e exposição antes de comparar. Para taxas por minuto, exigir minutos confiáveis; caso contrário, limitar o tipo de comparação.
3. Aplicar contexto de dificuldade pré-jogo de AT-013/serviço existente, sem depender de nota gerada pela IA.
4. Apresentar amostra, disponibilidade e diferenças de adversário/mando; não transformar pequenas diferenças em ranking absoluto.
5. Integrar Player Profile e comparação existente. A Comissão pode interpretar as diferenças sem modificar os números.

**Aceite verificável:** jogadores com papel/exposição diferentes recebem ressalvas ou comparação bloqueada onde necessário; valores por período e fonte correspondem às evidências.

## Corte 4D — Atributos e desenvolvimento (AT-017, PR 9)

1. Reutilizar reconciliação de GER/POT e identidade da Entrega 1.
2. Calcular deltas por atributo entre snapshots identificados, com data, valor anterior, posterior e intervalo.
3. Distinguir evolução observada, correção de fonte e campo ausente. Não atribuir variação a treino, função ou empréstimo sem evidência causal.
4. Relacionar produção recente e atributos em eixos separados; melhora de gols não prova melhora de atributo ou constância.
5. Integrar histórico e Player Profile com o mesmo contrato, preservando snapshots originais.

**Aceite verificável:** cada delta pode ser reconstituído pelos dois snapshots; ausência em um deles não gera evolução artificial.

## Corte 4E — Planos individuais da base (AT-018, PR 9)

1. Persistir metas atribuídas ao treinador, horizonte, papel pretendido e revisões, sem mudar desenvolvimento no jogo.
2. Acompanhar minutos e evolução somente quando observados, indicando cobertura do histórico.
3. Associar empréstimos registrados e seus períodos sem atribuir automaticamente evolução ao empréstimo.
4. Mostrar requisitos para integração ao profissional e alternativas de função como recomendações revisáveis.
5. Integrar FC26 Youth e contexto do elenco, sem novo menu principal.

**Aceite verificável:** plano, meta e revisão persistem; dados ausentes não aparecem como meta descumprida automaticamente; histórico de empréstimos mantém origem.

## Perguntas esportivas de validação

As perguntas abaixo são cenários de aceitação, não conclusões do plano:

- Oseni preserva produtividade em confrontos mais difíceis? Examinar papel, amostra e contexto pré-jogo.
- Providence evolui em produção, atributos e constância? Tratar os três eixos separadamente e qualificar o que os dados sustentam.
- Watts ou Benarous substituem características importantes de Paterson? Comparar funções e características específicas, sem reduzir a resposta ao GER.
- Se dois zagueiros emprestados retornarem, a cobertura continua suficiente? Explicitar a perspectiva do vínculo: retorno ao clube de origem ou chegada ao elenco, conforme o cenário real confirmado.

## Validação integrada

Cobrir adequação única compartilhada, jogador multifuncional em vagas simultâneas, simulação sem mutação do estado real, papéis desconhecidos, exposição incomparável, snapshots futuros, atributo faltante e troca de carreira.

Validar persistência/revisão dos planos, API, telas Squad/Player Profile/Base, build TypeScript e JS gerado. Conferir casos reais contra dados do workspace e registrar quando uma pergunta não pode ser respondida.

## Reversão e saída

Simulações devem permanecer separadas dos dados reais. Preservar planos e revisões em migrações, produzir backup verificável e documentar restauração. Reverter comparação não deve eliminar histórico do jogador nem sobrescrever atributos.

- [ ] AT-014 compartilhado com rotação e sucessão, sem dupla contagem.
- [ ] AT-019 simula cobertura e prioriza opções internas.
- [ ] AT-016 compara recortes defensáveis e explicita limitações.
- [ ] AT-017 mantém deltas auditáveis e sem causalidade inventada.
- [ ] AT-018 persiste metas, histórico e revisões com proveniência.
- [ ] PRs 8 e 9 possuem validação e checklist transversal.
