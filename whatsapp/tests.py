"""Testes do webhook com notificações simuladas no formato da Meta."""

import hashlib
import hmac
import json

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership
from whatsapp.inbound import phone_candidates, signature_is_valid
from whatsapp.models import InboundMessage

SECRET = 'segredo-de-teste'
URL = '/webhooks/whatsapp/'


@pytest.fixture(autouse=True)
def _whatsapp_settings(settings):
    settings.WHATSAPP_APP_SECRET = SECRET
    settings.WHATSAPP_VERIFY_TOKEN = 'verifica-123'


@pytest.fixture
def verificado(marcelo):
    Membership.objects.filter(user=marcelo).update(phone_verified_at=timezone.now())
    return marcelo


def notificacao(*mensagens):
    return {
        'object': 'whatsapp_business_account',
        'entry': [{
            'id': 'WABA_ID',
            'changes': [{
                'field': 'messages',
                'value': {
                    'messaging_product': 'whatsapp',
                    'metadata': {'phone_number_id': 'PHONE_ID'},
                    'messages': list(mensagens),
                },
            }],
        }],
    }


def texto(wa_id='wamid.A', de='5511999990001', corpo='oi'):
    return {'from': de, 'id': wa_id, 'timestamp': '1760550000', 'type': 'text',
            'text': {'body': corpo}}


def pdf(wa_id='wamid.PDF', de='5511999990001'):
    return {'from': de, 'id': wa_id, 'timestamp': '1760550000', 'type': 'document',
            'document': {'id': 'MEDIA_1', 'mime_type': 'application/pdf',
                         'filename': 'claro-outubro.pdf', 'caption': 'conta da claro'}}


def enviar(client, payload, secret=SECRET):
    body = json.dumps(payload).encode()
    sig = 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(URL, data=body, content_type='application/json',
                       HTTP_X_HUB_SIGNATURE_256=sig)


# --- Cadastro do webhook (GET) --------------------------------------------------

def test_verificacao_devolve_challenge(client):
    r = client.get(URL, {'hub.mode': 'subscribe', 'hub.verify_token': 'verifica-123',
                         'hub.challenge': '42'})
    assert r.status_code == 200
    assert r.content == b'42'


def test_verificacao_recusa_token_errado(client):
    r = client.get(URL, {'hub.mode': 'subscribe', 'hub.verify_token': 'errado',
                         'hub.challenge': '42'})
    assert r.status_code == 403


# --- Assinatura ---------------------------------------------------------------------

def test_recusa_sem_assinatura(client, db):
    r = client.post(URL, data=json.dumps(notificacao(texto())), content_type='application/json')
    assert r.status_code == 403
    assert not InboundMessage.objects.exists()


def test_recusa_assinatura_de_outra_chave(client, db):
    assert enviar(client, notificacao(texto()), secret='chave-falsa').status_code == 403
    assert not InboundMessage.objects.exists()


def test_sem_chave_configurada_recusa_tudo(client, db, settings):
    settings.WHATSAPP_APP_SECRET = ''
    assert enviar(client, notificacao(texto()), secret='').status_code == 403


def test_assinatura_confere_o_corpo_exato():
    body = b'{"a":1}'
    sig = 'sha256=' + hmac.new(b'k', body, hashlib.sha256).hexdigest()
    assert signature_is_valid(body, sig, 'k')
    assert not signature_is_valid(b'{"a":2}', sig, 'k')


# --- Recebimento ----------------------------------------------------------------------

def test_mensagem_de_membro_verificado_e_aceita(client, verificado):
    assert enviar(client, notificacao(texto(corpo='paguei a luz'))).status_code == 200
    msg = InboundMessage.objects.get()
    assert msg.status == InboundMessage.Status.ACCEPTED
    assert msg.membership.user == verificado
    assert msg.text == 'paguei a luz'
    assert msg.from_phone == '+5511999990001'


def test_pdf_guarda_dados_do_anexo(client, verificado):
    enviar(client, notificacao(pdf()))
    msg = InboundMessage.objects.get()
    assert msg.message_type == 'document'
    assert msg.media_id == 'MEDIA_1'
    assert msg.media_filename == 'claro-outubro.pdf'
    assert msg.text == 'conta da claro'


def test_telefone_desconhecido_e_gravado_mas_nao_aceito(client, verificado):
    enviar(client, notificacao(texto(de='5521988887777')))
    msg = InboundMessage.objects.get()
    assert msg.status == InboundMessage.Status.UNKNOWN_SENDER
    assert msg.membership is None


def test_telefone_nao_verificado_nao_e_aceito(client, marcelo):
    enviar(client, notificacao(texto()))
    assert InboundMessage.objects.get().status == InboundMessage.Status.UNKNOWN_SENDER


def test_mensagem_repetida_pela_meta_e_ignorada(client, verificado):
    enviar(client, notificacao(texto()))
    r = enviar(client, notificacao(texto()))
    assert r.status_code == 200
    assert InboundMessage.objects.count() == 1


def test_varias_mensagens_na_mesma_notificacao(client, verificado):
    enviar(client, notificacao(texto('wamid.1'), texto('wamid.2'), pdf('wamid.3')))
    assert InboundMessage.objects.count() == 3


def test_notificacao_de_status_nao_cria_mensagem(client, db):
    payload = notificacao()
    payload['entry'][0]['changes'][0]['value'] = {'statuses': [{'id': 'wamid.X', 'status': 'read'}]}
    assert enviar(client, payload).status_code == 200
    assert not InboundMessage.objects.exists()


def test_json_invalido(client, db):
    body = b'nao e json'
    sig = 'sha256=' + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    r = client.post(URL, data=body, content_type='application/json', HTTP_X_HUB_SIGNATURE_256=sig)
    assert r.status_code == 400


# --- Telefone brasileiro sem o nono dígito ----------------------------------------------

def test_celular_antigo_sem_nono_digito():
    assert phone_candidates('551199990001') == ['+551199990001', '+5511999990001']
    assert phone_candidates('5511999990001') == ['+5511999990001']


def test_reconhece_membro_quando_whatsapp_omite_o_nove(client, verificado):
    enviar(client, notificacao(texto(de='551199990001')))
    assert InboundMessage.objects.get().membership.user == verificado


def test_rota_tem_nome():
    assert reverse('whatsapp-webhook') == URL
