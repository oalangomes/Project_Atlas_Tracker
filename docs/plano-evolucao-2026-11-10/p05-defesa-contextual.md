# P05 — Defesa contextual (AT-025; H14–H17)

O serviço `atlas/defense_context.py` consulta exports MatchStats completos e vinculados, resolve o clube gerenciado no snapshot de origem e usa somente posições observadas com proveniência confiável, disponíveis até o corte temporal selecionado. A resposta `defenseContext` é consumida por **Análise → Match data**, pela **Comissão Técnica** e pela aba **Squad** do relatório da temporada.

## Contratos de cálculo

| Capacidade | Cálculo | Fonte e exclusão |
| --- | --- | --- |
| H14 · ações diretas | Soma de desarmes, interceptações, bloqueios e cortes por atleta. `/90` = soma com minutos correspondentes × 90 / soma desses minutos. | Linhas individuais FC26, com amostra por campo. Campo ausente não vira zero. Se uma linha com ação não tiver minutos, a soma bruta permanece e o `/90` do campo fica indisponível. |
| H15 · exposição individual estimada | Para cada fixture, valor coletivo adversário × minutos observados do defensor / 90; a soma é dividida por Σ(minutos observados / 90). Clean sheet estimado = minutos do atleta em fixtures com zero gol sofrido / minutos em fixtures com gols sofridos conhecidos. | Só com posição defensiva observada (`CB`/laterais/volante) e minutos positivos. xGA usa xG total adversário quando o contexto de pênaltis permite derivá-lo; chutes e clean sheet têm amostras próprias. |
| H16 · setores | Mesma média contextual ponderada, agregada por minutos de atletas na função observada. | Zaga, laterais e volante separados; o painel derivado requer **≥270 minutos com xGA e ≥3 fixtures distintos**. Cada indicador setorial exige também sua própria cobertura de 270 minutos e três fixtures. A resposta preserva a amostra de setores não qualificados, sem publicar seus indicadores. |
| H17 · pares | Conta fixtures em que ambos tiveram posição defensiva observada e minutos positivos. `Σ min(min A, min B)` é somente **limite superior** para minutos de possível sobreposição. | O campo `simultaneousPresenceConfirmed` permanece falso. O limiar histórico de 180 min aparece apenas como referência para o limite superior; não qualifica “minutos juntos”. |

Essas médias descrevem o contexto coletivo dos jogos em que cada defensor participou. Não identificam chutes, gols ou xG ocorridos enquanto ele estava em campo, nem atribuem responsabilidade individual. O xGA convencional não é post-shot xG. A soma de exposições de vários defensores pode exceder o total da equipe; ela não deve ser interpretada como total aditivo.

O serviço expõe contagens de fixtures, linhas sem posição confiável, linhas sem minutos e amostras próprias de xGA, chutes e clean sheet. Exports duplicados do mesmo fixture são reduzidos à versão vinculada mais recente dentro do corte temporal. Linhas sem equipe gerenciada e adversária são excluídas com contagem explícita.

## Verificação

- `py -3 -m unittest discover -s tests -q`: 167 testes passaram, incluindo sete novos casos de fonte direta, xGA ausente, minutos e posição incertos, qualificação setorial e por campo, dupla substituída e snapshot histórico.
- `npm run build` no frontend: passou.
- Consulta **somente leitura** ao banco ativo: 33 fixtures completos e vinculados no recorte da temporada atual, com 245 linhas defensivas de posição confiável e minutos positivos; os três setores atingem o corte. Esses números descrevem apenas o workspace consultado, não são benchmark do serviço nem homologação da captura.

Pendente de fonte externa: cronologia confiável de substituições para medir sobreposição real de pares e atribuir eventos/xGA ao intervalo em campo (BL-08/P12).
