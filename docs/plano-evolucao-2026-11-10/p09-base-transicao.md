# P09 — Relatório da base e trajetória cadastral

Implementação de AT-018, H24/H25 adaptados e H28. A entrega oferece um relatório expansível por jovem na lista da base; ela não calcula desempenho, carga ou prontidão a partir de partidas da base.

## Dados e limites

- O FC26 Youth continua sendo a fonte dos fatos importados: jogador, posição, GER, POT e presença na base no snapshot.
- Não há atuações ou minutos 5x5/11x11 da base no Atlas. O score H23 e o índice composto de prontidão do Hub não são portados.
- A entrada no elenco profissional, as estatísticas acumuladas e a posição efetivamente observada só entram no relatório quando há registro profissional confiável no snapshot. GER/POT não provam promoção nem tempo de jogo.
- A posição cadastrada não é tratada como posição efetivamente jogada. Sem evidência profissional confiável, o relatório declara que a posição em campo não pode ser confirmada.

## Comportamento

Em **FC26 Youth**, cada linha tem um **relatório de desenvolvimento e posição** expansível. Ao gerá-lo, a Comissão recebe a posição cadastrada, GER, POT e o histórico desses valores por snapshot; quando existirem, também recebe presença no elenco profissional, estatísticas profissionais acumuladas e posições de partida com proveniência confiável.

O modelo deve responder se a posição cadastrada parece defensável e, se sugerir alternativa, precisa fazê-lo como hipótese condicional vinculada às evidências. Ele não confirma troca de posição, não calcula prontidão e não altera o save. O relatório explicita que não há dados de partidas 5x5/11x11, minutos ou estatísticas da base.

Os planos manuais introduzidos no primeiro corte foram retirados da interface por não serem o fluxo aprovado. As tabelas e eventuais registros já gravados permanecem preservados para não apagar histórico, mas não direcionam a lista, o perfil ou o relatório.

## Persistência e reversão

O relatório é cacheado pela Comissão com o snapshot, o jogador, a versão do contrato de evidências e o idioma. Dados de snapshot continuam imutáveis. O esquema 5 e `manual_youth_development_plans`/`manual_youth_development_plan_revisions` continuam existentes somente para preservar registros já salvos.

Reverter o código não apaga os registros manuais nem os relatórios em cache. Uma versão anterior ignora as novas tabelas; para retornar a uma versão que não conhece o esquema, restaure o backup de contexto produzido antes da migração quando isso for necessário.

## Verificação

```powershell
py -3 -m unittest tests.test_youth_development_plans -v
py -3 -m unittest tests.test_youth_development_report -v
py -3 -m py_compile atlas/db.py atlas/manual_data.py atlas/server_query_management.py atlas/server_query_entities.py atlas/server_http.py
Set-Location frontend; npm run build
```

Os testes cobrem a preservação do histórico manual e o contrato factual do relatório: trajetória cadastral, limite explícito dos dados 5x5/11x11 e rejeição de jogador ausente do export juvenil.
