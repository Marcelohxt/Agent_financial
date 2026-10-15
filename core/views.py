from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
@transaction.non_atomic_requests
def health(request):
    """Responde se a aplicação está no ar. Usado por monitoramento e testes.

    Não abre transação no banco: a verificação de saúde não deve depender dele.
    """
    return JsonResponse({'status': 'ok'})
