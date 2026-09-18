# Academic Journal Crawler & Admin Panel

This project is a high-performance, automated crawler system designed to harvest metadata, extract PDFs, verify e-mails, and manage data from academic journals hosted on **SciELO** and **OJS**. It includes a modern, web-based administrative panel to view and filter the collected data, as well as several workers to process articles concurrently.

## 🚀 Como instalar e rodar em uma máquina nova

Para configurar o projeto do zero em outro computador, siga estes passos:

### 1. Requisitos do Sistema
- **Python 3.9+**
- (Opcional) Git para clonar o repositório.

### 2. Clonar / Baixar o projeto
Clone o repositório ou copie a pasta do projeto para o novo computador.
```bash
git clone <url-do-repositorio> crawler
cd crawler
```

### 3. Criar e Ativar o Ambiente Virtual
É altamente recomendado rodar o projeto dentro de um ambiente virtual (venv) para isolar as dependências.
```bash
# Cria o ambiente virtual na pasta "venv"
python3 -m venv venv

# Ativa o ambiente virtual (Mac/Linux)
source venv/bin/activate

# Ou ative no Windows (Prompt de Comando)
venv\Scripts\activate
```

### 4. Instalar as Dependências
Com o ambiente ativado, instale os pacotes necessários lendo o `requirements.txt`:
```bash
pip install -r requirements.txt
```
*(Pacotes principais: `flask`, `sqlalchemy`, `requests`, `beautifulsoup4`, `pandas`, `openpyxl`, `tqdm`, `pypdf`)*

### 5. Configurar o Banco de Dados Inicial
O sistema utiliza um banco de dados SQLite local (`crawler.db`), o que significa que não é necessário instalar servidores MySQL ou Postgres.
Para inicializar as tabelas e popular a base com os jornais padrão (lidos de `journals.json`), rode:
```bash
python3 populate_db.py
```

## 🕸️ Componentes do Sistema (Como tudo funciona)

O projeto é dividido em três grandes módulos operacionais:

### 1. Crawlers (Orquestrador)
Scripts responsáveis por navegar pelas páginas e baixar arquivos brutos.
- **`run_fast.py` / `orchestrator.py`**: Gerencia o pipeline de execução. Executa os robôs em modo pararelo.
- Os robôs escrapeiam os sites buscando Edições e Artigos. Os PDFs são baixados para as pastas `/downloads_scielo/` e `/downloads_ojs/`.

**Para rodar o processo de extração completo (Scrape + Baixar PDFs):**
```bash
python3 run_fast.py
```

### 2. Processadores e Verificadores (Workers paralelos)
Após o HTML e o PDF serem baixados, os workers leem os arquivos locais para extrair inteligência.
- **`worker_processor.py`**: Abre os PDFs baixados, extrai o texto e varre em busca de e-mails, além de metadados como autores e ORCID.
- **`worker_verifier.py`**: Pega todos os e-mails encontrados (`CapturedEmail`) e faz testes de ping no DNS e SMTP para checar se as caixas de entrada existem e são válidas (salvando como `VALID` ou `INVALID`).

**Para rodar os workers separadamente:**
- `python3 run_fast.py --mode process` (Processar PDFs)
- `python3 run_fast.py --mode verify` (Verificar E-mails)

### 3. Painel Administrativo (Web)
Uma interface amigável escrita em Flask para gerenciar os dados sem precisar usar SQL no terminal.

