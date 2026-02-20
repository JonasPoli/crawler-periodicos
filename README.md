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

## 🗃️ Importação da Nota Qualis

Se precisar atualizar as avaliações Qualis dos periódicos da base, substitua o arquivo da plataforma Sucupira Excel (ex: `sucupira.xlsx`) na pasta `docs/` e crie/rode um script de atualização semelhante ao `import_qualis.py` (ou acesse a rota do admin painel pertinente caso ela exista no futuro) para cruzar automaticamente pelo ISSN.

## 💾 Acesso Direto ao Banco (Para devs)
O arquivo gerado fica em `./crawler.db`. Ele pode ser aberto por qualquer gerenciador de banco de dados compatível com SQLite (como DBeaver, SQLite Studio, ou extensão de VSCode).
Tabelas chaves: `journals`, `editions`, `articles`, `files`, `captured_emails`.
