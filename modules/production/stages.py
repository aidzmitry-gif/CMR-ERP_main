"""Этапы канбана цеха (порядок списка = порядок колонок на доске)."""

STAGES: list[dict] = [
    {"id": "queue", "title": "Очередь (план)", "color": "#3B82F6"},
    {"id": "picking", "title": "Комплектация", "color": "#F97316"},
    {"id": "assembly", "title": "В производстве", "color": "#6366F1"},
    {"id": "qc", "title": "ОТК / Контроль", "color": "#06B6D4"},
    {"id": "packing", "title": "Упаковка", "color": "#14B8A6"},
    {"id": "done", "title": "Готово → склад", "color": "#22C55E"},
]
