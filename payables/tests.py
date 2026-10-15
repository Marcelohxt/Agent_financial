import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction

from accounts.models import Membership, User, Workspace
from core.models import AuditLog
from payables import services
from payables.models import Bill, Document, Holder
from payables.services import Allocation

S = Bill.Status
HOJE = datetime.date(2026, 10, 15)


# --- Titular ------------------------------------------------------------------

def test_titular_rejeita_cpf_invalido(workspace):
    with pytest.raises(ValidationError):
        Holder.objects.create(workspace=workspace, name='X', document_type='cpf', document='12345678900')


def test_titular_guarda_so_digitos(workspace):
    h = Holder.objects.create(
        workspace=workspace, name='Empresa', document_type='cnpj', document='11.222.333/0001-81'
    )
    assert h.document == '11222333000181'


# --- Documento e idempotência -------------------------------------------------

def _pdf(content=b'%PDF-1.4 boleto claro'):
    return ContentFile(content, name='boleto.pdf')


def test_mesmo_pdf_nao_entra_duas_vezes(workspace):
    Document.objects.create(workspace=workspace, kind='boleto', source='upload', file=_pdf())
    with pytest.raises(IntegrityError), transaction.atomic():
        Document.objects.create(workspace=workspace, kind='boleto', source='upload', file=_pdf())


