# Guia de Telemetria, Logs, Detecção de Crash e Diagnóstico de Performance

Este documento serve como referência técnica e operacional para entender, consultar e analisar as métricas de execução, erros e crashes do crawler, permitindo diagnosticar problemas e criar melhorias contínuas.

---

## 1. Arquitetura do Sistema de Telemetria

O sistema de telemetria rastreia o ciclo de vida de cada execução do crawler (`run_fast.py`) e registra métricas em tempo real em duas camadas:
1. **Banco de Dados SQLite (`crawler.db`)**: Tabelas `execution_runs` e `error_logs`.
2. **Arquivos Estruturados (`logs/runs/`)**: Relatórios em Markdown (`run_*.md`) e JSON estruturado (`run_*.json`).

```
                              ┌────────────────────────┐
                              │  run_fast.py (super)   │
                              └───────────┬────────────┘
                                          │ Inicia / Checkpoint / Finaliza
                                          ▼
                              ┌────────────────────────┐
                              │  TelemetryManager      │
                              │  (telemetry.py)        │
                              └───────────┬────────────┘
                      ┌───────────────────┴───────────────────┐
                      ▼                                       ▼
       ┌──────────────────────────────┐        ┌──────────────────────────────┐
       │   Banco de Dados SQLite      │        │      logs/runs/              │
       │   - execution_runs           │        │   - run_<id>.json            │
       │   - error_logs               │        │   - run_<id>.md              │
       └──────────────────────────────┘        └──────────────────────────────┘
                      ▲                                       ▲
                      │                                       │
       ┌──────────────┴──────────────┐         ┌──────────────┴──────────────┐
       │  CLI: audit_runs.py         │         │  Painel Web: /runs          │
       │  (Análise & Diagnóstico)    │         │  (Visualização Gráfica)     │
       └─────────────────────────────┘         └─────────────────────────────┘
```

---

## 2. Estrutura dos Dados e Tabelas

### Tabela `execution_runs`
Armazena o histórico consolidado de cada run:
- `run_id`: Identificador único no formato `run_YYYYMMDD_HHMMSS_<hash>`.
- `mode`: Modo executado (`super`, `crawl`, `process`, `verify`).
- `journal_id`: ID do periódico específico ou `NULL` para todos.
- `status`: Estado final da execução:
  - `completed`: Execução finalizada normalmente.
  - `running`: Execução em andamento.
  - `interrupted`: Interrompida via `Ctrl+C`.
  - `crashed`: Detectada como abortada/crashada (ex: reinicialização do Hackintosh).
- `workers_count`: Número de workers paralelos por fase.
- `start_time` / `end_time` / `duration_seconds`: Janela de tempo total.
- `editions_processed`: Quantidade de edições concluídas.
- `articles_crawled` / `pdfs_downloaded` / `pdfs_failed`: Volume de artigos e PDFs processados.
- `emails_extracted` / `emails_valid` / `emails_invalid`: E-mails únicos capturados e validados.
- `speed_articles_per_min` / `speed_emails_per_min`: Throughput por minuto.
- `crash_recovered_tasks`: Número de tarefas órfãs destravadas pelo auto-recovery.
- `system_info`: JSON com versão do SO, Python e contagem de núcleos da CPU.
- `notes`: Observações e histórico de recuperação.

### Tabela `error_logs`
Armazena cada erro ou exceção com contexto completo:
- `run_id`: ID da execução vinculada.
- `phase`: Fase onde ocorreu (`crawling`, `extraction`, `verification`, `system`).
- `journal_id` / `article_id`: Entidades afetadas (quando aplicável).
- `error_type`: Categoria (ex: `HTTP404NotFound`, `DownloadFailed`, `PDFExtractionFailed`, `SMTPTimeout`, `SystemCrashOrForceKill`).
- `message`: Mensagem descritiva do erro.
- `details`: Detalhes técnicos, URLs ou stack traces.
- `created_at`: Data e hora do evento.

---

## 3. Detecção Automática de Crash e Auto-Recovery (Hackintosh)

### Como funciona:
1. Quando `run_fast.py` inicia no modo `super` ou `reset`, ele executa `TelemetryManager.start_run()`.
2. O sistema verifica se existem execuções anteriores com `status == 'running'`.
3. Se existir um run marcado como `running`, significa que a máquina desligou, travou ou o processo foi encerrado sem chamar os hooks de finalização.
4. O sistema automaticamente:
   - Atualiza o status do run anterior para `crashed`.
   - Cria um registro em `error_logs` do tipo `SystemCrashOrForceKill`.
   - Executa `db_manager.reset_stuck_tasks(timeout_minutes=0)`, destravando todas as edições, artigos e e-mails que estavam bloqueados por workers mortos.
   - Vincula o número de tarefas recuperadas ao novo run (`crash_recovered_tasks`).

---

## 4. Como Analisar os Logs e Criar Melhorias

### A. Via Linha de Comando (`audit_runs.py`)

A ferramenta `audit_runs.py` foi criada especificamente para que você (ou o assistente IA) inspecione o estado operacional rapidamente:

1. **Listar histórico recente de execuções e velocidades:**
   ```bash
   venv/bin/python audit_runs.py
   ```
   *Exemplo de saída:*
   ```text
   ===================================================================================================================
   RUN ID                     | INÍCIO (UTC)     | MODO    | PERIÓDICO | STATUS      | DURAÇÃO   | ARTS/M  | EMAILS/M | EMAILS    
   ===================================================================================================================
   run_20260824_141022_27cfcc | 24/08 14:10:22   | super   | 129       | COMPLETED   | 7m 12s    | 45.2    | 160.8    | 810/1241  
   ===================================================================================================================
   ```

2. **Inspecionar a última execução em detalhes:**
   ```bash
   venv/bin/python audit_runs.py --last
   ```

