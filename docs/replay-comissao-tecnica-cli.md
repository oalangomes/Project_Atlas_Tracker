# Replay retroativo da Comissão Técnica (Ollama local)

O Atlas já gera os relatórios em ordem cronológica e persiste cada tarefa no SQLite.
Este lançador apenas chama a API do Atlas: não modifica o save do FC26.

## Preparação

1. Usar a branch/release contendo P3 e o lançador P4.
2. Iniciar o Atlas Tracker normalmente no Windows (porta padrão 8765).
3. Manter Ollama ativo com o modelo selecionado pelo Atlas (ATLAS_OLLAMA_MODEL; padrão qwen3.5:9b).
4. Confirmar que o Atlas aberto corresponde ao workspace/carreira pretendido.

## Duplo clique

Na raiz do projeto, abrir **executar_reports_retroativos.bat**.
O terminal permite escolher carreira e temporada, exige a confirmação GERAR,
inicia o replay sem copiar o banco e mostra o andamento.

## Terminal (raiz do repositório)

Listar carreiras e temporadas:
    py -3 -m scripts.replay_commission_reports --list

Verificar a seleção SEM gerar:
    py -3 -m scripts.replay_commission_reports --career-id 1 --season-index 0 --dry-run

Iniciar, com confirmação:
    py -3 -m scripts.replay_commission_reports --career-id 1 --season-index 0

Executar sem confirmação interativa (exige IDs explícitos):
    py -3 -m scripts.replay_commission_reports --career-id 1 --season-index 0 --yes

Iniciar sem permanecer acompanhando:
    py -3 -m scripts.replay_commission_reports --career-id 1 --season-index 0 --yes --no-watch

Acompanhar um job já iniciado SEM criar outro:
    py -3 -m scripts.replay_commission_reports --career-id 1 --job-id SEU_JOB_ID

Iniciar e auditar os relatórios persistidos da mesma carreira ao final:
    py -3 -m scripts.replay_commission_reports --career-id 1 --season-index 0 --yes --audit-db "C:\CAMINHO\atlas_tracker.sqlite3" --output replay-result.json

**Atenção:** season_index é o índice **exato do banco** e pode ser 0.
Não troque por número do menu, ano da temporada ou índice da carreira.
O SQLite informado em --audit-db precisa ser o do mesmo workspace da carreira.
O script não adivinha o caminho do banco porque o Atlas pode ter múltiplos workspaces.

## Status

queued/running: trabalho ainda processando no Atlas.
complete: tarefas concluídas sem erros registrados.
complete_with_warnings: terminou com falhas ou dados ausentes.
paused_offline: Ollama indisponível; replay retomável.
paused/failed: investigar e retomar.

Para retomar após uma pausa, restabeleça Ollama e inicie novamente a MESMA
carreira e temporada; o Atlas identifica o job retomável. Não dispare outra
chamada de início para um job que já esteja executando. Para simplesmente
reconectar o terminal a ele, prefira --job-id.

Ctrl+C interrompe o acompanhamento, NÃO o processamento no Atlas.
O ID para reconexão é impresso logo após iniciar o replay.

O resumo JSON, quando solicitado, inclui progresso, gerados, reutilizados,
relatórios que exigem revisão e relatório opcional da auditoria.

A partir de P3.1, REPORT_VERSION=33 evita reaproveitamento de contexto
incompatível. Auditoria estrutural não comprova qualidade futebolística;
revise relatórios reais de partidas e jogadores após o replay.
