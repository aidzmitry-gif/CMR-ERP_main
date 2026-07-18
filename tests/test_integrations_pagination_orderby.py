"""Регрессия S5: каждый страничный OData-вызов к 1С несёт стабильный $orderby.

Без $orderby на файловой ИБ 1С постраничный $skip/$top не гарантирует порядок строк
между страницами → $skip пропускает/задваивает записи справочника (потеря/дубли
контрагентов, номенклатуры и цен при импорте). До фикса вызов регистра цен
`InformationRegister_ЦеныНоменклатуры` шёл без $orderby — этот тест ловил бы дрейф.
"""
from __future__ import annotations

from modules.integrations.client import OneCClient


def _capture_page_params(method_name: str) -> list[dict]:
    """Прогоняет sync-метод с перехваченным _get, возвращает параметры всех вызовов."""
    client = OneCClient(base_url="http://127.0.0.1:9/ka/odata")
    calls: list[dict] = []
    state = {"n": 0}

    def fake_get(entity: str, params: dict | None = None) -> list[dict]:
        calls.append(dict(params or {}))
        state["n"] += 1
        top = int((params or {}).get("$top", "0"))
        # Первая страница «полная» → цикл запросит вторую (там и проявился бы дрейф $skip);
        # вторая пустая — стоп. Пустые dict-строки безопасны: их отфильтруют по Code/Ref_Key.
        if state["n"] == 1 and top:
            return [{} for _ in range(top)]
        return []

    client._get = fake_get  # type: ignore[assignment]
    getattr(client, method_name)()
    return calls


def test_every_paged_call_has_stable_orderby():
    for method in ("_fetch_counterparties_sync", "_fetch_stock_sync"):
        for params in _capture_page_params(method):
            # Страничный вызов узнаём по $top — ровно он рискует пропуском/дублем без порядка.
            if "$top" in params:
                assert params.get("$orderby"), (
                    f"{method}: страничный вызов без $orderby — $skip/$top на файловой ИБ 1С "
                    f"пропустит/задвоит записи: {params}"
                )
