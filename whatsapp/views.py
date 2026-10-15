import hmac
import json
import logging

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .inbound import handle_notification, signature_is_valid

logger = logging.getLogger(__name__)


@csrf_exempt  # a Meta não envia token CSRF; a autenticação é a assinatura HMAC
@require_http_methods(['GET', 'POST'])
@transaction.non_atomic_requests
def webhook(request):
    if request.method == 'GET':
        return _verify_subscription(request)
    return _receive(request)


def _verify_subscription(request):
    """Etapa de cadastro do webhook no painel da Meta: devolve o `hub.challenge`."""
    expected = settings.WHATSAPP_VERIFY_TOKEN
    token = request.GET.get('hub.verify_token', '')
    if (
        request.GET.get('hub.mode') == 'subscribe'
        and expected
        and hmac.compare_digest(token, expected)
    ):
        return HttpResponse(request.GET.get('hub.challenge', ''), content_type='text/plain')
    return HttpResponseForbidden('Token de verificação inválido.')


def _receive(request):
    signature = request.headers.get('X-Hub-Signature-256', '')
    if not signature_is_valid(request.body, signature, settings.WHATSAPP_APP_SECRET):
        logger.warning('Webhook do WhatsApp com assinatura inválida; recusado.')
        return HttpResponseForbidden('Assinatura inválida.')
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest('JSON inválido.')

    handle_notification(payload)
    # Responder 200 rápido: senão a Meta reenvia a notificação.
    return HttpResponse(status=200)
