from django.db import models


class InboundMessage(models.Model):
    """Toda mensagem que chega pelo webhook, aceita ou não.

    O id da mensagem do WhatsApp (`wa_message_id`) é único: se a Meta reenviar a mesma
    notificação, ela é reconhecida e ignorada.
    """

    class Status(models.TextChoices):
        ACCEPTED = 'aceita', 'Aceita'
        UNKNOWN_SENDER = 'remetente_desconhecido', 'Remetente desconhecido'

    wa_message_id = models.CharField(max_length=128, unique=True)
    from_phone = models.CharField(max_length=16, help_text='Formato E.164.')
    membership = models.ForeignKey(
        'accounts.Membership', on_delete=models.PROTECT, null=True, blank=True,
        related_name='inbound_messages',
    )
    message_type = models.CharField(max_length=20)
    text = models.TextField(blank=True)
    media_id = models.CharField(max_length=128, blank=True, help_text='Id do anexo na Meta.')
    media_mime_type = models.CharField(max_length=100, blank=True)
    media_filename = models.CharField(max_length=255, blank=True)
    sent_at = models.DateTimeField()
    payload = models.JSONField(help_text='Mensagem original, para auditoria.')
    status = models.CharField(max_length=24, choices=Status.choices)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-received_at']

    def __str__(self):
        return f'{self.message_type} de {self.from_phone} ({self.get_status_display()})'
