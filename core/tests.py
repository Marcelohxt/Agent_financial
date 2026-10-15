from django.urls import reverse


def test_health_responde_ok(client):
    response = client.get(reverse('health'))

    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


def test_health_recusa_post(client):
    response = client.post(reverse('health'))

    assert response.status_code == 405