3. **Verificar os erros mais frequentes consolidados:**
   ```bash
   venv/bin/python audit_runs.py --errors
   ```

4. **Gerar diagnóstico de performance e sugestões:**
   ```bash
   venv/bin/python audit_runs.py --insights
   ```

---

### B. Via Painel Administrativo Web
Acesse:
- **Painel de Telemetria e Execuções**: `http://127.0.0.1:5000/runs`
  - Apresenta cards com taxa de sucesso, contagem de crashes e tarefas recuperadas.
  - Tabela com histórico de runs e velocidades (Artigos/min, E-mails/min).
  - Tabela com os erros mais recentes registrados.

---

### C. Queries SQL de Diagnóstico Profundo no `crawler.db`

Ao analisar o banco para planejar melhorias, use os seguintes padrões SQL:

#### 1. Identificar Periódicos com Maior Taxa de Erro:
```sql
SELECT 
    j.id, 
    j.name, 
    COUNT(e.id) as total_erros,
    e.error_type
FROM error_logs e
JOIN journals j ON e.journal_id = j.id
GROUP BY j.id, e.error_type
ORDER BY total_erros DESC
LIMIT 10;
```
*Ação recomendada*: Se um periódico apresentar muitos erros `DownloadFailed` ou `HTTP403Forbidden`, implementar headers customizados de User-Agent ou ajustar regras no scraper específico.

#### 2. Identificar Domínios de E-mail com Maior Rejeição SMTP ou Timeout:
```sql
SELECT 
    substr(email, instr(email, '@') + 1) as domain,
    COUNT(*) as total_invalid
FROM captured_emails
WHERE verification_status = 'INVALID'
GROUP BY domain
ORDER BY total_invalid DESC
LIMIT 15;
```
*Ação recomendada*: Adicionar domínios com servidores SMTP deliberadamente bloqueados ou lentos à lista de cache/ignorar para poupar tempo.

#### 3. Analisar Tempo Médio de Execução por Modo:
```sql
SELECT 
    mode, 
    status,
    COUNT(*) as total_runs, 
    AVG(duration_seconds) as media_duracao_segundos,
    AVG(CAST(speed_emails_per_min as FLOAT)) as media_emails_por_min
FROM execution_runs
GROUP BY mode, status;
```

---

## 5. Emulação de Agentes (User-Agents e Headers Anti-Bloqueio)

Para evitar bloqueios (`403 Forbidden` e proteções WAF), o crawler implementa o módulo [`user_agents.py`](file:///Volumes/SATA/projetos/crawler-de-revistas/user_agents.py) com perfis completos de cabeçalhos HTTP (`User-Agent`, `Accept`, `Accept-Language`, `Sec-Ch-Ua`, `Sec-Fetch-*`):

### Perfis Disponíveis:
- `--agent rotate` *(Padrão)*: Sorteia dinamicamente entre navegadores reais modernos e bots a cada requisição.
- `--agent googlebot`: Emula o indexador oficial do Google (`Googlebot/2.1`).
- `--agent gptbot`: Emula o bot de IA da OpenAI (`GPTBot/1.2`).
- `--agent bingbot`: Emula o indexador do Bing (`bingbot/2.0`).
- `--agent chrome`: Emula Google Chrome no macOS/Windows com headers Sec-Ch-Ua.
- `--agent firefox`: Emula Mozilla Firefox mais recente.
- `--agent safari`: Emula Apple Safari no macOS.

### Exemplos de Uso:
```bash
# Execução super com 6 crawlers de download simultâneos e rotação de agentes (Máxima Velocidade)
venv/bin/python run_fast.py super --id 129 --crawlers 6 --agent rotate

# Execução se identificando como Googlebot com 4 crawlers
venv/bin/python run_fast.py super --id 129 --crawlers 4 --agent googlebot

# Execução se identificando como GPTBot
venv/bin/python run_fast.py super --id 129 --agent gptbot
```

---

## 6. Otimizações de Download de PDFs (Eliminação de Gargalos)

1. **Extração Fast-Regex de Metadados**: O crawler analisa as meta-tags do cabeçalho HTML via regex compilada em menos de 0.001s, pulando o parser DOM pesado de 50ms por artigo.
2. **Buffer de Download de 64 KB**: Gravação de streams binários em blocos de 65.536 bytes para reduzir chamadas de I/O em disco.
3. **Paralelismo Desacoplado (`--crawlers N`)**: Como a extração de texto (Fase 2) e validação (Fase 3) são instantâneas, o crawler aloca a maior parte dos processos (4 a 8 workers) para a fase de I/O de rede (download).

---

## 7. Como o Agente IA Deve Utilizar Esta Documentação

Em tarefas futuras de otimização:
1. **Passo 1 (Auditoria)**: Execute `venv/bin/python audit_runs.py --last` e `venv/bin/python audit_runs.py --insights`.
2. **Passo 2 (Diagnóstico de Gargalos)**:
   - Se houver muitos erros `HTTP403Forbidden` ou `DownloadFailed`: Teste alternar o perfil de agente (`--agent googlebot` ou `--agent rotate`).
   - Se `speed_articles_per_min` estiver baixo: Inspecione erros na fase `crawling` ou requisições HTTP bloqueadas.
   - Se `speed_emails_per_min` estiver baixo: Inspecione timeouts na fase `verification` (ex: servidores SMTP lentos).
   - Se `crash_recovered_tasks` for alto: Avalie o consumo de memória RAM na fase `extraction` de PDFs grandes para evitar kernel panics no Hackintosh.
3. **Passo 3 (Otimização)**: Aplique melhorias direcionadas no código e execute uma nova run com telemetria para comparar o ganho de throughput nos relatórios de `logs/runs/*.md`.
