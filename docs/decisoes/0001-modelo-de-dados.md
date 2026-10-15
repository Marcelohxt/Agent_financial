# 0001 — Modelo de dados do MVP: contas a pagar

Status: **aprovada por Marcelo em 2026-10-15; implementada**
Data: 2026-10-15

## Contexto

- Dois usuários compartilham o mesmo controle financeiro. Toda ação registra **quem fez** e
  **quem aprovou**.
- Uso pessoal, com um acesso PJ (ex.: Claro Empresas). Cada conta a pagar carrega o **CPF ou
  CNPJ do titular**.
- O foco do MVP é **contas a pagar**: boletos e faturas com vencimento, PDFs vinculados,
  pagamentos parciais, um pagamento cobrindo várias contas, comprovantes.
- Mensagens e downloads podem chegar repetidos: o sistema precisa ser **idempotente**
  (receber o mesmo documento duas vezes não cria duas contas).
- Princípio da arquitetura: **o LLM propõe, o código valida, o humano confirma**. A IA pode
  extrair dados de um PDF, mas nunca aprova nem marca como paga.

## Entidades

```
Espaço ──< Membro >── Usuário
  │
  ├──< Titular (CPF/CNPJ)
  ├──< Fornecedor
  ├──< Documento (PDF)
  ├──< Conta a pagar >── Titular, Fornecedor
  │        └──< Documento (boleto, fatura)
  ├──< Pagamento ── Documento (comprovante)
  │        └──< Alocação >── Conta a pagar
  └──< Auditoria
```

### Espaço (`Workspace`) e Membro (`Membership`)
O "controle financeiro" compartilhado. Os dois usuários são membros do mesmo espaço; todos os
dados pertencem ao espaço, e toda consulta filtra pelo espaço do usuário logado.

O membro guarda o **telefone do WhatsApp** (formato E.164, ex.: `+5511999998888`), único no
sistema. Uma mensagem recebida só é aceita se vier de um telefone cadastrado e verificado; é
assim que o sistema sabe quem enviou e em qual espaço gravar.

### Titular (`Holder`)
Em nome de quem a conta está.

| Campo | Tipo | Observação |
|---|---|---|
| name | texto | "Marcelo", "Empresa X" |
| document_type | escolha | CPF ou CNPJ |
| document | texto | só dígitos; **dígitos verificadores validados no código** |

Único por (espaço, documento).

### Fornecedor (`Supplier`)
Quem cobra: "Claro", "Enel", "Condomínio".

| Campo | Tipo | Observação |
|---|---|---|
| name | texto | |
| document | texto (opcional) | CNPJ/CPF do fornecedor, quando conhecido |

### Documento (`Document`)
Qualquer arquivo recebido: boleto, fatura, comprovante.

| Campo | Tipo | Observação |
|---|---|---|
| kind | escolha | boleto, fatura, comprovante, outro |
| file | arquivo | guardado fora do banco (pasta `media/`, depois armazenamento externo) |
| sha256 | texto (64) | hash do conteúdo; **único por espaço** → mesmo PDF não entra duas vezes |
| source | escolha | upload, e-mail, mensagem, download |
| external_id | texto (opcional) | id da mensagem/e-mail de origem; **único por (espaço, source, external_id)** |
| original_name / received_at / uploaded_by | | |

### Conta a pagar (`Bill`)
Uma obrigação com vencimento.

| Campo | Tipo | Observação |
|---|---|---|
| holder | FK → Titular | CPF/CNPJ do titular |
| supplier | FK → Fornecedor | |
| description | texto | "Fatura Claro 10/2026" |
| amount | decimal(14,2) | valor total; sempre > 0 |
| due_date | data | vencimento |
| barcode | texto (opcional) | linha digitável; **única por espaço** quando preenchida |
| status | escolha | ver máquina de estados |
| source | escolha | manual ou extraída por IA |
| documents | M2M → Documento | boleto, fatura e outros anexos |
| created_by, approved_by, approved_at, cancelled_by, cancelled_at | | quem fez cada passo |

**Máquina de estados** (transições só pelo código, cada uma gera auditoria):

```
recebida ──► pendente_validacao ──► aprovada ──► paga
    │               │                  │
    └───────────────┴──────────────────┴──► cancelada
```

- `recebida`: o documento chegou; os dados ainda podem estar incompletos.
- `pendente_validacao`: os dados foram extraídos (pela IA ou digitados) e aguardam um humano.
- `aprovada`: um membro conferiu e aprovou. **Só um humano faz essa transição.**
- `paga`: as alocações de pagamento somam exatamente o valor da conta. O código faz essa
  transição sozinho quando a soma fecha; nunca a IA.
