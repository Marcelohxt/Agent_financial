from .models import AuditLog


def record(*, workspace, actor, action, target, changes=None):
    """Grava uma linha de auditoria para `target` (qualquer instância de modelo)."""
    return AuditLog.objects.create(
        workspace=workspace,
        actor=actor,
        action=action,
        target_type=target._meta.label_lower,
        target_id=str(target.pk),
        changes=changes or {},
    )
