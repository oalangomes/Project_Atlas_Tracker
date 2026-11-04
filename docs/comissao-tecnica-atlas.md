# Comissão Técnica e inteligência de partidas no Atlas

A Comissão Técnica é uma camada do Project Atlas Tracker existente. Ela usa a carreira e o snapshot selecionados, preserva os cálculos estatísticos canônicos e não escreve no save EA FC. MatchStats, histórico, posição cadastrada e posição observada mantêm a proveniência própria.

## Cobertura entre módulos do Atlas

| Módulo | Dados e cálculos canônicos | Apresentação preservada | Evolução desta entrega | Lacuna atual |
|---|---|---|---|---|
| Match Center | Fixtures, placar, MatchStats, eventos exportados, rating/minutos | Cabeçalho, comparação estatística, eventos e tabela de atuações diretamente visíveis | Diagnóstico contextual aparece junto das estatísticas; relatório salvo acessível na partida | Eventos não têm minuto confiável; não há coordenadas espaciais |
| Estatísticas detalhadas de partidas | `atlas/match_stats.py`: xG de equipe derivado quando penalidades permitem, NPK-xG, xA, chutes, passe, duelos, defesa, goleiro e taxas | Indicadores de equipe e métricas individuais completas permanecem acessíveis | Leituras de relatório selecionam a exportação da carreira e do snapshot, com corte temporal | Cobertura incompleta; campos ausentes continuam N/D |
| Analysis / Match Intelligence | Agregados, divisões casa/fora/competição, séries por jogo e médias móveis já existentes | Gráficos, líderes e tabela jogo a jogo permanecem como base | Comissão recebe referências pré-partida e pode contextualizar a partida contra temporada e últimas cinco exportações anteriores | Não há cronologia de xG por evento nem métricas táticas não exportadas |
| Player Analysis | Radar, atributos, perfis de função, percentis, OVR/POT, histórico individual e estatísticas detalhadas | Análise determinística e comparações de clube/liga são preservadas | Relatório individual acrescenta peer group do elenco, amostra, minutos, forma e contribuição MatchStats | Comparações por posição observada ainda dependem de captura com proveniência confiável |
| Comparações de elenco, posição e grupo | `server_query_entities.py` e `atlas/commission.py` | Comparações cadastrais continuam nas telas existentes; tabelas detalhadas não viram o painel principal | Relatório contextual pode mencionar concorrentes de grupo nominal, com minutos e amostra | Grupo posicional nominal não comprova função tática equivalente |
| Evolução individual | Rating/minutos por atuação, MatchStats ligados e histórico OVR/POT | Abas de partidas e desenvolvimento mantidas | O relatório de partida individual compara a atuação com até cinco aparições MatchStats anteriores | Sem granularidade por período em campo ou função |
| Technical Commission | Política de amostra e notas ponderadas da Comissão; tendências coletivas existentes | Painel coletivo e ferramentas de elenco permanecem integrados ao Atlas | Diagnóstico determinístico separado de interpretação Ollama e comparação histórica | Qualidade esportiva ainda requer avaliação humana contra partidas reais |
| Relatórios Ollama | Contexto serializado com fatos e IDs, MatchStats canônico, jogador e referências históricas anteriores | A análise fica na partida, perfil do jogador ou Comissão Técnica | Relatório JSON tipado em fato/inferência/hipótese, fontes citadas, limitações, cache por carreira/snapshot/versão/fatos; sem verificador baseado em segunda chamada ao mesmo modelo | Ollama está opcional e offline no ambiente desta execução; não foi possível medir saída real do modelo |

## Fontes e limites das afirmações

- **Extraído:** valores presentes em snapshot, fixture, exportação MatchStats completa ligada, histórico de rating/minutos ou atributo cadastrado.
- **Derivado:** taxas e médias produzidas pelos cálculos de `atlas/match_stats.py`, contexto pré-partida agregado e métricas da Comissão Técnica. O contexto de partida exclui datas iguais/posteriores ao jogo analisado e exports posteriores ao snapshot selecionado.
- **Indisponível:** posse percentual, pressão coletiva, altura de linha, evento com minuto, coordenadas, disponibilidade física, hierarquia formal e funções táticas quando não há fonte específica. Nenhum valor ausente é tratado como zero.
- A posição observada é aceita somente quando `actual_position_source` é `career_playermatchratinghistory_position`. Ela não confirma titularidade, função ou movimentação.
- Dados profissionais e futebol jovem 5x5 permanecem separados. O save EA FC segue somente leitura e nenhuma mudança de exportador Lua foi necessária.

## Política de amostra e comparação temporal

- Os cortes do Hub continuam: utilizável com pelo menos 300 minutos e 3 atuações válidas; confiável com 450 minutos e 5 atuações. São rótulos de amostra, não regras universais para relevância esportiva.
- Forma individual mantém até cinco atuações válidas, ponderadas por minutos.
- Referência coletiva pré-partida contém médias da temporada até a data e médias das últimas cinco partidas detalhadas elegíveis, além de divisão casa/fora quando há amostra. Cada métrica leva a própria contagem de jogos não ausentes.
- Referência individual usa até cinco atuações MatchStats anteriores elegíveis; posição observada só entra com proveniência confiável. Não se atribuem ações de uma partida a posições por intervalo.
- Contextos são filtrados por `career_id`, time gerenciado e `import_sequence` selecionado. Plymouth Argyle e Sheffield United não são cruzados.

## Relatórios estruturados

Cada resumo e conclusão tem `kind`: `fact`, `inference` ou `hypothesis`. Hipóteses exigem campo `limitations`. Todas citam IDs de fatos presentes no contexto. A validação local verifica JSON, IDs de fontes citadas, números contidos nos valores dessas fontes, limites de fonte e contradições objetivas conhecidas; ela não mede qualidade esportiva nem usa o mesmo LLM como único avaliador. Os itens válidos não são descartados por palavras genéricas como “domínio” ou “defesa sólida”; interpretações continuam rotuladas e devem estar apoiadas nas evidências citadas.

A interface não mostra score de confiança ou nota de qualidade inventada a partir da quantidade de evidências aceitas. Cobertura, itens filtrados e ausência de avaliação independente ficam em detalhes. O cache usa versão de contrato (atual v5), carreira, snapshot, modo, modelo e hash das fontes.

O Ollama é opcional. Sem serviço local, as estatísticas, gráficos e comparações do Atlas continuam disponíveis. Relatórios existentes podem ser lidos do cache; uma chamada falha não grava uma análise nova.

## Avaliação reproduzível e alcance da evidência

`tests/fixtures/commission_intelligence_cases.json` contém doze casos sintéticos de contrato, incluindo contradição entre placar e desempenho, conversão, defesa, comparação individual, posições, amostra pequena, divergência de fonte e hipótese não comprovada. Esses cenários testam classificação e validação de evidência, não são resultados de modelo nem substituem avaliação de conteúdo gerado ao vivo. Como Ollama estava offline durante esta execução, não é correto declarar ganho medido de qualidade do modelo ou apresentar exemplos de saída real antes/depois.
