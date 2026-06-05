"""Стадии воронки офис-менеджера (документы по сделкам)."""

STAGES: list[dict] = [
    {"id": "ready", "title": "Готово к отгрузке", "color": "#3B82F6"},
    {"id": "shipped", "title": "Отгружено", "color": "#8B5CF6"},
    {"id": "docs", "title": "Сбор документов", "color": "#F59E0B"},
    {"id": "await_pay", "title": "Ожидают оплаты", "color": "#14B8A6"},
    {"id": "paid", "title": "Оплачено", "color": "#22C55E"},
]