- `cancelada`: não será paga. Conta paga não pode ser cancelada.
- **Vencida não é guardada; é calculada**: `due_date < hoje` e status diferente de `paga` ou
  `cancelada`. Guardar exigiria uma tarefa diária para atualizar e poderia ficar errado se ela
  falhasse.
- **Parcialmente paga** também é calculada: soma das alocações > 0 e < valor.

### Pagamento (`Payment`) e Alocação (`PaymentAllocation`)
Um pagamento é o dinheiro que saiu; a alocação diz quais contas ele quitou.

| Pagamento | Tipo | Observação |
|---|---|---|
| paid_at | data | |
| amount | decimal(14,2) | > 0 |
| method | escolha | pix, boleto, débito, transferência, outro |
| receipt | FK → Documento (opcional) | comprovante |
| registered_by | FK → Usuário | |

| Alocação | Tipo | Observação |
|---|---|---|
| payment | FK → Pagamento | |
| bill | FK → Conta a pagar | só contas `aprovada` |
| amount | decimal(14,2) | > 0 |

Isso cobre os três casos:
- **Pagamento parcial**: uma alocação menor que o valor da conta.
- **Um pagamento para várias contas**: várias alocações no mesmo pagamento.
- **Várias parcelas da mesma conta**: várias alocações para a mesma conta.

Regras (no código, com teste, dentro de uma transação de banco com bloqueio de linha):
- Soma das alocações de um pagamento ≤ valor do pagamento.
- Soma das alocações de uma conta ≤ valor da conta.
- Pagamento registrado não é editado nem apagado; corrige-se estornando.

### Auditoria (`AuditLog`)
| Campo | Observação |
|---|---|
| actor | usuário (vazio quando foi o sistema/IA) |
| action | `bill.approved`, `payment.registered`... |
| target | tipo + id do registro |
| changes | JSON com antes e depois |
| created_at | |

Só inserção: o código nunca altera nem apaga uma linha de auditoria.

## Regras gerais
- Dinheiro sempre `Decimal`, nunca `float` (`0.1 + 0.2 != 0.3` em float).
- Moeda única: BRL.
- Nada financeiro é apagado; registros são cancelados ou estornados.
- A IA só cria contas em `recebida`/`pendente_validacao`. Aprovar e pagar exigem um humano.

## Canal: WhatsApp

A interface principal será o WhatsApp: o casal envia boletos, faturas e comprovantes, e o
sistema responde pedindo confirmação.

- **API oficial (WhatsApp Cloud API, da Meta)**, com um número próprio do sistema.
  Bibliotecas não oficiais (que simulam o WhatsApp Web) violam os termos do WhatsApp e podem ter
  o número banido; não servem para um sistema financeiro.
- **Conversa individual, não grupo.** A API de grupos exige conta comercial oficial verificada
  pela Meta e tem limites de participantes. Cada um conversa com o número do sistema; como os dois
  são membros do mesmo espaço, o sistema avisa o outro quando algo muda ("Marcelo registrou o
  pagamento da Claro"). O efeito para o casal é o mesmo de um grupo.
- **Idempotência**: a Meta pode reenviar a mesma notificação. O id da mensagem do WhatsApp vai em
  `Document.external_id` (e num registro de mensagens recebidas), então a mesma mensagem nunca é
  processada duas vezes.
- **Confirmação humana pelo próprio chat**: a IA lê o PDF e propõe ("Claro, R$ 189,90, vence
  20/10. Aprovar?"); a aprovação é a resposta do membro, registrada na auditoria com o telefone.

## Fora desta fase (de propósito)
- Buscar boletos sozinho nos sites dos fornecedores (ex.: portal da Claro). Exige guardar login e
  senha de terceiros e automatizar sites com captcha, o que traz risco de segurança e pode violar
  os termos dos sites. Alternativas a avaliar depois: encaminhamento automático de e-mails de
  fatura e DDA (boletos registrados no seu CPF/CNPJ, via banco).
- Cartão de crédito com fatura detalhada, parcelamento e recorrência.
- Contas bancárias e saldo (de onde saiu o dinheiro).
- Contas a receber e lançamentos genéricos.
- Múltiplas moedas.
- Integração com e-mail/mensagens e extração por IA (o modelo já está pronto para recebê-las).
