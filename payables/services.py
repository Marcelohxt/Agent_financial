"""Regras de negócio de contas a pagar.

Toda mudança de status e todo pagamento passa por aqui: as funções validam, gravam numa
transação de banco e registram auditoria. A IA nunca chama `approve_bill` nem
`register_payment`; essas exigem um membro humano do espaço.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from core import audit

from .models import ZERO, Bill, Payment, PaymentAllocation

S = Bill.Status


def _require_member(workspace, user):
    if user is None or not workspace.has_member(user):
        raise PermissionDenied('Usuário não é membro deste espaço.')


def _lock_bill(bill) -> Bill:
    return Bill.objects.select_for_update().get(pk=bill.pk)


@transaction.atomic
def submit_for_validation(bill, *, actor=None):
    """recebida → pendente_validacao. Pode ser feito pelo sistema/IA (actor=None)."""
    bill = _lock_bill(bill)
    if actor is not None:
        _require_member(bill.workspace, actor)
    if bill.status != S.RECEIVED:
        raise ValidationError(f'Só contas recebidas vão para validação (status: {bill.status}).')
    if bill.amount is None or bill.due_date is None:
        raise ValidationError('A conta precisa de valor e vencimento antes da validação.')
    bill.status = S.PENDING_VALIDATION
    bill.save(update_fields=['status'])
    audit.record(
        workspace=bill.workspace, actor=actor, action='bill.submitted', target=bill,
        changes={'status': [S.RECEIVED, S.PENDING_VALIDATION]},
    )
    return bill


@transaction.atomic
def approve_bill(bill, *, actor):
    """pendente_validacao → aprovada. Só um membro humano."""
    bill = _lock_bill(bill)
    _require_member(bill.workspace, actor)
    if bill.status != S.PENDING_VALIDATION:
        raise ValidationError(f'Só contas pendentes de validação podem ser aprovadas (status: {bill.status}).')
    bill.status = S.APPROVED
    bill.approved_by = actor
    bill.approved_at = timezone.now()
    bill.save(update_fields=['status', 'approved_by', 'approved_at'])
    audit.record(
        workspace=bill.workspace, actor=actor, action='bill.approved', target=bill,
        changes={'status': [S.PENDING_VALIDATION, S.APPROVED]},
    )
    return bill


@transaction.atomic
def cancel_bill(bill, *, actor, reason=''):
    """Qualquer status (exceto paga) → cancelada. Conta com pagamento parcial não é cancelada."""
    bill = _lock_bill(bill)
    _require_member(bill.workspace, actor)
    if bill.status in (S.PAID, S.CANCELLED):
        raise ValidationError(f'Conta {bill.get_status_display().lower()} não pode ser cancelada.')
    if bill.allocations.exists():
        raise ValidationError('Conta com pagamento registrado não pode ser cancelada.')
    previous = bill.status
    bill.status = S.CANCELLED
    bill.cancelled_by = actor
    bill.cancelled_at = timezone.now()
    bill.save(update_fields=['status', 'cancelled_by', 'cancelled_at'])
    audit.record(
        workspace=bill.workspace, actor=actor, action='bill.cancelled', target=bill,
        changes={'status': [previous, S.CANCELLED], 'reason': reason},
    )
    return bill


@dataclass(frozen=True)
class Allocation:
    bill: Bill
    amount: Decimal


@transaction.atomic
def register_payment(*, workspace, actor, paid_at, amount, method, allocations, receipt=None):
    """Registra um pagamento e distribui o valor entre contas aprovadas.

    Cobre pagamento parcial, um pagamento para várias contas e várias parcelas da mesma conta.
    A conta vira `paga` quando as alocações somam exatamente o valor dela.
    """
    _require_member(workspace, actor)
    amount = Decimal(amount)
    if amount <= ZERO:
        raise ValidationError('O valor do pagamento deve ser positivo.')
    if not allocations:
        raise ValidationError('Informe ao menos uma conta para o pagamento.')
    if receipt is not None and receipt.workspace_id != workspace.pk:
        raise ValidationError('Comprovante de outro espaço.')

    total = sum((Decimal(a.amount) for a in allocations), ZERO)
    if total > amount:
        raise ValidationError(f'As alocações ({total}) passam do valor do pagamento ({amount}).')

    # Trava as contas em ordem de id para evitar deadlock entre pagamentos simultâneos.
    bill_ids = sorted({a.bill.pk for a in allocations})
    locked = {b.pk: b for b in Bill.objects.select_for_update().filter(pk__in=bill_ids).order_by('pk')}

    requested: dict[int, Decimal] = {}
    for a in allocations:
        if Decimal(a.amount) <= ZERO:
            raise ValidationError('Cada alocação deve ter valor positivo.')
        requested[a.bill.pk] = requested.get(a.bill.pk, ZERO) + Decimal(a.amount)

    for bill_id, value in requested.items():
        bill = locked[bill_id]
        if bill.workspace_id != workspace.pk:
            raise ValidationError('Conta de outro espaço.')
        if bill.status != S.APPROVED:
            raise ValidationError(f'Só contas aprovadas podem ser pagas: "{bill.description}" está {bill.status}.')
        if value > bill.remaining_amount:
            raise ValidationError(
                f'Pagamento de {value} passa do que falta pagar em "{bill.description}" ({bill.remaining_amount}).'
            )

    payment = Payment.objects.create(
        workspace=workspace, paid_at=paid_at, amount=amount, method=method,
        receipt=receipt, registered_by=actor,
    )
    for a in allocations:
        PaymentAllocation.objects.create(payment=payment, bill=locked[a.bill.pk], amount=Decimal(a.amount))

    audit.record(
        workspace=workspace, actor=actor, action='payment.registered', target=payment,
        changes={
            'amount': str(amount),
            'allocations': [{'bill': a.bill.pk, 'amount': str(a.amount)} for a in allocations],
        },
    )

    for bill in locked.values():
        if bill.remaining_amount == ZERO:
            bill.status = S.PAID
            bill.save(update_fields=['status'])
            audit.record(
                workspace=workspace, actor=actor, action='bill.paid', target=bill,
                changes={'status': [S.APPROVED, S.PAID], 'payment': payment.pk},
            )
    return payment
