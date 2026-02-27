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
python3 run_fast.py super --workers 4
```
*(Ajuste o número de `--workers` conforme a capacidade da sua máquina para acelerar o processo).*

## 🗃️ Importação da Nota Qualis

Se precisar atualizar as avaliações Qualis dos periódicos da base, substitua o arquivo da plataforma Sucupira Excel (ex: `sucupira.xlsx`) na pasta `docs/` e crie/rode um script de atualização semelhante ao `import_qualis.py` (ou acesse a rota do admin painel pertinente caso ela exista no futuro) para cruzar automaticamente pelo ISSN.

## 💾 Acesso Direto ao Banco (Para devs)
O arquivo gerado fica em `./crawler.db`. Ele pode ser aberto por qualquer gerenciador de banco de dados compatível com SQLite (como DBeaver, SQLite Studio, ou extensão de VSCode).
Tabelas chaves: `journals`, `editions`, `articles`, `files`, `captured_emails`.
