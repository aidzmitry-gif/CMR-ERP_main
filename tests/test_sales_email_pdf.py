import base64
from io import BytesIO

import pytest
from PIL import Image
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
    ("image_format", "mime_type"),
    [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")],
)
async def test_actual_pdf_preserves_embedded_raster_image(image_format, mime_type):
    image_data = BytesIO()
    Image.new("RGB", (8, 8), (30, 100, 180)).save(image_data, format=image_format)
    encoded = base64.b64encode(image_data.getvalue()).decode("ascii")
    source = SOURCE.replace(
        "</html>", f'<img src="data:{mime_type};base64,{encoded}" alt="Логотип"></html>',
    )
    content = await pdf(source)
    reader = PdfReader(BytesIO(content))
    assert len(reader.pages) == 1
    assert len(reader.pages[0].images) == 1
    assert reader.pages[0].images[0].image.size == (8, 8)


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
