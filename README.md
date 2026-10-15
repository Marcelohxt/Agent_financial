# Agent Financial

🇧🇷 [Português](#português) · 🇺🇸 [English](#english)

---

## Português

Assistente financeiro para um casal controlar **contas a pagar** pelo **WhatsApp**: vocês enviam
boletos, faturas e comprovantes; o sistema organiza, pede confirmação e registra quem fez cada coisa.

> **Status:** em desenvolvimento (Fase 2 — MVP). O núcleo de contas a pagar e o recebimento de
> mensagens do WhatsApp estão prontos e testados. A conexão real com a Meta, a leitura dos PDFs e a
> extração por IA ainda não foram feitas.

### Princípio central

**O LLM propõe, o código valida, o humano confirma.**

- A IA pode ler um PDF e sugerir "Claro, R$ 189,90, vence 20/10".
- Regras de negócio, cálculos e validações são **código determinístico e testado**, nunca a IA.
- Aprovar uma conta e registrar um pagamento são **sempre ações de uma pessoa**, registradas na
  auditoria.

### O que já funciona

| Área | O que faz |
|---|---|
| Espaço compartilhado | Os dois membros veem e gerenciam os mesmos dados |
| Titulares | Contas em nome de CPF ou CNPJ, com dígitos verificadores validados |
| Documentos | PDFs com hash SHA-256: o mesmo arquivo nunca entra duas vezes |
| Contas a pagar | Máquina de estados `recebida → pendente de validação → aprovada → paga` (ou `cancelada`) |
| Pagamentos | Parciais, um pagamento para várias contas, várias parcelas da mesma conta |
| Auditoria | Registro de quem fez o quê; não pode ser alterado nem apagado |
| Webhook do WhatsApp | Confere a assinatura da Meta, ignora mensagens repetidas, só aceita telefones cadastrados e verificados |
| Admin | Painel do Django para consultar e cadastrar dados |

### Arquitetura

```
WhatsApp (Meta Cloud API)
        │  webhook HTTPS + assinatura HMAC
        ▼
┌──────────────────────────────┐
│ Django                       │
│  whatsapp/  recebe mensagens │──► InboundMessage (idempotente)
│  payables/  regras de negócio│──► Contas, Pagamentos, Documentos
│  accounts/  usuários, espaço │
│  core/      auditoria, saúde │──► AuditLog (só inserção)
└──────────────┬───────────────┘
               ▼
         PostgreSQL 17
```

Um **orquestrador único** (sem multiagentes, sem LangChain): as chamadas ao modelo de IA serão
explícitas, pelo SDK oficial, para facilitar auditoria e testes. Detalhes e justificativas em
[docs/decisoes/0001-modelo-de-dados.md](docs/decisoes/0001-modelo-de-dados.md).

### Modelo de dados

```
Espaço ──< Membro >── Usuário          (membro guarda o telefone do WhatsApp)
  ├──< Titular (CPF/CNPJ)
  ├──< Fornecedor
  ├──< Documento (PDF)
  ├──< Conta a pagar ── Titular, Fornecedor, Documentos
  ├──< Pagamento ── Comprovante
  │      └──< Alocação >── Conta a pagar
  └──< Auditoria
```

Decisões importantes:

- **Dinheiro em `Decimal`**, nunca `float` (`0.1 + 0.2 != 0.3` em float).
- **"Vencida" e "parcialmente paga" são calculadas**, não gravadas: não dependem de uma tarefa
  agendada que pode falhar.
- **Nada financeiro é apagado**: contas são canceladas, pagamentos serão estornados.
- **Moeda única:** BRL.

### Tecnologias

| Item | Versão | Por quê |
|---|---|---|
| Python | 3.12 | Suporte de segurança até 2028 |
| Django | 5.2 LTS | Suporte até abril de 2028 |
| PostgreSQL | 17 | Transações, restrições e bloqueio de linha confiáveis |
| psycopg | 3 | Driver oficial do PostgreSQL |
| django-environ | 0.14 | Configuração e segredos via `.env` |
| pytest + pytest-django | 9 / 4 | Testes |
| ruff | 0.17 | Lint e formatação |

### Pré-requisitos

- Windows 10/11 (os comandos abaixo são para PowerShell; em Linux/macOS, troque
  `.venv\Scripts\Activate.ps1` por `source .venv/bin/activate`)
- Python 3.12
- PostgreSQL 17 rodando localmente
- Git

### Instalação

```powershell
# 1. Clonar
git clone https://github.com/Marcelohxt/Agent_financial.git
cd Agent_financial

# 2. Ambiente virtual
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
# Se o Windows bloquear o script:
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# 3. Dependências
pip install -r requirements.txt

# 4. Configuração
copy .env.example .env
# Edite o .env e preencha SECRET_KEY e DATABASE_URL
```

Gerar uma `SECRET_KEY`:

```powershell
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### Banco de dados

Abra o **SQL Shell (psql)** pelo menu Iniciar, entre como `postgres` e rode:

```sql
CREATE ROLE agent_financial LOGIN PASSWORD 'SUA_SENHA' CREATEDB;
CREATE DATABASE agent_financial OWNER agent_financial;
```

`CREATEDB` permite que os testes criem um banco temporário. Depois:

```powershell
python manage.py migrate
python manage.py createsuperuser
```

### Executar

```powershell
python manage.py runserver
```

| Endereço | O quê |
|---|---|
| http://127.0.0.1:8000/health/ | Verificação de saúde (`{"status": "ok"}`) |
| http://127.0.0.1:8000/admin/ | Painel administrativo |
| http://127.0.0.1:8000/webhooks/whatsapp/ | Webhook da Meta (exige assinatura válida) |

### Testes e qualidade

```powershell
pytest -v          # todos os testes (os nomes estão em português e descrevem as regras)
ruff check .       # lint
python manage.py check
```

### Variáveis de ambiente

Todas ficam no `.env`, que **nunca** vai para o Git. Modelo completo em [.env.example](.env.example).

| Variável | Obrigatória | Descrição |
|---|---|---|
| `SECRET_KEY` | sim | Chave secreta do Django |
| `DEBUG` | não | `True` só no seu computador. Padrão: `False` |
| `ALLOWED_HOSTS` | não | Hosts aceitos, separados por vírgula |
| `DATABASE_URL` | sim | `postgres://usuario:senha@host:5432/banco` |
| `MEDIA_ROOT` | não | Pasta dos PDFs. Padrão: `media/` |
| `WHATSAPP_PHONE_NUMBER_ID` | para WhatsApp | ID do número na Meta |
| `WHATSAPP_ACCESS_TOKEN` | para WhatsApp | Token de acesso da Cloud API |
| `WHATSAPP_APP_SECRET` | para WhatsApp | Chave do app, usada para conferir a assinatura do webhook |
| `WHATSAPP_VERIFY_TOKEN` | para WhatsApp | Texto aleatório cadastrado no webhook da Meta |

### Estrutura

```
config/        configurações, URLs
accounts/      usuário, espaço compartilhado, membros (com telefone)
core/          auditoria, validadores (CPF, CNPJ, telefone), rota de saúde
payables/      titulares, fornecedores, documentos, contas, pagamentos
  services.py  regras de negócio: toda mudança de status passa por aqui
whatsapp/      webhook e registro de mensagens recebidas
docs/decisoes/ registros de decisões de arquitetura
```

### Segurança

- Segredos só no `.env` (ignorado pelo Git).
- `DEBUG` desligado por padrão.
- Webhook autenticado por HMAC-SHA256; sem chave configurada, recusa tudo.
- Mensagens só são aceitas de telefones cadastrados e verificados.
- Toda requisição roda numa transação; pagamentos travam as contas envolvidas para evitar
  pagamento duplicado em acessos simultâneos.
- Auditoria só de inserção.
- Conteúdo externo (mensagens, PDFs) é tratado como não confiável.

**Antes de usar com dados reais:** troque a autenticação `trust` do PostgreSQL por
`scram-sha-256`, use senhas fortes, HTTPS e um token permanente da Meta.

### Próximos passos

- [ ] Liberar a conta de desenvolvedor na Meta e conectar o número de teste
- [ ] Baixar o PDF recebido e criar a conta a pagar como "recebida"
- [ ] Extrair dados do boleto (linha digitável, valor, vencimento) com validação no código
- [ ] Aprovação e registro de pagamento pelo chat
- [ ] Avisar o outro membro quando algo mudar
- [ ] Consultas ("gastos da última semana") calculadas pelo código
- [ ] Estorno de pagamento
- [ ] Implantação com HTTPS e armazenamento externo de arquivos

Fora do MVP, de propósito: busca automática de boletos em sites de fornecedores, cartão de crédito
com parcelas, contas bancárias e saldo, múltiplas moedas.

---

## English

A financial assistant for a couple to manage **bills to pay** over **WhatsApp**: you send
boletos (Brazilian payment slips), invoices and receipts; the system organizes them, asks for
confirmation and records who did what.

> **Status:** in development (Phase 2 — MVP). The bills core and WhatsApp message intake are done
> and tested. The live Meta connection, PDF reading and AI extraction are not built yet.

### Core principle

**The LLM proposes, code validates, a human confirms.**

- The AI may read a PDF and suggest "Claro, R$ 189.90, due Oct 20".
- Business rules, calculations and validations are **deterministic, tested code**, never the AI.
- Approving a bill and recording a payment are **always done by a person**, and audited.

### What works today

| Area | What it does |
|---|---|
| Shared workspace | Both members see and manage the same data |
| Holders | Bills under a CPF or CNPJ (Brazilian tax IDs), with check digits validated |
| Documents | PDFs hashed with SHA-256: the same file is never stored twice |
| Bills | State machine `received → pending validation → approved → paid` (or `cancelled`) |
| Payments | Partial payments, one payment for several bills, several payments for one bill |
| Audit log | Who did what; cannot be edited or deleted |
| WhatsApp webhook | Verifies Meta's signature, ignores duplicate deliveries, only accepts registered, verified phones |
| Admin | Django admin to browse and enter data |

### Architecture

```
WhatsApp (Meta Cloud API)
        │  HTTPS webhook + HMAC signature
        ▼
┌──────────────────────────────┐
│ Django                       │
│  whatsapp/  message intake   │──► InboundMessage (idempotent)
│  payables/  business rules   │──► Bills, Payments, Documents
│  accounts/  users, workspace │
│  core/      audit, health    │──► AuditLog (insert-only)
└──────────────┬───────────────┘
               ▼
         PostgreSQL 17
```

A **single orchestrator** (no multi-agent setup, no LangChain): model calls will be explicit,
through the official SDK, so they are easy to audit and test. Rationale (in Portuguese) in
[docs/decisoes/0001-modelo-de-dados.md](docs/decisoes/0001-modelo-de-dados.md).

### Data model

```
Workspace ──< Membership >── User      (membership stores the WhatsApp phone)
  ├──< Holder (CPF/CNPJ)
  ├──< Supplier
  ├──< Document (PDF)
  ├──< Bill ── Holder, Supplier, Documents
  ├──< Payment ── Receipt
  │      └──< PaymentAllocation >── Bill
  └──< AuditLog
```

Key decisions:

- **Money is `Decimal`**, never `float` (`0.1 + 0.2 != 0.3` in float).
- **"Overdue" and "partially paid" are computed**, not stored, so they never depend on a
  scheduled job that might fail.
- **Nothing financial is deleted**: bills are cancelled, payments will be reversed.
- **Single currency:** BRL.

### Stack

| Item | Version | Why |
|---|---|---|
| Python | 3.12 | Security support until 2028 |
| Django | 5.2 LTS | Supported until April 2028 |
| PostgreSQL | 17 | Reliable transactions, constraints and row locking |
| psycopg | 3 | Official PostgreSQL driver |
| django-environ | 0.14 | Settings and secrets from `.env` |
| pytest + pytest-django | 9 / 4 | Tests |
| ruff | 0.17 | Lint and formatting |

### Requirements

- Windows 10/11 (commands below are PowerShell; on Linux/macOS use
  `source .venv/bin/activate` instead of `.venv\Scripts\Activate.ps1`)
- Python 3.12
- PostgreSQL 17 running locally
- Git

### Setup

```powershell
git clone https://github.com/Marcelohxt/Agent_financial.git
cd Agent_financial

py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1

pip install -r requirements.txt

copy .env.example .env
# Edit .env and fill in SECRET_KEY and DATABASE_URL
```

Create the database (in `psql` as `postgres`):

```sql
CREATE ROLE agent_financial LOGIN PASSWORD 'YOUR_PASSWORD' CREATEDB;
CREATE DATABASE agent_financial OWNER agent_financial;
```

Then:

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

| URL | What |
|---|---|
| http://127.0.0.1:8000/health/ | Health check (`{"status": "ok"}`) |
| http://127.0.0.1:8000/admin/ | Admin panel |
| http://127.0.0.1:8000/webhooks/whatsapp/ | Meta webhook (requires a valid signature) |

### Tests and quality

```powershell
pytest -v
ruff check .
python manage.py check
```

Test names are in Portuguese and read as a list of business rules.

### Environment variables

See the table in the Portuguese section above and [.env.example](.env.example). The `.env` file is
**never** committed.

### Project layout

```
config/        settings, URLs
accounts/      user, shared workspace, memberships (with phone)
core/          audit log, validators (CPF, CNPJ, phone), health check
payables/      holders, suppliers, documents, bills, payments
  services.py  business rules: every status change goes through here
whatsapp/      webhook and inbound message log
docs/decisoes/ architecture decision records (Portuguese)
```

### Security

- Secrets only in `.env` (git-ignored); `DEBUG` off by default.
- Webhook authenticated with HMAC-SHA256; with no secret configured it rejects everything.
- Messages accepted only from registered, verified phones.
- Every request runs in a transaction; payments lock the affected bills to prevent double
  payment under concurrent access.
- Insert-only audit log. External content (messages, PDFs) is treated as untrusted.

**Before using real data:** switch PostgreSQL's `trust` authentication to `scram-sha-256`, use
strong passwords, HTTPS and a permanent Meta token.

### Roadmap

- [ ] Get the Meta developer account approved and connect the test number
- [ ] Download the received PDF and create the bill as "received"
- [ ] Extract boleto data (barcode line, amount, due date) with code-side validation
- [ ] Approval and payment recording from the chat
- [ ] Notify the other member when something changes
- [ ] Queries ("spending last week") computed by code
- [ ] Payment reversal
- [ ] Deployment with HTTPS and external file storage

Intentionally out of the MVP: automatic boleto fetching from supplier websites, credit cards with
installments, bank accounts and balances, multiple currencies.
