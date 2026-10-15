from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class AuditLog(models.Model):
    """Registro de quem fez o quê e quando. Só aceita inserção."""

    workspace = models.ForeignKey(
        'accounts.Workspace', on_delete=models.PROTECT, related_name='audit_logs'
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text='Vazio quando a ação foi do sistema ou da IA.',
    )
    action = models.CharField(max_length=64)
    target_type = models.CharField(max_length=64)
    target_id = models.CharField(max_length=64)
    changes = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['target_type', 'target_id'])]

    def __str__(self):
        return f'{self.action} {self.target_type}#{self.target_id}'

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError('Registros de auditoria não podem ser alterados.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('Registros de auditoria não podem ser apagados.')
