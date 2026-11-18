# P06 — Forma, função e elenco

Implementação da P06 sobre os agregadores existentes do Atlas. O cache de métricas da Comissão passa à versão 5; a versão dos relatórios de IA não muda nesta entrega.

## Contratos entregues

- Últimas cinco atuações válidas em ordem de data, horário e identificador da partida quando vinculados. A nota usa minutos como peso. Se o horário não foi capturado, a ordem entre jogos no mesmo dia continua limitada ao identificador disponível.
- Posição cadastrada e função observada aparecem separadas. A função exige origem confiável no histórico da atuação; a nota por função atribui cada atuação inteira a uma posição e não estima minutos por fase.
- O rival é um jogador do elenco ativo com a mesma função observada dominante. Ambos precisam de ao menos 450 minutos e cinco jogos observados na função. A comparação expõe nota ponderada e amostra, sem índice composto nem decisão automática de vaga. Hierarquia ausente resulta em abstenção.
- O perfil do jogador mostra posição cadastrada e atuações com posição observada. A trajetória une aliases do mesmo clube por EA ID, conserva a contagem de observações e respeita o snapshot selecionado.
- A análise do elenco expõe a lista completa além dos 15 destaques, incluindo mais de 40 pessoas quando presentes. Produção (jogos/nota) e evolução (GER/POT entre snapshots) ficam em colunas distintas. Nomes alternativos por EA ID são preservados; registros manuais sem EA ID continuam separados.
- Estatísticas manuais e importadas da mesma competição/temporada/jogador não são somadas duas vezes quando o Object ID coincide ou o nome normalizado conservadoramente coincide. O contexto manual não consulta snapshot posterior ao recorte.

## Limites e próximos pacotes

- MatchStats detalhado continua parcial; ausência de export não equivale a zero. Sem posição observada confiável, rival e nota por função ficam N/D.
- Sem hierarquia formal ou minutos por fase, a comparação não recomenda titularidade. Planos individuais editáveis de desenvolvimento e sucessão seguem para P09/P10, como previsto no roadmap; P06 entrega o universo completo para revisão.
- A investigação separada do cache de relatórios de IA permanece pendente. Esta entrega não altera `REPORT_VERSION` nem executa geração de relatórios.

## Validação

- `python -m unittest discover -s tests -p 'test_*.py' -q`
- `npm run build` em `frontend`
- Consulta somente leitura ao snapshot ativo 83: 29 jogadores, 363 linhas de atuação, 527 linhas detalhadas; 4 jogadores com rival elegível na Comissão. A análise de elenco retornou 29 registros completos e 15 destaques. Estes números descrevem o estado local verificado, não são limite de implementação.
