# Entrega 4 — Desenvolvimento e funções

[Índice](README.md) · [Governança](governanca-e-validacao.md) · Anterior: [Entrega 3](entrega-3-rotacao-profundidade.md) · Próxima: [Entrega 5](entrega-5-comissao-relatorios.md).

**Prioridade:** P2 para AT-016–AT-018. AT-014 permanece P1 e é compartilhado com a Entrega 3. **Estado:** relatório do P09 implementado. P10 (AT-019) cancelado e removido. **Dependências:** contratos da Entrega 1. Os PRs originais 8/9 são históricos. O escopo ativo está em [P06 e P09](plano-execucao-integracao-hub.md#prs-pequenos-propostos).

## Revisão Hub → Atlas

AT-016/017 reutilizam `atlas/positions.py`, Comissão e consultas históricas para H08/H10/H19/H22/H26/H29–H31. Comparar função **observada** com fonte e amostra; nota não deve ser repartida entre posições sem minutos por papel. A forma usa últimas cinco atuações na ordem esportiva. Índice posicional Sheffield requer calibração e não substitui adequação Atlas.

AT-018 usa os registros cadastrais da base por snapshot (GER, POT, posição e vínculo) no relatório expansível de cada jovem. Não há fonte disponível para atuações ou minutos de partidas 5x5/11x11 da base. H23 fica fora do P09 e H24/H25 são adaptados sem índice de prontidão ou cálculo de carga de jogos. A passagem ao elenco profissional e a posição em campo só são descritas quando registradas em fontes profissionais confiáveis. A troca de posição é uma hipótese condicionada à evidência disponível.

## Objetivo e condição de conclusão

Apoiar escolha de jogadores e planejamento do elenco sem converter números brutos em hierarquia automática. Identificar opções internas, diferenças e riscos esportivos, sem tratar contratação como resposta padrão.

| Pacote | Implementação | Critério de aceite original |
| --- | --- | --- |
| AT-016 | Comparador contextual de jogadores | Mesmo papel, período e exposição comparáveis, com ressalvas |
| AT-017 | Evolução detalhada de atributos | Deltas auditáveis entre snapshots, sem atribuir causa inexistente |
| AT-018 | Relatório de desenvolvimento da base | GER/POT histórico, posição cadastrada e mudança de vínculo observada; posição/minutos profissionais apenas com fonte |

AT-014 conserva o critério da Entrega 3: cobertura suficiente, adaptação e lacuna funcional. Arquivos/serviços candidatos: `positions.py`, consultas existentes de jogadores/histórico, Player Profile, Squad, Base e gestão manual. Confirmar caminhos e contratos antes de implementar.

## Corte 4A — Profundidade funcional (AT-014, PR 8)

1. Reutilizar grupos de posições, profundidade desejada e adequação de `positions.py`; inventariar quais papéis já são expressos.
2. Exibir cobertura suficiente, adaptação e lacuna por função. Justificar adequação com atributos/posições disponíveis e separar função observada da cadastrada.
3. Tratar indisponibilidade, empréstimo e vínculo conforme dados realmente disponíveis, distinguindo projeção do treinador de situação extraída.
4. Considerar que um atleta pode cobrir múltiplas funções, mas não ocupa várias vagas simultâneas na mesma composição. Exibir esse limite em cenários de cobertura.
5. Compartilhar o contrato de profundidade funcional entre Squad e rotação.

**Aceite verificável:** função com cobertura, função apenas adaptável e função sem alternativa são identificadas e explicadas; um único jogador multifuncional não mascara duas lacunas simultâneas.

## Corte 4B — Simulação de sucessão (AT-019, cancelado)

O P10 foi removido. A tela, a rota de consulta e os testes do simulador foram retirados.

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

## Corte 4E — Relatório individual da base (AT-018, PR 9)

1. Exibir por jovem um relatório expansível de posição, sem mudar desenvolvimento no jogo. Uma alternativa de posição é hipótese revisável, não uma conclusão automática.
2. Mostrar GER/POT, posição e presença na base por snapshot, com data, fonte e lacunas. Não atribuir variação a treino ou atuação sem evidência.
3. Mostrar a entrada no elenco profissional e os minutos profissionais somente quando observados nas fontes existentes, com corte por carreira/snapshot. Associar empréstimos registrados sem atribuir evolução ao empréstimo.
4. Exigir que a IA exponha as lacunas de 5x5/11x11 e minutos da base; sem score de prontidão, etiqueta automática de pré-profissional ou mudança automática de posição.
5. Integrar FC26 Youth existente, sem novo menu principal nem truncar o universo de jovens. Registros manuais históricos, se já existirem, são preservados mas não conduzem esse fluxo.

**Aceite verificável:** GER/POT e vínculo podem ser reconstituídos pelos snapshots; ausência de partidas/minutos da base aparece como indisponível; entrada e posição profissional não são presumidas; recomendação de posição é condicional e não muda dados; histórico de empréstimos mantém origem.

## Perguntas esportivas de validação

As perguntas abaixo são cenários de aceitação, não conclusões do plano:

- Oseni preserva produtividade em confrontos mais difíceis? Examinar papel, amostra e contexto pré-jogo.
- Providence evolui em produção, atributos e constância? Tratar os três eixos separadamente e qualificar o que os dados sustentam.
- Watts ou Benarous substituem características importantes de Paterson? Comparar funções e características específicas, sem reduzir a resposta ao GER.

## Validação integrada

Cobrir adequação única compartilhada, jogador multifuncional em vagas simultâneas, papéis desconhecidos, exposição incomparável, snapshots futuros, atributo faltante e troca de carreira.

Validar o contrato do relatório, API, lista FC26 Youth, build TypeScript e JS gerado. Conferir casos reais contra dados do workspace e registrar as lacunas de evidência.

## Reversão e saída

Preservar planos e revisões em migrações, produzir backup verificável e documentar restauração. Preservar histórico e atributos do jogador ao reverter a comparação.

- [ ] AT-014 compartilhado com rotação, sem dupla contagem.
- [ ] AT-016 compara recortes defensáveis e explicita limitações.
- [ ] AT-017 mantém deltas auditáveis e sem causalidade inventada.
- [ ] AT-018 persiste metas, histórico e revisões com proveniência.
- [ ] PRs 8 e 9 possuem validação e checklist transversal.