def test_mesma_mensagem_whatsapp_nao_entra_duas_vezes(workspace):
    Document.objects.create(
        workspace=workspace, kind='boleto', source='whatsapp', external_id='wamid.1', file=_pdf(b'a')
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Document.objects.create(
            workspace=workspace, kind='boleto', source='whatsapp', external_id='wamid.1', file=_pdf(b'b')
        )


def test_linha_digitavel_unica(make_bill):
    make_bill(barcode='34191790010104351004791020150008291070026000')
    with pytest.raises(IntegrityError), transaction.atomic():
        make_bill(barcode='34191790010104351004791020150008291070026000')


# --- Máquina de estados ---------------------------------------------------------

def test_fluxo_completo_de_aprovacao(make_bill, marcelo):
    bill = make_bill()
    bill = services.submit_for_validation(bill)  # sistema/IA pode fazer
    assert bill.status == S.PENDING_VALIDATION
    bill = services.approve_bill(bill, actor=marcelo)
    assert bill.status == S.APPROVED
    assert bill.approved_by == marcelo
    assert list(AuditLog.objects.values_list('action', flat=True).order_by('id')) == [
        'bill.submitted', 'bill.approved',
    ]


def test_conta_sem_valor_nao_vai_para_validacao(make_bill):
    with pytest.raises(ValidationError):
        services.submit_for_validation(make_bill(amount=None))


def test_nao_aprova_conta_apenas_recebida(make_bill, marcelo):
    with pytest.raises(ValidationError):
        services.approve_bill(make_bill(), actor=marcelo)


def test_aprovacao_exige_humano_membro(make_bill, workspace):
    bill = make_bill(status=S.PENDING_VALIDATION)
    with pytest.raises(PermissionDenied):
        services.approve_bill(bill, actor=None)  # IA/sistema
    estranho = User.objects.create_user('estranho')
    with pytest.raises(PermissionDenied):
        services.approve_bill(bill, actor=estranho)


def test_cancelar_e_paga_nao_pode(make_bill, marcelo):
    bill = services.cancel_bill(make_bill(), actor=marcelo, reason='duplicada')
    assert bill.status == S.CANCELLED
    with pytest.raises(ValidationError):
        services.cancel_bill(make_bill(status=S.PAID, description='outra'), actor=marcelo)


def test_vencida_e_calculada(make_bill):
    atrasada = make_bill(due=datetime.date(2026, 10, 10))
    em_dia = make_bill(due=datetime.date(2026, 10, 20), description='em dia')
    assert atrasada.is_overdue(HOJE)
    assert not em_dia.is_overdue(HOJE)
    assert list(Bill.objects.overdue(HOJE)) == [atrasada]


# --- Pagamentos -------------------------------------------------------------------

@pytest.fixture
def aprovada(make_bill, marcelo):
    def _make(amount, description='Conta'):
        bill = make_bill(amount=amount, status=S.PENDING_VALIDATION, description=description)
        return services.approve_bill(bill, actor=marcelo)
    return _make


def _pagar(workspace, actor, amount, *allocs):
    return services.register_payment(
        workspace=workspace, actor=actor, paid_at=HOJE, amount=Decimal(amount), method='pix',
        allocations=[Allocation(bill=b, amount=Decimal(v)) for b, v in allocs],
    )


def test_pagamento_parcial_e_depois_quitacao(workspace, marcelo, parceira, aprovada):
    bill = aprovada('300.00')
    _pagar(workspace, marcelo, '100.00', (bill, '100.00'))
    bill.refresh_from_db()
    assert bill.status == S.APPROVED
    assert bill.is_partially_paid()
    assert bill.remaining_amount == Decimal('200.00')

    _pagar(workspace, parceira, '200.00', (bill, '200.00'))
    bill.refresh_from_db()
    assert bill.status == S.PAID
    assert AuditLog.objects.filter(action='bill.paid', actor=parceira).exists()


def test_um_pagamento_quita_varias_contas(workspace, marcelo, aprovada):
    luz, agua = aprovada('150.00', 'Luz'), aprovada('80.50', 'Água')
    _pagar(workspace, marcelo, '230.50', (luz, '150.00'), (agua, '80.50'))
    luz.refresh_from_db()
    agua.refresh_from_db()
    assert luz.status == agua.status == S.PAID


def test_nao_paga_mais_que_o_valor_da_conta(workspace, marcelo, aprovada):
    bill = aprovada('100.00')
    with pytest.raises(ValidationError):
        _pagar(workspace, marcelo, '150.00', (bill, '150.00'))


def test_alocacoes_nao_passam_do_pagamento(workspace, marcelo, aprovada):
    a, b = aprovada('100.00', 'A'), aprovada('100.00', 'B')
    with pytest.raises(ValidationError):
        _pagar(workspace, marcelo, '150.00', (a, '100.00'), (b, '100.00'))


def test_nao_paga_conta_nao_aprovada(workspace, marcelo, make_bill):
    with pytest.raises(ValidationError):
        _pagar(workspace, marcelo, '100.00', (make_bill(), '100.00'))


def test_nao_paga_conta_de_outro_espaco(marcelo, aprovada):
    bill = aprovada('100.00')
    outro = Workspace.objects.create(name='Outro')
    with pytest.raises(PermissionDenied):  # não é membro do outro espaço
        _pagar(outro, marcelo, '100.00', (bill, '100.00'))
    Membership.objects.create(workspace=outro, user=marcelo)
    with pytest.raises(ValidationError):  # é membro, mas a conta é de outro espaço
        _pagar(outro, marcelo, '100.00', (bill, '100.00'))


def test_valores_em_centavos_sem_erro_de_float(workspace, marcelo, aprovada):
    bill = aprovada('0.30')
    _pagar(workspace, marcelo, '0.10', (bill, '0.10'))
    _pagar(workspace, marcelo, '0.20', (bill, '0.20'))
    bill.refresh_from_db()
    assert bill.status == S.PAID


def test_conta_com_pagamento_nao_pode_ser_cancelada(workspace, marcelo, aprovada):
    bill = aprovada('100.00')
    _pagar(workspace, marcelo, '40.00', (bill, '40.00'))
    with pytest.raises(ValidationError):
        services.cancel_bill(bill, actor=marcelo)


# --- Auditoria ---------------------------------------------------------------------

def test_auditoria_nao_pode_ser_alterada_nem_apagada(make_bill, marcelo):
    services.cancel_bill(make_bill(), actor=marcelo)
    log = AuditLog.objects.get()
    log.action = 'adulterado'
    with pytest.raises(PermissionError):
        log.save()
    with pytest.raises(PermissionError):
        log.delete()
