# P07 — Contexto tático manual

Implementação de AT-008–011 e H18/H35 sobre Match Report e Comissão. O Diário do Treinador é uma fonte manual separada das tabelas importadas do FC26.

## Registro e revisão

- Uma carreira e um fixture do clube identificam o registro. API: `GET /api/careers/{career}/matches/{fixture}/diary?snapshotId={snapshot}`, `POST .../diary/save` e `POST .../diary/invalidate`.
- Nota, autor, data da observação, escalações própria e adversária, posições observadas, funções e minutos de entrada/saída são opcionais por campo. O autor e ao menos uma observação são obrigatórios. Titularidade desconhecida e minuto desconhecido permanecem `null`.
- Cada edição exige a revisão anterior e cria uma revisão imutável; invalidar preserva o histórico. A API distingue a revisão atual da revisão que já existia quando o snapshot foi importado. Anotações posteriores são rotuladas retrospectivas na tela e no catálogo da Comissão.
- `SCHEMA_VERSION` passa de 1 a 2. A inicialização produz um backup SQLite `atlas_manual_*_pre_schema_2.sqlite3` antes de criar as tabelas. Ele contém tabelas manuais, carreira, snapshot e fixture para recuperação de contexto editável, com contagens verificadas; não é cópia integral dos exports imutáveis. O banco ativo verificado tem cerca de 14 GB. Código anterior ignora as tabelas adicionais e não remove as revisões; ao voltar a esta versão, a inicialização pode gerar outro backup porque o código anterior regrava a versão 1.

## Formação e proveniência

- Formação própria e rival são campos separados. Uma formação explícita do treinador é `confirmed_manual`; hipótese explícita com evidência é `estimated_manual`; onze titulares com posições **observadas manualmente** permitem `estimated_observed_xi`. Sem isso, a resposta é `indeterminate`.
- Uma linha defensiva de cinco isolada fica registrada como linha de cinco, sem completar automaticamente o sistema rival. Posições naturais do elenco e formação própria não são usadas para inferir o adversário.
- Posição manual divergente da posição extraída aparece com ambas as fontes no Match Report. Nenhuma linha importada é alterada.
- A Comissão recebe `coach_diary` com autor, revisão, horário, formação classificada e marca retrospectiva. O hash de evidência muda somente nos relatórios cujo fixture contém esse diário; a versão global dos relatórios de IA permanece inalterada. Não há regeneração histórica automática.

## Validação e limites

- Testes cobrem escalação parcial, XI observado, linha de cinco sem formação, hipótese e confirmação, revisões, conflito de edição, isolamento por carreira/snapshot, invalidação, backup pré-migração, rota HTTP e mudança de hash do relatório.
- A estimativa `estimated_observed_xi` descreve a distribuição dos onze atletas observados; não mede fase tática ou mudanças durante o jogo. Sem cronologia confiável, minutos de substituição não são inferidos.
- A aplicação ativa e o banco do workspace não são migrados por esta branch até que ela seja executada. Nenhuma geração de IA é feita pela implementação ou pelos testes.
