# 🚀 Plano de Evolução: Integração de Modelos Cloud & Otimização de Performance

## 1. Objetivo
Expandir as capacidades de análise do Atlas integrando modelos de linguagem em nuvem (Cloud LLMs) para eliminar o impacto de performance na GPU durante o jogo e elevar a qualidade esportiva dos relatórios (reduzindo falsos positivos).

## 2. Arquitetura Técnica: Camada de Abstração
Substituir as chamadas diretas ao Ollama por um `LLMManager` que orquestra diferentes provedores.

### 2.1 Provedores Implementados
*   **Local (Ollama):** Mantido para uso offline.
*   **Google Gemini 1.5 Flash (Recomendado):** Foco em custo zero (Free Tier) e janela de contexto gigante para análise de temporadas.
*   **Groq (Llama 3.1):** Foco em ultra-velocidade e alta precisão (70B params).

### 2.2 Modos de Operação
1.  **Local:** 100% GPU local.
2.  **Cloud Only:** 0% impacto na GPU (Ideal durante partidas).
3.  **Hybrid:** Prioriza Cloud com fallback para Local.

## 3. Estratégia de Custo e Segurança
*   **Modelo Freemium:** Utilização de APIs com Free Tiers (Google AI Studio e Groq).
*   **Segurança:** Chaves de API armazenadas em `.env` ou variáveis de ambiente (nunca hardcoded).
*   **Controle de Gastos:** Implementação de limites de tokens por requisição e cache agressivo de snapshots para evitar chamadas redundantes.

## 4. Roadmap de Implementação

### Fase 1: Infraestrutura (Back-end)
- [ ] Criar interface `BaseLLMProvider` em `atlas/commission.py`.
- [ ] Implementar `OllamaProvider`, `GeminiProvider` e `GroqProvider`.
- [ ] Desenvolver `PromptAdapter` para garantir saídas estritamente em JSON para modelos Cloud.
- [ ] Integrar gerenciamento de chaves via `.env`.

### Fase 2: Interface e UX (Front-end)
- [ ] Adicionar seletor de "Motor de Análise" no menu de Configurações.
- [ ] Criar campo de validação de API Key.
- [ ] Adicionar indicador visual de qual provedor está ativo.

### Fase 3: Validação de Qualidade
- [ ] Executar testes de proveniência (v31) com Gemini 1.5 Flash.
- [ ] Comparar taxa de `review_required` vs Ollama Local.
- [ ] Liberar a funcionalidade de **Replay Cronológico** após validação da qualidade esportiva.
