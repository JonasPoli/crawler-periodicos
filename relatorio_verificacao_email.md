# Relatório de Verificação de E-mails

Este documento descreve tecnicamente o processo de verificação de validade e existência de e-mails implementado no sistema **Crawler Periodicos**.

## 1. Visão Geral
O sistema de verificação é escrito em **Python 3** e utiliza uma abordagem multicamada para garantir que um e-mail seja sintaticamente correto, pertença a um domínio válido e que a caixa postal realmente exista no servidor de destino.

As principais bibliotecas utilizadas são:
- `re`: Para validação de sintaxe via expressões regulares.
- `dns.resolver` (`dnspython`): Para consultas de registros DNS (A e MX).
- `smtplib`: Para comunicação direta com os servidores de e-mail via protocolo SMTP.

---

## 2. Processo de Verificação Passo a Passo

 O processo é executado em quatro níveis de profundidade:

### Nível 1: Validação de Sintaxe (Regex)
O primeiro teste verifica se a string do e-mail segue o formato padrão (ex: `usuario@dominio.com`).

**Código fonte (`worker_verifier.py`):**
```python
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

def verify_syntax(email):
    return bool(EMAIL_REGEX.match(email))
```

### Nível 2: Verificação de Domínio e MX (DNS)
O sistema verifica se o domínio existe e se possui um servidor de e-mail configurado (registro MX). Se não houver MX, ele tenta verificar se o domínio possui um registro A (alguns servidores aceitam e-mails diretamente no IP do domínio).

**Código fonte (`worker_verifier.py`):**
```python
def verify_domain_dns(domain):
    try:
        # Tenta resolver o registro MX (Mail Exchange)
        dns.resolver.resolve(domain, 'MX')
        return True
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        try:
            # Caso não tenha MX, tenta ver se existe um registro A
            dns.resolver.resolve(domain, 'A')
            return True
        except:
            return False
    except:
        return False
```

### Nível 3: Verificação de Existência da Caixa Postal (SMTP)
Este é o teste mais avançado. O sistema conecta-se ao servidor de e-mail remoto e simula o início de um envio de mensagem sem de fato enviá-la. Ele utiliza o comando `RCPT TO` para perguntar ao servidor se aquele endereço específico é aceito.

**O que é testado:**
1. **Conexão**: Se o servidor responde na porta 25 (SMTP).
2. **HELO/EHLO**: Identificação do verificador perante o servidor.
3. **MAIL FROM**: Inicia a transação de e-mail.
4. **RCPT TO**: O servidor responde se o e-mail existe (`250 OK`) ou se é inválido (`550 User unknown`).

**Código fonte (`worker_verifier.py`):**
```python
def verify_smtp(email, mx_record):
    try:
        server = smtplib.SMTP(timeout=5)
        code, message = server.connect(mx_record)
        if code != 220:
            server.quit()
            return False
        
        server.helo(socket.gethostname())
        server.mail('test@example.com') # Remetente fictício para o teste
        code, message = server.rcpt(email) # O teste crucial de existência
        server.quit()
        
        if code == 250:
            return True # O e-mail existe
        return False # O servidor rejeitou o destinatário
    except Exception:
        return False
```

### Nível 4: Verificação POP
**Nota Técnica:** O sistema **não utiliza o protocolo POP** (Post Office Protocol) para verificação. O POP é um protocolo de *recebimento* (leitura) de mensagens por parte do usuário final. Para verificar se um e-mail *existe*, o padrão técnico mundial é o uso do protocolo **SMTP** através do comando `RCPT TO`, como detalhado acima.

---

## 3. Fluxo de Decisão e Estados
Os resultados são consolidados no banco de dados (`crawler.db`) na tabela `captured_emails`.

| Status Final | Significado |
| :--- | :--- |
| **VALID** | Passou na sintaxe, DNS e o servidor SMTP confirmou a existência. |
| **INVALID** | Falhou em qualquer um dos testes (Sintaxe, Domínio ou Rejeição SMTP). |
| **PENDING** | E-mail capturado mas ainda aguardando a rodada de verificação. |
| **UNKNOWN** | Erro técnico durante a verificação (Ex: Timeout do servidor). |

---

## 4. Resumo Técnico
- **Linguagem**: Python 3.
- **Protocolo de Existência**: SMTP (Porta 25).
- **DNS**: Consultas de registros MX e A.
- **Conformidade**: RFC 5321 (SMTP).
- **Paralelismo**: O sistema utiliza múltiplos workers para processar milhares de e-mails simultaneamente.
