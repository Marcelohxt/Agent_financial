from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models

from core.validators import validate_phone_e164


class User(AbstractUser):
    """Usuário do sistema.

    Por enquanto é igual ao usuário padrão do Django. Existe desde o início para
    que campos novos possam ser adicionados depois sem migração complicada.
    """


class Workspace(models.Model):
    """O controle financeiro compartilhado. Todos os dados financeiros pertencem a um espaço."""

    name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def has_member(self, user) -> bool:
        return self.memberships.filter(user=user, is_active=True).exists()


class Membership(models.Model):
    """Liga um usuário a um espaço e guarda o telefone usado no WhatsApp."""

    workspace = models.ForeignKey(Workspace, on_delete=models.PROTECT, related_name='memberships')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='memberships'
    )
    phone = models.CharField(
        max_length=16,
        unique=True,
        null=True,
        blank=True,
        validators=[validate_phone_e164],
        help_text='Formato E.164, ex.: +5511999998888.',
    )
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['workspace', 'user'], name='unique_membership'),
        ]

    def __str__(self):
        return f'{self.user} em {self.workspace}'
