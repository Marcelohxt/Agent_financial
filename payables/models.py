import hashlib
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce

from core.validators import is_valid_cnpj, is_valid_cpf, only_digits

MONEY = {'max_digits': 14, 'decimal_places': 2}
ZERO = Decimal('0.00')


class Holder(models.Model):
    """Titular: em nome de quem a conta está (CPF ou CNPJ)."""

    class DocumentType(models.TextChoices):
        CPF = 'cpf', 'CPF'
        CNPJ = 'cnpj', 'CNPJ'

    workspace = models.ForeignKey(
        'accounts.Workspace', on_delete=models.PROTECT, related_name='holders'
    )
    name = models.CharField(max_length=120)
    document_type = models.CharField(max_length=4, choices=DocumentType.choices)
    document = models.CharField(max_length=14, help_text='Só dígitos.')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['workspace', 'document'], name='unique_holder_document'
            ),
        ]

    def __str__(self):
        return f'{self.name} ({self.get_document_type_display()})'

    def clean(self):
        valid = is_valid_cpf if self.document_type == self.DocumentType.CPF else is_valid_cnpj
        if not valid(self.document):
            raise ValidationError(
                {'document': f'{self.get_document_type_display()} inválido.'}
            )

    def save(self, *args, **kwargs):
        self.document = only_digits(self.document)
        self.full_clean()
        super().save(*args, **kwargs)


class Supplier(models.Model):
    """Fornecedor: quem cobra (Claro, Enel, condomínio...)."""

    workspace = models.ForeignKey(
        'accounts.Workspace', on_delete=models.PROTECT, related_name='suppliers'
    )
    name = models.CharField(max_length=120)
    document = models.CharField(max_length=14, blank=True, help_text='CNPJ/CPF, só dígitos.')

    def __str__(self):
        return self.name

    def clean(self):
        if self.document and not (is_valid_cpf(self.document) or is_valid_cnpj(self.document)):
            raise ValidationError({'document': 'CPF/CNPJ do fornecedor inválido.'})

    def save(self, *args, **kwargs):
        self.document = only_digits(self.document)
        self.full_clean()
        super().save(*args, **kwargs)


def _document_upload_to(instance, filename):
    return f'documents/{instance.workspace_id}/{instance.sha256}.pdf'


class Document(models.Model):
    """Arquivo recebido: boleto, fatura, comprovante. O hash impede duplicatas."""

    class Kind(models.TextChoices):
        BOLETO = 'boleto', 'Boleto'
        INVOICE = 'fatura', 'Fatura'
        RECEIPT = 'comprovante', 'Comprovante'
        OTHER = 'outro', 'Outro'

    class Source(models.TextChoices):
        UPLOAD = 'upload', 'Upload'
        WHATSAPP = 'whatsapp', 'WhatsApp'
        EMAIL = 'email', 'E-mail'
        DOWNLOAD = 'download', 'Download'

    workspace = models.ForeignKey(
        'accounts.Workspace', on_delete=models.PROTECT, related_name='documents'
    )
    kind = models.CharField(max_length=12, choices=Kind.choices)
    file = models.FileField(upload_to=_document_upload_to)
    sha256 = models.CharField(max_length=64, editable=False)
    source = models.CharField(max_length=10, choices=Source.choices)
    external_id = models.CharField(
        max_length=128, blank=True, help_text='Id da mensagem ou e-mail de origem.'
    )
    original_name = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True
    )
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['workspace', 'sha256'], name='unique_document_hash'),
            models.UniqueConstraint(
                fields=['workspace', 'source', 'external_id'],
                condition=~Q(external_id=''),
                name='unique_document_external_id',
            ),
        ]

    def __str__(self):
        return f'{self.get_kind_display()} {self.original_name or self.sha256[:8]}'

    @staticmethod
    def hash_file(file) -> str:
        digest = hashlib.sha256()
        file.seek(0)
        for chunk in file.chunks():
            digest.update(chunk)
        file.seek(0)
        return digest.hexdigest()

    def save(self, *args, **kwargs):
        if not self.sha256:
            self.sha256 = self.hash_file(self.file)
        super().save(*args, **kwargs)


