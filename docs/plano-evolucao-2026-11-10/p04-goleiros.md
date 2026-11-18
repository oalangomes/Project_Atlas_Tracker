# P04 — Goleiros (AT-024; H11–H13)

Implementação em `codex/p04-goleiros`, sobre P03. O contrato `goalkeeperEvidence` está na resposta da partida detalhada; `goalkeeperSeason` e a evidência por fixture aparecem no perfil de goleiro. A Comissão recebe o mesmo estado de atribuição e não associa o xG do adversário ao atleta quando há mais de um goleiro elegível.

## Fonte e fórmulas

| Indicador | Cálculo e amostra | Quando fica indisponível |
| --- | --- | --- |
| Defesas / 90 | Defesas da linha individual FC26 × 90 / minutos positivos | Sem defesas ou minutos individuais |
| Taxa de defesas contextual | Defesas individuais / chutes no alvo da **equipe adversária** × 100. Na temporada, soma os numeradores e denominadores dos fixtures conciliados. | Mais de um goleiro, minutos incertos, campo ausente, chutes no alvo zero, diferença entre defesas individuais e coletivas, gols sofridos individuais e coletivos, ou defesas + gols sofridos ≠ chutes no alvo adversários |
| Gols sofridos / 90 | Gols sofridos individuais × 90 / minutos positivos | Gols sofridos individuais ou coletivos ausentes/divergentes; mais de um goleiro |
| xGA − GA | xG total convencional da equipe adversária − gols sofridos do goleiro | xG total ausente, gols sofridos ausentes/divergentes ou mais de um goleiro |
| xGA − GA / 90 | Soma de xGA − GA × 90 / soma dos minutos nos fixtures elegíveis | Sem fixture elegível |

O xG total vem de NPK-xG mais `0,7 × tentativas de pênalti` quando o contexto de pênaltis está disponível. xGA − GA é um **contexto de qualidade das chances**, não post-shot xG nem medida causal de mérito individual. `shots_against` do goleiro e `shots_on_target` da equipe adversária são preservados como fatos diferentes. A coluna cumulativa antiga agora se chama **Recorded save %** e usa `saves / (saves + goals_conceded)` das estatísticas oficiais; ela não é confundida com a nova taxa contextual.

O papel de goleiro usa posição observada de fonte confiável quando presente; caso contrário, posição cadastrada, marcada como tal. Apenas um goleiro com minutos positivos e sem outro com minutos desconhecidos recebe contexto coletivo. Quando dois goleiros aparecem, as linhas individuais permanecem disponíveis, mas os indicadores contextuais e a associação individual de xG ficam indisponíveis. O perfil mostra a amostra própria de cada indicador, sem transformar ausência em zero.

## Verificação

- 168 testes Python passaram, inclusive casos sintéticos de um, dois, zero e minutos desconhecidos, divergência de denominador, xG total ausente, posição observada e amostras distintas.
- `npm run build` do frontend passou.
- Consulta somente leitura ao banco ativo: o export 34 do fixture 1545 concilia as taxas; no export 27 do fixture 218216, um lado registra 5 defesas e 2 gols sofridos diante de 8 chutes no alvo adversários. A taxa fica indisponível com motivo `shots_on_target_mismatch`; os três valores originais permanecem expostos. Esta inspeção não é benchmark nem validação da captura no jogo.

Limite pendente: a captura FC26 não fornece post-shot xG nem cronologia confiável da troca de goleiros. Uma divisão temporal de xGA entre dois goleiros depende de nova fonte e validação futura.

A apresentação numérica reutiliza `num()` da interface, que aplica `Intl.NumberFormat(atlasLanguage())`; em pt-BR, os indicadores exibem vírgula decimal. A formatação não altera as fórmulas deste pacote.
