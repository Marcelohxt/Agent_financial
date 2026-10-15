"""Validações determinísticas de documentos brasileiros e telefones.

Nada aqui depende de IA: são regras fixas, testadas, que decidem se um dado é aceito.
"""

import re

from django.core.exceptions import ValidationError

_PHONE_E164 = re.compile(r'^\+[1-9]\d{7,14}$')


def only_digits(value: str) -> str:
    return re.sub(r'\D', '', value or '')


def is_valid_cpf(value: str) -> bool:
    digits = only_digits(value)
    if len(digits) != 11 or digits == digits[0] * 11:
        return False
    for size in (9, 10):
        total = sum(int(d) * w for d, w in zip(digits[:size], range(size + 1, 1, -1)))
        check = (total * 10) % 11 % 10
        if check != int(digits[size]):
            return False
    return True


def is_valid_cnpj(value: str) -> bool:
    digits = only_digits(value)
    if len(digits) != 14 or digits == digits[0] * 14:
        return False
    weights_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    weights_2 = [6, *weights_1]
    for size, weights in ((12, weights_1), (13, weights_2)):
        total = sum(int(d) * w for d, w in zip(digits[:size], weights))
        remainder = total % 11
        check = 0 if remainder < 2 else 11 - remainder
        if check != int(digits[size]):
            return False
    return True


def validate_cpf(value: str) -> None:
    if not is_valid_cpf(value):
        raise ValidationError('CPF inválido.', code='invalid_cpf')


def validate_cnpj(value: str) -> None:
    if not is_valid_cnpj(value):
        raise ValidationError('CNPJ inválido.', code='invalid_cnpj')


def validate_phone_e164(value: str) -> None:
    if not _PHONE_E164.match(value or ''):
        raise ValidationError(
            'Telefone deve estar no formato internacional, ex.: +5511999998888.',
            code='invalid_phone',
        )
