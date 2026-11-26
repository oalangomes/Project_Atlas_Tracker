# P11 — Comissão e semestre

Implementação do primeiro corte verificável de AT-021–023 e H33–H34. A entrega acrescenta uma visão semestral determinística aos relatórios esportivos e reutiliza os controles já existentes da Comissão Técnica; ela não faz chamadas de IA automaticamente.

## Semestre auditável

Na aba **Semester** de *Season report*, o treinador escolhe janeiro–junho ou julho–dezembro. A consulta `GET /api/careers/{career_id}/sporting-reports/semester` parte do snapshot mais recente da temporada selecionada e agrega apenas os meses já presentes no relatório mensal/sazonal.

O resultado informa, de forma explícita:

- meses incluídos e excluídos, além de mês parcial;
- partidas com resultado e partidas com MatchStats detalhado;
- vitórias, empates, derrotas, gols e pontos somente quando os meses necessários são completos;
- minutos, atuações avaliadas, nota média ponderada por atuações e cobertura detalhada por atleta.

Não há inferência de causa tática, evolução de atleta ou disponibilidade. Nota ausente não vira zero. A leitura é somente de dados: não altera fixtures, snapshots, contratos, observações ou save.

## Comissão, revisão e privacidade

O semestre convive com os contratos já usados pela Comissão: fatos por evidência, cache por carreira/snapshot/escopo, validação posterior dos claims e sinal `review_required` quando uma afirmação é filtrada. O relatório exibido preserva cobertura, afirmações aceitas/rejeitadas e o aviso de revisão; uma resposta de modelo não se aprova apenas por declarar conformidade.

Os controles cloud permanecem opt-in: o envio só ocorre com provedor, chave protegida e consentimento explícito; revogar o consentimento bloqueia novos envios cloud. Falhas ou ausência do modelo não indisponibilizam as métricas determinísticas nem a visão semestral.

## Limites de aceite

Esta entrega não afirma benchmark entre modelos, custo efetivamente observado nem avaliação humana executada, pois nenhuma chamada externa foi disparada durante a implementação. Geração histórica em lote continua sujeita ao gate já existente e não é iniciada pela aba semestral.

## Verificação

```powershell
py -3 -m unittest tests.test_semester_report -v
py -3 -m unittest tests.test_semester_report_api -v
py -3 -m unittest discover -s tests -q
Set-Location frontend; npm run build
```

Os testes verificam o corte Jan–Jun/Jul–Dez, meses excluídos, nota ausente, mês parcial, parâmetros inválidos e que a rota abre o banco em modo somente leitura.