**Para rodar o painel:**
```bash
cd admin_panel
python3 app.py
```
Acesse no navegador: [http://127.0.0.1:5000](http://127.0.0.1:5000)

**O que você pode fazer no painel:**
- **Dashboard**: Ver estatísticas em tempo real, quanto tempo falta para o crawler terminar e a velocidade de Processamento/Verificação.
- **Periódicos**: Lista todos os jornais, seus links, Qualis importado (CAPES) e ISSNs.
- **Artigos e E-mails**: Ver metadados ricos extraídos dos artigos, ver os e-mails extraídos e se eles são válidos (`VALID`).
- **Relatórios**: Exportar bases consolidadas de contatos (e-mails por periódicos e cruzamento de status) em arquivo `.csv`.

## ➕ Como adicionar um novo periódico e extrair tudo

Para adicionar um novo periódico ao crawler e configurar o sistema para encontrar todas as edições, baixar todos os artigos, extrair autores/arquivos e testar todos os e-mails encontrados, siga estes 3 passos:

### 1. Adicionar o periódico à lista
Você tem três opções para cadastrar um novo periódico:
- **Opção A (Pelo Painel Admin):** Com o painel rodando (`python3 app.py` dentro da pasta `admin_panel`), acesse `http://127.0.0.1:5000/journals/create` no seu navegador. Preencha o formulário (Nome, URL, Tipo Fonte) e salve. *(Recomendado para uso visual)*.
- **Opção B (Manual):** Abra o arquivo `journals.json` e adicione um novo bloco JSON com o `name`, `url` e `type` (`ojs` ou `scielo`).
- **Opção C (Automática via Script):** Edite o arquivo `add_journals.py`, adicione o link do periódico na variável `USER_URLS` e, no terminal, rode:
  ```bash
  python3 add_journals.py
  ```

### 2. Sincronizar com o Banco de Dados (Apenas para Opções B e C)
Se você cadastrou pelo **Painel Admin (Opção A)**, o periódico já foi salvo direto no banco de dados e você pode **pular este passo**.
Caso tenha usado as opções Manuais ou via Script (`journals.json`), você precisa avisar o banco de dados que existem novos periódicos executando:
```bash
python3 populate_db.py
```

### 3. Rodar o "Super Processo" (Processamento Completo e Paralelo)
Execute o orquestrador no modo `super` para ele automaticamente descobrir as edições, baixar os artigos, extrair as informações e validar os e-mails simultaneamente:
```bash
venv/bin/python3 run_fast.py super --workers 4
```
*(Ajuste o número de `--workers` conforme a capacidade da sua máquina para acelerar o processo).*

## 📏 Tamanho dos periódicos (antes de processar)

O `journal_sizer.py` mede quantas edições e artigos cada periódico tem **direto no site**, sem baixar nada. Serve de base para estimar quantos e-mails um periódico deve render (`artigos no site × média de e-mails por PDF do sistema`).

Estratégias, das mais baratas às mais caras (vence a primeira que responder):
- **OJS:** sitemap (`/sitemap`, exato) → OAI-PMH (`/oai`, exato) → arquivo de edições + contagem dos sumários (todos, ou amostra quando há mais de 40 edições).
- **SciELO:** API ArticleMeta pelo ISSN (exato) → `/grid` + contagem dos sumários.
- **Último recurso** (site fora do ar ou atrás de desafio anti-bot, como o Cloudflare): total de DOIs no Crossref, pelo ISSN ou pelo título exato (estimado).

Só entra na conta o que pertence ao periódico cadastrado: links para outros periódicos (do mesmo site ou de fora) são ignorados, assim como na média de e-mails por PDF, que usa apenas PDFs do próprio periódico.

Quando roda:
- **Ao cadastrar** um periódico pelo painel (ou ao mudar a URL/tipo), em segundo plano.
- **Ao rodar** `populate_db.py`, para os periódicos ainda sem medição.
- **Varredura geral**, pela linha de comando ou pelo painel (**Tamanho dos Periódicos**):
  ```bash
  venv/bin/python journal_sizer.py --all                # todos os periódicos ativos
  venv/bin/python journal_sizer.py --missing            # só os que ainda não têm medição válida
  venv/bin/python journal_sizer.py --stale-days 30      # medição válida mais velha que 30 dias
  venv/bin/python journal_sizer.py --id 129 --dry-run   # mede e mostra, sem gravar
  venv/bin/python journal_sizer.py --all --full         # sem amostragem nos sumários
  ```

As medições ficam na tabela `journal_size_estimates` (histórico: uma linha por medição, com o detalhe de cada estratégia em JSON).

**Anti-bot:** quando nada do site responde sem desafio/bloqueio (Cloudflare, Sucuri, Imperva, DDoS-Guard, AWS WAF, captcha), a medição grava `blocked_by` e o periódico aparece como *bloqueado: extração impossível*. O tamanho, nesse caso, vem do Crossref.

### Relatório de cobertura (painel → Tamanho dos Periódicos → Exportar CSV)

`journal_report.py` cruza a medição do site com o banco e mostra, por periódico e no total: artigos no site, analisados, sem PDF, com erro, na fila, não descobertos e a analisar; e-mails encontrados, únicos e válidos; e-mails supostos, ainda a extrair e não extraíveis (por anti-bot e por falta de PDF). O CSV sai em `/journals/sizes?export=csv`, com uma linha `TOTAL` no fim.

Regras das contagens do banco:
- Só entram artigos do próprio periódico (URL sob a raiz cadastrada ou sob a raiz onde o site publica de fato, por exemplo o domínio novo após uma migração).
- Cada artigo conta uma vez, pelo id (ignora galé, `/abstract/`, `?lang=` e http/https/www).
- *Analisado* = PDF processado (`completed`) ou artigo que já tem e-mails. O `reset_journal_for_rerun` volta artigos processados para `found` sem apagar os e-mails; os que foram processados sem e-mail aparecem como *na fila*, porque serão reprocessados.
- *E-mails encontrados* somam os e-mails de cada artigo, na mesma unidade das estimativas. *Únicos* e *válidos* contam endereços distintos.

## 🗃️ Importação da Nota Qualis

Se precisar atualizar as avaliações Qualis dos periódicos da base, substitua o arquivo da plataforma Sucupira Excel (ex: `sucupira.xlsx`) na pasta `docs/` e crie/rode um script de atualização semelhante ao `import_qualis.py` (ou acesse a rota do admin painel pertinente caso ela exista no futuro) para cruzar automaticamente pelo ISSN.

## 💾 Acesso Direto ao Banco (Para devs)
O arquivo gerado fica em `./crawler.db`. Ele pode ser aberto por qualquer gerenciador de banco de dados compatível com SQLite (como DBeaver, SQLite Studio, ou extensão de VSCode).
Tabelas chaves: `journals`, `editions`, `articles`, `files`, `captured_emails`.


## Só uma revista:
Para rodar apenas para a revista de id=1
venv/bin/python3 run_fast.py super --workers 4 --id 1





venv/bin/python run_fast.py super --id 127 && venv/bin/python run_fast.py super --id 128 && venv/bin/python run_fast.py super --id 26

