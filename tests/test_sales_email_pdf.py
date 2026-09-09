from io import BytesIO

import pytest
from pypdf import PdfReader

from modules.sales.mail_pdf import pdf, render_original

SOURCE = """<!doctype html><html lang="ru"><meta charset="utf-8"><style>
@page {size:A4; margin:18mm} body {font-family:DejaVu Sans,Arial,sans-serif; font-size:11pt}
table {border-collapse:collapse;width:100%} td,th {border:1px solid #888;padding:6px}
</style><h1>Счёт № КОНТРОЛЬ-001</h1><p>Только синтетические данные для приёмки CRM</p>
<p>Покупатель: ООО «Контроль». Продавец: ООО «Тест».</p>
<table><tr><th>Наименование</th><th>Количество</th><th>Цена</th><th>Сумма</th></tr>
<tr><td>Аккумулятор тестовый</td><td>2</td><td>100,00</td><td>200,00</td></tr></table>
<p>НДС: 40,00 BYN</p><p>К оплате: 240,00 BYN</p></html>"""


async def test_actual_pdf_contains_cyrillic_and_frozen_values(tmp_path):
    content = await pdf(SOURCE)
    reader = PdfReader(BytesIO(content))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert "КОНТРОЛЬ-001" in text and "Аккумулятор тестовый" in text
    assert "240,00 BYN" in text
    (tmp_path / "invoice.pdf").write_bytes(content)


@pytest.mark.parametrize(
    "markup",
    [
        '<img src="file:///etc/passwd">',
        '<img src="http://127.0.0.1:8000/secrets">',
        '<style>@import url("https://evil.test/style");</style>',
        '<img src="data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=">',
        '<a href="https://evil.test/">Ссылка</a>',
        '<link rel="attachment" href="file:///etc/passwd">',
        "<script>alert(1)</script>",
        '<iframe src="file:///etc/passwd"></iframe>',
    ],
)
def test_pdf_rejects_external_resources_active_content_and_links(markup):
    with pytest.raises(Exception):
        render_original("<html>" + markup + "</html>")
