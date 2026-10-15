import pytest
from django.core.exceptions import ValidationError

from core.validators import is_valid_cnpj, is_valid_cpf, validate_phone_e164


@pytest.mark.parametrize('cpf', ['529.982.247-25', '52998224725', '111.444.777-35'])
def test_cpf_valido(cpf):
    assert is_valid_cpf(cpf)


@pytest.mark.parametrize('cpf', ['529.982.247-24', '111.111.111-11', '123', ''])
def test_cpf_invalido(cpf):
    assert not is_valid_cpf(cpf)


@pytest.mark.parametrize('cnpj', ['11.222.333/0001-81', '11222333000181'])
def test_cnpj_valido(cnpj):
    assert is_valid_cnpj(cnpj)


@pytest.mark.parametrize('cnpj', ['11.222.333/0001-80', '00000000000000', '1122233300018'])
def test_cnpj_invalido(cnpj):
    assert not is_valid_cnpj(cnpj)


def test_telefone_e164():
    validate_phone_e164('+5511999998888')
    for invalido in ['11999998888', '+0511999998888', '+55 11 99999-8888']:
        with pytest.raises(ValidationError):
            validate_phone_e164(invalido)
