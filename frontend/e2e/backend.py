"""Dedicated E2E-only application: synthetic SQLite and no background integrations."""
import asyncio
import ipaddress
import json
import os
import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

# Test-only egress guard: retain Docker loopback publication while denying every
# application-initiated non-loopback TCP connection and external DNS lookup.
_connect, _connect_ex, _getaddrinfo = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

def local_host(host):
    if host in (None, 'localhost', '0.0.0.0', '::'):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False

def check_address(address):
    if isinstance(address, tuple) and not local_host(address[0]):
        raise OSError('E2E forbids external network connections')

def connect(sock, address):
    check_address(address)
    return _connect(sock, address)

def connect_ex(sock, address):
    check_address(address)
    return _connect_ex(sock, address)

def getaddrinfo(host, *args, **kwargs):
    if not local_host(host):
        raise OSError('E2E forbids external DNS')
    return _getaddrinfo(host, *args, **kwargs)

socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = connect, connect_ex, getaddrinfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
test_directory = TemporaryDirectory(prefix='crm-playwright-')
database_path = Path(test_directory.name) / 'synthetic.db'
# The invoice seeder runs in a separate process; an explicit dedicated path
# lets both processes use the same synthetic database.
if os.environ.get('E2E_SQLITE_PATH'):
    candidate = Path(os.environ['E2E_SQLITE_PATH']).resolve()
    expected = Path(__file__).resolve().parents[2] / 'e2e.db'
    if candidate != expected or candidate.exists():
        raise RuntimeError('E2E_SQLITE_PATH must be a new workspace e2e.db')
    database_path = candidate
os.environ.update(AIOS_ENVIRONMENT='dev', AIOS_AUTH_MODE='dev',
                  AIOS_DATABASE_URL=f'sqlite+aiosqlite:///{database_path.as_posix()}',
                  AIOS_SALES_EMAIL_ENABLED='false', AIOS_AI_ENABLED='false',
                  AIOS_SMTP_HOST='127.0.0.1', AIOS_SMTP_FROM='crm@example.test', AIOS_SMTP_TLS='false')
# Settings and the egress guard must be installed before application imports.
from config.access import USERS  # noqa: E402
from core.domain.models import Counterparty, Sku, User  # noqa: E402
from core.runtime.app import create_app  # noqa: E402
from modules.integrations.models import StockItem  # noqa: E402
from modules.sales.models import PriceQuote  # noqa: E402

USERS.extend([
    {'username':'e2e_owner', 'full_name':'Контрольный менеджер E2E', 'role':'sales'},
    {'username':'e2e_foreign', 'full_name':'Чужой менеджер E2E', 'role':'sales'},
])

app = create_app()
db = app.state.core.services.db

@asynccontextmanager
async def lifespan(_app):
    await db.connect()
    yield
    await db.disconnect()

app.router.lifespan_context = lifespan

@app.get('/__e2e_isolation')
def isolation():
    return {'chain': 'CRM-READY-001-H04-E2E', 'synthetic_only': True,
            'background_workers': False, 'email_enabled': False, 'egress_guard': True}

async def seed():
    marker = Path(test_directory.name) / 'seed.json'
    if marker.exists():
        return
    await db.connect()
    async with db.session_factory() as session:
        buyer = Counterparty(name='Контроль E2E — синтетический покупатель', unp='123456789')
        stocked = Sku(code='QA-STOCK', title='Контрольный аккумулятор — в наличии', unit='шт')
        ordered = Sku(code='QA-ORDER', title='Контрольный аккумулятор — под заказ', unit='шт')
        owner = User(username='e2e_owner', full_name='Контрольный менеджер E2E', employee_id=2901,
                     department='Продажи', role='sales', status='active', deal_visibility='own')
        foreign = User(username='e2e_foreign', full_name='Чужой менеджер E2E', employee_id=2902,
                       department='Продажи', role='sales', status='active', deal_visibility='own')
        session.add_all([buyer, stocked, ordered, owner, foreign])
        await session.flush()
        session.add_all([StockItem(sku_code=stocked.code, qty_available=10, qty_reserved=0),
                         StockItem(sku_code=ordered.code, qty_available=0, qty_reserved=0),
                         PriceQuote(sku_code=ordered.code, counterparty=buyer.name, price=150)])
        await session.commit()
        marker.write_text(json.dumps({'synthetic_only': True, 'order_sku_id': ordered.id,
                                     'stock_sku_id': stocked.id, 'owner_employee_id': 2901}))
    await db.disconnect()

if __name__ == '__main__':
    import uvicorn
    bind_host = os.environ.get('E2E_BIND_HOST', '127.0.0.1')
    if bind_host not in ('127.0.0.1', '0.0.0.0'):
        raise ValueError('Unsupported E2E bind address')
    asyncio.run(seed())
    uvicorn.run(app, host=bind_host, port=8000)
