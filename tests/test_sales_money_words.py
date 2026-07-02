"""Юнит-тест: сумма прописью (BYN) для печатной формы счёта (kind=invoice)."""
from decimal import Decimal

import pytest

from modules.sales._money_words import money_words

pytestmark = pytest.mark.unit


def test_money_words_matches_template_example():
    # пример из sales-invoice-template.html: 108.25 BYN, 1 шт
    assert money_words(Decimal("108.25")) == "Сто восемь рублей 25 копеек"


def test_money_words_singular_forms():
    assert money_words(Decimal("1.01")) == "Один рубль 01 копейка"


def test_money_words_few_forms():
    assert money_words(Decimal("2.22")) == "Два рубля 22 копейки"


def test_money_words_many_forms():
    assert money_words(Decimal("0.00")) == "Ноль рублей 00 копеек"


def test_money_words_thousands():
    assert money_words(Decimal("1360.00")) == "Одна тысяча триста шестьдесят рублей 00 копеек"


def test_money_words_rounds_to_kopecks():
    # округление до копеек с переносом в рубли (999.995 → 1000.00, не «...100 копеек»)
    assert money_words(Decimal("999.995")) == "Одна тысяча рублей 00 копеек"
