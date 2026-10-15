import datetime
from decimal import Decimal

import pytest

from accounts.models import Membership, User, Workspace
from payables.models import Bill


@pytest.fixture(autouse=True)
def _media_tmp(settings, tmp_path):
    # PDFs dos testes vão para uma pasta temporária, nunca para media/ de verdade.
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def workspace(db):
    return Workspace.objects.create(name='Casa')


@pytest.fixture
def marcelo(workspace):
    user = User.objects.create_user('marcelo')
    Membership.objects.create(workspace=workspace, user=user, phone='+5511999990001')
    return user


@pytest.fixture
def parceira(workspace):
    user = User.objects.create_user('parceira')
    Membership.objects.create(workspace=workspace, user=user, phone='+5511999990002')
    return user


@pytest.fixture
def make_bill(workspace):
    def _make(amount='100.00', status=Bill.Status.RECEIVED, due=None, **kwargs):
        return Bill.objects.create(
            workspace=workspace,
            description=kwargs.pop('description', 'Conta teste'),
            amount=Decimal(amount) if amount is not None else None,
            due_date=due or datetime.date(2026, 10, 20),
            status=status,
            **kwargs,
        )

    return _make
