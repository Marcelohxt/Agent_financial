"""Processamento das notificações do webhook do WhatsApp Cloud API.

Formato da notificação (resumido):
    {"object": "whatsapp_business_account",
     "entry": [{"changes": [{"field": "messages",
                             "value": {"messages": [{"from": "5511...", "id": "wamid...",
                                                     "timestamp": "1760000000",
                                                     "type": "text", "text": {"body": "oi"}}]}}]}]}

Tudo que vem daqui é conteúdo externo, não confiável: só gravamos e identificamos o
remetente. Nada é aprovado ou pago a partir de uma mensagem sem as regras de `payables`.
"""

import datetime
import hashlib
import hmac
import logging

from django.db import IntegrityError, transaction

from accounts.models import Membership
from core.validators import only_digits

from .models import InboundMessage

logger = logging.getLogger(__name__)

MEDIA_TYPES = ('document', 'image')


def signature_is_valid(raw_body: bytes, header: str, app_secret: str) -> bool:
    """Confere o cabeçalho X-Hub-Signature-256 (HMAC-SHA256 do corpo com a chave do app)."""
    if not app_secret or not header or not header.startswith('sha256='):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix('sha256='))


def phone_candidates(wa_from: str) -> list[str]:
    """Telefones E.164 possíveis para o remetente.

    O WhatsApp às vezes envia celulares brasileiros antigos sem o nono dígito
    (55 + DDD + 8 dígitos). Nesse caso também tentamos a versão com o 9.
    """
    digits = only_digits(wa_from)
    candidates = [f'+{digits}']
    if digits.startswith('55') and len(digits) == 12 and digits[4] in '6789':
        candidates.append(f'+{digits[:4]}9{digits[4:]}')
    return candidates


def find_member(wa_from: str):
    return (
        Membership.objects.filter(
            phone__in=phone_candidates(wa_from),
            phone_verified_at__isnull=False,
            is_active=True,
        )
        .select_related('workspace', 'user')
        .first()
    )


def _iter_messages(payload: dict):
    for entry in payload.get('entry') or []:
        for change in entry.get('changes') or []:
            if change.get('field') != 'messages':
                continue
            yield from (change.get('value') or {}).get('messages') or []


def _store(message: dict):
    wa_id = message.get('id')
    wa_from = message.get('from')
    if not wa_id or not wa_from:
        logger.warning('Mensagem do WhatsApp sem id ou remetente; ignorada.')
        return None

    member = find_member(wa_from)
    kind = message.get('type', 'unknown')
    media = message.get(kind, {}) if kind in MEDIA_TYPES else {}
    try:
        sent_at = datetime.datetime.fromtimestamp(int(message.get('timestamp')), tz=datetime.UTC)
    except (TypeError, ValueError):
        sent_at = datetime.datetime.now(tz=datetime.UTC)

    try:
        with transaction.atomic():
            return InboundMessage.objects.create(
                wa_message_id=wa_id,
                from_phone=phone_candidates(wa_from)[0],
                membership=member,
                message_type=kind,
                text=(message.get('text') or {}).get('body', '') or media.get('caption', ''),
                media_id=media.get('id', ''),
                media_mime_type=media.get('mime_type', ''),
                media_filename=media.get('filename', ''),
                sent_at=sent_at,
                payload=message,
                status=(
                    InboundMessage.Status.ACCEPTED if member
                    else InboundMessage.Status.UNKNOWN_SENDER
                ),
            )
    except IntegrityError:
        # Mesma mensagem reenviada pela Meta: já foi gravada, não faz nada.
        logger.info('Mensagem %s repetida; ignorada.', wa_id)
        return None


def handle_notification(payload: dict) -> list[InboundMessage]:
    """Grava as mensagens novas da notificação e devolve só as que foram criadas agora."""
    created = []
    for message in _iter_messages(payload):
        stored = _store(message)
        if stored is not None:
            created.append(stored)
    return created
