import hashlib
from sqlalchemy import select
from modules.accounting.financial_closing import canonical
from modules.accounting.models import Line
from modules.accounting.schemas import LineInput, PostingInput

def checksum(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

async def actual_posting(session, entry):
    body = {key: getattr(entry, key) for key in PostingInput.model_fields if key != 'lines'}
    lines = (await session.scalars(select(Line).where(Line.entry_id == entry.id).order_by(Line.id))).all()
    body['lines'] = [{'account': line.account_code, **{key: getattr(line, key) for key in LineInput.model_fields if key != 'account'}} for line in lines]
    return PostingInput.model_validate(body)