class BillQuerySet(models.QuerySet):
    def with_paid_amount(self):
        return self.annotate(
            paid_total=Coalesce(Sum('allocations__amount'), ZERO, output_field=models.DecimalField(**MONEY))
        )

    def overdue(self, today):
        return self.filter(due_date__lt=today).exclude(
            status__in=[Bill.Status.PAID, Bill.Status.CANCELLED]
        )


class Bill(models.Model):
    """Conta a pagar. O status só muda pelas funções de `payables.services`."""

    class Status(models.TextChoices):
        RECEIVED = 'recebida', 'Recebida'
        PENDING_VALIDATION = 'pendente_validacao', 'Pendente de validação'
        APPROVED = 'aprovada', 'Aprovada'
        PAID = 'paga', 'Paga'
        CANCELLED = 'cancelada', 'Cancelada'

    class Origin(models.TextChoices):
        MANUAL = 'manual', 'Manual'
        AI = 'ia', 'Extraída por IA'

    workspace = models.ForeignKey('accounts.Workspace', on_delete=models.PROTECT, related_name='bills')
    holder = models.ForeignKey(Holder, on_delete=models.PROTECT, null=True, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, null=True, blank=True)
    description = models.CharField(max_length=255)
    amount = models.DecimalField(**MONEY, null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    barcode = models.CharField(max_length=60, blank=True, help_text='Linha digitável, só dígitos.')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RECEIVED)
    origin = models.CharField(max_length=6, choices=Origin.choices, default=Origin.MANUAL)
    documents = models.ManyToManyField(Document, blank=True, related_name='bills')

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+'
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)

    objects = BillQuerySet.as_manager()

    class Meta:
        ordering = ['due_date', 'id']
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__isnull=True) | Q(amount__gt=0), name='bill_amount_positive'
            ),
            models.UniqueConstraint(
                fields=['workspace', 'barcode'],
                condition=~Q(barcode=''),
                name='unique_bill_barcode',
            ),
            models.CheckConstraint(
                condition=~Q(status='aprovada') | Q(approved_by__isnull=False),
                name='approved_bill_has_approver',
            ),
        ]

    def __str__(self):
        return f'{self.description} ({self.get_status_display()})'

    @property
    def paid_amount(self) -> Decimal:
        return self.allocations.aggregate(total=Coalesce(Sum('amount'), ZERO))['total']

    @property
    def remaining_amount(self) -> Decimal:
        return (self.amount or ZERO) - self.paid_amount

    def is_overdue(self, today) -> bool:
        return (
            self.due_date is not None
            and self.due_date < today
            and self.status not in (self.Status.PAID, self.Status.CANCELLED)
        )

    def is_partially_paid(self) -> bool:
        return ZERO < self.paid_amount < (self.amount or ZERO)


class Payment(models.Model):
    """Dinheiro que saiu. As alocações dizem quais contas ele quitou."""

    class Method(models.TextChoices):
        PIX = 'pix', 'Pix'
        BOLETO = 'boleto', 'Boleto'
        DEBIT = 'debito', 'Débito'
        TRANSFER = 'transferencia', 'Transferência'
        OTHER = 'outro', 'Outro'

    workspace = models.ForeignKey(
        'accounts.Workspace', on_delete=models.PROTECT, related_name='payments'
    )
    paid_at = models.DateField()
    amount = models.DecimalField(**MONEY)
    method = models.CharField(max_length=14, choices=Method.choices)
    receipt = models.ForeignKey(
        Document, on_delete=models.PROTECT, null=True, blank=True, related_name='payments'
    )
    registered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-paid_at', '-id']
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name='payment_amount_positive'),
        ]

    def __str__(self):
        return f'Pagamento {self.amount} em {self.paid_at}'


class PaymentAllocation(models.Model):
    """Quanto de um pagamento foi para uma conta."""

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name='allocations')
    bill = models.ForeignKey(Bill, on_delete=models.PROTECT, related_name='allocations')
    amount = models.DecimalField(**MONEY)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name='allocation_amount_positive'),
        ]

    def __str__(self):
        return f'{self.amount} de {self.payment_id} para {self.bill_id}'
