"""Durable source identity guards; full posting body correspondence is separate."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from modules.accounting import service
from tests.accounting.test_postgres import pg_book, pg_factory  # noqa: F401


async def test_inbox_identity_and_source_resolution(pg_factory, pg_book, posting):  # noqa: F811
    async with pg_factory() as session:
        payload = posting(source='queued').model_dump(mode='json')
        await service.receive(session, pg_book[0], 'event-queued', '2026-09', payload)
        await session.commit()
        wrong = await service.post(session, pg_book[0], posting(source='other-document'), 'tester')
        await session.commit()
        with pytest.raises(DBAPIError, match='matching source entry'):
            await session.execute(text('UPDATE accounting.inbox SET entry_id=:entry'), {'entry': wrong.id})
        await session.rollback()
        for sql, error in [
            ("UPDATE accounting.inbox SET event_key='replacement'", 'identity is immutable'),
            ("UPDATE accounting.inbox SET month='2026-10'", 'identity is immutable'),
            ("UPDATE accounting.inbox SET payload='{}'", 'identity is immutable'),
            ('DELETE FROM accounting.inbox', 'immutable'),
            ('TRUNCATE accounting.inbox', 'immutable'),
        ]:
            with pytest.raises(DBAPIError, match=error):
                async with session.begin_nested():
                    await session.execute(text(sql))
        inbox_id = await session.scalar(text('SELECT id FROM accounting.inbox'))
        entry = await service.confirm_inbox(session, pg_book[0], inbox_id, 'tester')
        await session.commit()
        entry_id = entry.id
        assert (await service.confirm_inbox(session, pg_book[0], inbox_id, 'tester')).id == entry_id
        await session.commit()
        with pytest.raises(DBAPIError, match='Resolved inbox is immutable'):
            await session.execute(text('UPDATE accounting.inbox SET entry_id=NULL'))
        await session.rollback()
        assert await session.scalar(text('SELECT entry_id FROM accounting.inbox')) == entry_id
        assert await session.scalar(text('SELECT count(*) FROM accounting.entry')) == 2
        with pytest.raises(DBAPIError, match='Inbox must start pending'):
            await session.execute(text("""INSERT INTO accounting.inbox
                (organization_id,event_key,month,payload,entry_id)
                SELECT organization_id,'forged-resolved',month,payload,entry_id FROM accounting.inbox"""))
        await session.rollback()
        # Invalid posting content remains a durable pending error, not a lost event.
        invalid = await service.receive(session, pg_book[0], 'invalid-event', '2026-09', {'invalid': True})
        assert invalid.error and invalid.entry_id is None
        await session.commit()


@pytest.mark.parametrize('field', ['amount', 'dimensions', 'explanation'])
async def test_inbox_cannot_resolve_different_posting_body(pg_factory, pg_book, posting, field):  # noqa: F811
    async with pg_factory() as session:
        data = posting(source='body-check')
        entry = await service.post(session, pg_book[0], data, 'tester')
        await session.commit()
        entry_id = entry.id
        payload = data.model_dump(mode='json')
        if field == 'amount':
            for line in payload['lines']:
                line['amount'] = '101.00'
        elif field == 'dimensions':
            payload['lines'][0]['dimensions'] = {'department': 'different'}
        else:
            payload['explanation'] = 'A different economic justification'
        await service.receive(session, pg_book[0], 'different-body', '2026-09', payload)
        await session.commit()
        with pytest.raises(DBAPIError, match='posting body'):
            await session.execute(text('UPDATE accounting.inbox SET entry_id=:entry,error=NULL'), {'entry': entry_id})
            await session.commit()
        await session.rollback()
        assert await session.scalar(text('SELECT entry_id FROM accounting.inbox')) is None


@pytest.mark.parametrize('source_version', ['1.0', True])
async def test_inbox_normalization_and_late_lines(pg_factory, pg_book, posting, source_version):  # noqa: F811
    async with pg_factory() as session:
        assert await session.scalar(text('SELECT accounting.posting_text(:value)'), {'value': '\vrev\v'}) == 'rev'
        payload = posting(source='normalized').model_dump(mode='json')
        payload['source'] = '\t normalized\n'
        payload['source_version'] = source_version
        payload.pop('opening')
        payload.pop('correction_of')
        payload['lines'][0]['amount'] = '100.0'
        payload['lines'][1]['amount'] = '100'
        payload['lines'][0]['dimensions'] = {' department ': ' value '}
        row = await service.receive(session, pg_book[0], 'normalized-event', '2026-09', payload)
        assert row.error is None
        await session.commit()
        inbox_id = row.id
        entry = await service.confirm_inbox(session, pg_book[0], inbox_id, 'tester')
        await session.flush()
        await session.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
        with pytest.raises(DBAPIError, match='posting body cannot receive additional lines'):
            async with session.begin_nested():
                await session.execute(text("""INSERT INTO accounting.line
                    (entry_id,account_id,account_code,account_title,category,cash,side,amount,dimensions,currency)
                    SELECT entry_id,account_id,account_code,account_title,category,cash,side,amount,dimensions,currency
                    FROM accounting.line WHERE entry_id=:entry"""), {'entry': entry.id})
        await session.commit()
        replay = await service.receive(session, pg_book[0], 'normalized-event', '2026-09', payload)
        assert replay.id == inbox_id and replay.payload == payload
        assert await session.scalar(text('SELECT count(*) FROM accounting.line')) == 2


async def test_inbox_preserves_raw_number_types(pg_factory, pg_book, posting):  # noqa: F811
    async with pg_factory() as session:
        payload = posting(source='integer-money').model_dump(mode='json')
        for line in payload['lines']:
            line['amount'] = 100
        row = await service.receive(session, pg_book[0], 'integer-event', '2026-09', payload)
        await session.commit()
        entry = await service.confirm_inbox(session, pg_book[0], row.id, 'tester')
        await session.commit()
        entry_id = entry.id
        with pytest.raises(DBAPIError, match='Inbox source identity is immutable'):
            await session.execute(text("""UPDATE accounting.inbox SET payload=
                jsonb_set(jsonb_set(payload::jsonb,'{lines,0,amount}','100.0'::jsonb),
                    '{lines,1,amount}','100.0'::jsonb)::json"""))
        await session.rollback()
        assert isinstance((await session.scalar(text('SELECT payload FROM accounting.inbox')))['lines'][0]['amount'], int)
        for line in payload['lines']:
            line['amount'] = 100.0
        pending = await service.receive(session, pg_book[0], 'float-event', '2026-09', payload)
        assert pending.error
        await session.commit()
        pending_id = pending.id
        with pytest.raises(DBAPIError, match='posting body requires exact decimal'):
            await session.execute(text('UPDATE accounting.inbox SET entry_id=:entry,error=NULL WHERE id=:id'),
                                  {'entry': entry_id, 'id': pending_id})
        await session.rollback()
        assert await session.scalar(text('SELECT entry_id FROM accounting.inbox WHERE id=:id'), {'id': pending_id}) is None


@pytest.mark.parametrize('field', ['dimensions', 'explanation'])
async def test_inbox_does_not_normalize_stored_ledger_text(pg_factory, pg_book, posting, field):  # noqa: F811
    async with pg_factory() as session:
        valid = posting(source='stored-text')
        valid.lines[0].dimensions = {'department': 'value'}
        payload = valid.model_dump(mode='json')
        # Simulate a producer bypassing DTO normalization before ledger insertion.
        if field == 'dimensions':
            lines = [valid.lines[0].model_copy(update={'dimensions': {'department': ' value '}}), valid.lines[1]]
            forged = valid.model_copy(update={'lines': lines})
        else:
            forged = valid.model_copy(update={'explanation': ' ' + valid.explanation + ' '})
        entry = await service.post(session, pg_book[0], forged, 'tester')
        await session.commit()
        entry_id = entry.id
        await service.receive(session, pg_book[0], 'stored-text-event', '2026-09', payload)
        await session.commit()
        with pytest.raises(DBAPIError, match='posting body'):
            await session.execute(text('UPDATE accounting.inbox SET entry_id=:entry,error=NULL'), {'entry': entry_id})
            await session.commit()
        await session.rollback()
        assert await session.scalar(text('SELECT entry_id FROM accounting.inbox')) is None


@pytest.mark.parametrize('field', ['side', 'cash_activity'])
async def test_inbox_rejects_whitespace_in_literal_fields(pg_factory, pg_book, posting, field):  # noqa: F811
    async with pg_factory() as session:
        data = posting(source='literal-fields', debit='51')
        entry = await service.post(session, pg_book[0], data, 'tester')
        await session.commit()
        entry_id = entry.id
        payload = data.model_dump(mode='json')
        payload['lines'][0][field] = ' ' + payload['lines'][0][field] + ' '
        row = await service.receive(session, pg_book[0], 'literal-event', '2026-09', payload)
        assert row.error
        await session.commit()
        with pytest.raises(DBAPIError, match='posting body'):
            await session.execute(text('UPDATE accounting.inbox SET entry_id=:entry,error=NULL'), {'entry': entry_id})
            await session.commit()
        await session.rollback()
        assert await session.scalar(text('SELECT entry_id FROM accounting.inbox')) is None


async def test_inbox_decimal_model_matches_python(pg_factory):  # noqa: F811
    import json
    from decimal import Decimal

    async with pg_factory() as session:
        for value in ['100', '100.0', '100.00', '+001.00', '.50', '1.', '1e2', '1.00e2',
                      '1.00e3', '0E7', '-0', '-0.00', '0.0000001', '1_00.0',
                      '1.230000', '100000000000000000.00', 100, 0, -10]:
            rendered = await session.scalar(text('SELECT accounting.inbox_decimal_model(CAST(:value AS json))'),
                                            {'value': json.dumps(value)})
            assert rendered == str(Decimal(value)), (value, rendered, str(Decimal(value)))


async def test_inbox_preserves_existing_scale_sensitive_replay(pg_factory, pg_book, posting):  # noqa: F811
    async with pg_factory() as session:
        data = posting(source='scale-replay', amount='100.00')
        entry = await service.post(session, pg_book[0], data, 'tester')
        await session.commit()
        entry_id = entry.id
        payload = posting(source='scale-replay', amount='100.0').model_dump(mode='json')
        row = await service.receive(session, pg_book[0], 'scale-event', '2026-09', payload)
        assert row.error  # Existing application replay contract rejects changed serialization.
        await session.commit()
        with pytest.raises(DBAPIError, match='replay digest'):
            await session.execute(text('UPDATE accounting.inbox SET entry_id=:entry,error=NULL'), {'entry': entry_id})
        await session.rollback()
        assert await session.scalar(text('SELECT entry_id FROM accounting.inbox')) is None
        exact = await service.receive(session, pg_book[0], 'exact-scale-event', '2026-09', data.model_dump(mode='json'))
        await session.commit()
        assert (await service.confirm_inbox(session, pg_book[0], exact.id, 'tester')).id == entry_id
        await session.commit()
        assert await session.scalar(text('SELECT count(*) FROM accounting.entry')) == 1


async def test_inbox_replay_model_and_digest_match_application(pg_factory, posting):  # noqa: F811
    import copy
    import json

    from modules.accounting.schemas import PostingInput

    raw = posting().model_dump(mode='json')
    variants = [raw]
    scientific = copy.deepcopy(raw)
    scientific['source_version'] = '1.0'
    scientific['policy_id'] = '1.0'
    scientific.pop('opening')
    scientific.pop('correction_of')
    for line in scientific['lines']:
        line['amount'] = '1.00e2'
    variants.append(scientific)
    separated = copy.deepcopy(raw)
    for line in separated['lines']:
        line['amount'] = '1_00.0'
    variants.append(separated)
    boolean_integer = copy.deepcopy(raw)
    boolean_integer['source_version'] = True
    variants.append(boolean_integer)
    epoch_dates = copy.deepcopy(raw)
    epoch_dates.update(document_date=1788220800, operation_date=1788220800000,
                       posting_date='2026-09-01T00:00:00+03:00')
    variants.append(epoch_dates)
    foreign = copy.deepcopy(raw)
    for line in foreign['lines']:
        line.update(currency='USD', original_amount='31.250', rate='3.2000', rate_scale='1.0',
                    rate_date='2026-09-01', rate_source=' Synthetic source ')
    variants.append(foreign)
    unicode = copy.deepcopy(raw)
    unicode['explanation'] = '\tПроверка 🙂\n'
    unicode['lines'][0]['dimensions'] = {' подразделение ': '\tЦех 1\n'}
    variants.append(unicode)
    controls = copy.deepcopy(raw)
    controls['source'] = '\u001csource\u001f'
    controls['explanation'] = '\u001ctext\u001f'
    variants.append(controls)
    async with pg_factory() as session:
        for candidate in variants:
            expected = PostingInput.model_validate(candidate)
            body = json.dumps(candidate, ensure_ascii=False)
            actual = await session.scalar(text('SELECT accounting.inbox_replay_model(CAST(:body AS json))'), {'body': body})
            assert actual == expected.model_dump(mode='json')
            checksum = await session.scalar(text('SELECT accounting.financial_sha(accounting.inbox_replay_model(CAST(:body AS json)))'), {'body': body})
            assert checksum == service.digest(expected)


async def test_inbox_dates_match_installed_oracle(pg_factory):  # noqa: F811
    import json
    from datetime import date

    from pydantic import TypeAdapter

    values = ['2026-09-01', '2026-09-01T00:00:00', '2026-09-01T00:00:00+03:00',
              '2026-09-01T00:00', '2026-09-01 00:00:00', '2026-09-01T00:00:00+0300',
              '2026-09-01T00:00:00.0000009', '2026-09-01T00:00:00,000',
              1788220800, 1788220800000, '1788220800', '+1788220800', 0.0000001,
              '2026-09-01T01:00:00', '2026-09-01T00:00:00.0000010', True,
              '09/01/2026', ' 2026-09-01 ', '2026-02-30', '0000-01-01', '1e9',
              0.0000005, -0.0000001]
    oracle = TypeAdapter(date)
    async with pg_factory() as session:
        for style, zone in [('ISO, MDY', 'UTC'), ('SQL, DMY', 'Pacific/Honolulu')]:
            await session.execute(text('SELECT set_config(:key,:value,true)'), {'key': 'DateStyle', 'value': style})
            await session.execute(text('SELECT set_config(:key,:value,true)'), {'key': 'TimeZone', 'value': zone})
            for value in values:
                try:
                    expected = oracle.validate_python(value).isoformat()
                except ValueError:
                    with pytest.raises(DBAPIError):
                        async with session.begin_nested():
                            await session.scalar(text('SELECT accounting.posting_date_value(CAST(:value AS jsonb))'), {'value': json.dumps(value)})
                else:
                    actual = await session.scalar(text('SELECT accounting.posting_date_value(CAST(:value AS jsonb))'), {'value': json.dumps(value)})
                    assert actual == expected, (value, actual, expected, style, zone)


async def test_inbox_epoch_and_midnight_dates_resolve(pg_factory, pg_book, posting):  # noqa: F811
    async with pg_factory() as session:
        payload = posting(source='epoch-posting').model_dump(mode='json')
        payload.update(document_date=1788220800, operation_date=1788220800000,
                       posting_date='2026-09-01T00:00:00+03:00')
        row = await service.receive(session, pg_book[0], 'epoch-event', '2026-09', payload)
        assert row.error is None
        await session.commit()
        inbox_id = row.id
        entry = await service.confirm_inbox(session, pg_book[0], inbox_id, 'tester')
        await session.commit()
        assert entry.document_date.isoformat() == entry.operation_date.isoformat() == entry.posting_date.isoformat() == '2026-09-01'
        assert (await service.receive(session, pg_book[0], 'epoch-event', '2026-09', payload)).payload == payload
        assert (await service.confirm_inbox(session, pg_book[0], inbox_id, 'tester')).id == entry.id


@pytest.mark.parametrize('field', ['source', 'explanation', 'account', 'dimension', 'opening', 'source_version'])
async def test_inbox_rejects_invalid_raw_types(pg_factory, pg_book, posting, field):  # noqa: F811
    async with pg_factory() as session:
        data = posting(source='123', explanation='123', opening=True)
        data.lines[0].dimensions = {'department': '123'}
        entry = await service.post(session, pg_book[0], data, 'tester')
        await session.commit()
        entry_id = entry.id
        payload = data.model_dump(mode='json')
        if field in {'source', 'explanation'}:
            payload[field] = 123
        elif field == 'account':
            payload['lines'][0]['account'] = 41
        elif field == 'dimension':
            payload['lines'][0]['dimensions']['department'] = 123
        elif field == 'source_version':
            payload['source_version'] = '1e0'
        else:
            payload['opening'] = 'tr'  # PostgreSQL accepts a prefix; Pydantic does not.
        row = await service.receive(session, pg_book[0], 'invalid-type-event', '2026-09', payload)
        assert row.error
        await session.commit()
        with pytest.raises(DBAPIError, match='posting body|integer model'):
            await session.execute(text('UPDATE accounting.inbox SET entry_id=:entry,error=NULL'), {'entry': entry_id})
            await session.commit()
        await session.rollback()
        assert await session.scalar(text('SELECT entry_id FROM accounting.inbox')) is None


async def test_inbox_shape_rejects_schema_invalid_objects(pg_factory, posting):  # noqa: F811
    import copy
    import json

    from pydantic import ValidationError

    from modules.accounting.schemas import PostingInput

    base = posting().model_dump(mode='json')
    candidates = []
    for field, value in [('source', ''), ('source', 'x' * 161), ('opening', None),
                         ('unexpected', 1), ('lines', [])]:
        candidate = copy.deepcopy(base)
        candidate[field] = value
        candidates.append(candidate)
    for field, value in [('account', '41x'), ('currency', 'usd'), ('rate_source', 'x' * 201),
                         ('dimensions', None), ('dimensions', {'department': ''}), ('unexpected', 1)]:
        candidate = copy.deepcopy(base)
        candidate['lines'][0][field] = value
        candidates.append(candidate)
    async with pg_factory() as session:
        for candidate in candidates:
            with pytest.raises(ValidationError):
                PostingInput.model_validate(candidate)
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.scalar(text('SELECT accounting.inbox_replay_model(CAST(:body AS json))'),
                                         {'body': json.dumps(candidate)})


async def test_inbox_required_numeric_and_fx_constraints(pg_factory, posting):  # noqa: F811
    import copy
    import json

    from pydantic import ValidationError

    from modules.accounting.schemas import PostingInput

    base = posting().model_dump(mode='json')
    candidates = []
    for field, value in [('source_version', 0), ('policy_id', 0), ('correction_of', 0),
                         ('document_date', None), ('operation_date', None), ('posting_date', None)]:
        candidate = copy.deepcopy(base)
        candidate[field] = value
        candidates.append((field, candidate))
    for field, value in [('amount', '-1'), ('amount', '100.001'), ('amount', '100000000000000000000'),
                         ('quantity', '0'), ('quantity', '0.0000001'), ('rate_scale', 0),
                         ('cash_activity', 'invalid'), ('rate', '1'), ('currency', 'USD')]:
        candidate = copy.deepcopy(base)
        candidate['lines'][0][field] = value
        candidates.append((f'{field}={value}', candidate))
    foreign = copy.deepcopy(base)
    foreign['lines'][0].update(currency='USD', original_amount='31.25', rate='3.2', rate_scale=1,
                               rate_date='2026-09-01', rate_source='Synthetic source', amount='99.99')
    candidates.append(('fx mismatch', foreign))
    failures = []
    async with pg_factory() as session:
        for label, candidate in candidates:
            try:
                PostingInput.model_validate(candidate)
            except ValidationError:
                pass
            else:
                pytest.fail(f'Oracle unexpectedly accepts {label}')
            try:
                async with session.begin_nested():
                    await session.scalar(text('SELECT accounting.inbox_replay_model(CAST(:body AS json))'),
                                         {'body': json.dumps(candidate)})
            except DBAPIError:
                pass
            else:
                failures.append(label)
        assert not failures, failures


async def test_inbox_numeric_boundaries_match_application(pg_factory, posting):  # noqa: F811
    import copy
    import json

    from pydantic import ValidationError

    from modules.accounting.schemas import PostingInput

    base = posting().model_dump(mode='json')
    candidates = []
    for field, values in [('amount', ['99999999999999999999', '9999999999999999999.9',
                                     '100000000000000000000', '0.000', '1.2300', '1.2301', 'NaN']),
                          ('quantity', ['0.000001', '0.0000001', '1.0000000', '0',
                                        '999999999999999999999999', '1000000000000000000000000'])]:
        for value in values:
            candidate = copy.deepcopy(base)
            candidate['lines'][0][field] = value
            candidates.append(candidate)
    rounding = copy.deepcopy(base)
    rounding['lines'][0].update(currency='USD', original_amount='0.01', rate='0.5', rate_scale=1,
                                rate_date='2026-09-01', rate_source='Synthetic half-up', amount='0.01')
    candidates.append(rounding)
    async with pg_factory() as session:
        for candidate in candidates:
            try:
                expected = PostingInput.model_validate(candidate)
            except ValidationError:
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.scalar(text('SELECT accounting.inbox_replay_model(CAST(:body AS json))'), {'body': json.dumps(candidate)})
            else:
                actual = await session.scalar(text('SELECT accounting.inbox_replay_model(CAST(:body AS json))'), {'body': json.dumps(candidate)})
                assert actual == expected.model_dump(mode='json')


async def test_inbox_integer_grammar_matches_installed_oracle(pg_factory):  # noqa: F811
    import json

    from pydantic import TypeAdapter

    values = ['1e0', '1.0', '1.00', '1_0', '1__0', '_1', '1_', '+01', ' 1 ',
              '1.', '01.0', '.0', '1.0_0', '١', '１', True, 1.0, 1.5,
              '1_0.0', '1_0.00', '+1_0', '01_0', '1.000', '-0.0', '0_0',
              '1\t', '\u001c1\u001c']
    oracle = TypeAdapter(int)
    async with pg_factory() as session:
        for value in values:
            try:
                expected = oracle.validate_python(value)
            except ValueError:
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.scalar(text('SELECT accounting.posting_integer_value(CAST(:value AS jsonb))'), {'value': json.dumps(value)})
            else:
                actual = await session.scalar(text('SELECT accounting.posting_integer_value(CAST(:value AS jsonb))'), {'value': json.dumps(value)})
                assert actual == expected, (value, actual, expected)


async def test_inbox_analytical_whitespace_matches_application(pg_factory, posting):  # noqa: F811
    import json

    from pydantic import ValidationError

    from modules.accounting.schemas import PostingInput

    async with pg_factory() as session:
        for value in ['\u001c', '\u001d \u001e\t\u001f', '\u00a0\u001c\u0085',
                      '\u001cvalue\u001f', ' department ', '\u001c value \u001f']:
            payload = posting().model_dump(mode='json')
            payload['lines'][0]['dimensions'] = {'department': value}
            try:
                expected = PostingInput.model_validate(payload)
            except ValidationError:
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.scalar(text('SELECT accounting.inbox_replay_model(CAST(:body AS json))'), {'body': json.dumps(payload)})
            else:
                actual = await session.scalar(text('SELECT accounting.inbox_replay_model(CAST(:body AS json))'), {'body': json.dumps(payload)})
                assert actual == expected.model_dump(mode='json')


async def test_inbox_float_boolean_opening_resolves(pg_factory, pg_book, posting):  # noqa: F811
    async with pg_factory() as session:
        for value in [1.0, 0.0]:
            payload = posting(source=f'opening-{value}').model_dump(mode='json')
            payload['opening'] = value
            row = await service.receive(session, pg_book[0], f'opening-event-{value}', '2026-09', payload)
            assert row.error is None
            await session.commit()
            entry = await service.confirm_inbox(session, pg_book[0], row.id, 'tester')
            await session.commit()
            assert entry.opening is bool(value)
            assert (await service.receive(session, pg_book[0], f'opening-event-{value}', '2026-09', payload)).payload == payload


async def test_inbox_review_decimal_and_fx_inputs(pg_factory, pg_book, posting):  # noqa: F811
    import copy
    import json

    from pydantic import ValidationError

    from core.domain.reference import Currency
    from modules.accounting.schemas import PostingInput

    candidates = []
    for amount in ['1__00.0', '_100.0', '100.0_']:
        payload = posting().model_dump(mode='json')
        for line in payload['lines']:
            line['amount'] = amount
        candidates.append(payload)
    payload = posting().model_dump(mode='json')
    payload['lines'][0].update(
        currency='USD', original_amount='999999999999599999.99', rate='10.000001',
        rate_scale=100, rate_date='2026-09-01', rate_source='Synthetic rounding',
        amount='100000009999959999.99',
    )
    payload['lines'][1]['amount'] = '100000009999959999.99'
    candidates.append(payload)
    precision_boundary = copy.deepcopy(payload)
    precision_boundary['lines'][0].update(
        original_amount='999999999999999999.99', rate='500000000.000001',
        rate_scale=1000000000, amount='500000000000000999.99',
    )
    precision_boundary['lines'][1]['amount'] = '500000000000000999.99'
    candidates.append(precision_boundary)
    failures = []
    async with pg_factory() as session:
        session.add(Currency(code='USD', title='Synthetic USD'))
        await session.commit()
        for index, candidate in enumerate(candidates):
            candidate['source'] = f'review-decimal-{index}'
            expected = PostingInput.model_validate(candidate).model_dump(mode='json')
            try:
                async with session.begin_nested():
                    actual = await session.scalar(text('SELECT accounting.inbox_replay_model(CAST(:body AS json))'),
                                                  {'body': json.dumps(candidate)})
            except DBAPIError as exc:
                failures.append((candidate['lines'][0]['amount'], str(exc.orig)))
                continue
            assert actual == expected
            row = await service.receive(session, pg_book[0], f'review-event-{index}', '2026-09', candidate)
            assert row.error is None
            await session.commit()
            entry = await service.confirm_inbox(session, pg_book[0], row.id, 'tester')
            await session.commit()
            assert (await service.confirm_inbox(session, pg_book[0], row.id, 'tester')).id == entry.id
            await session.commit()
        # Adjacent cent values must not pass either validation boundary.
        for wrong_amount in ['100000009999959999.98', '100000010000000000.00']:
            payload['lines'][0]['amount'] = wrong_amount
            with pytest.raises(ValidationError, match='documented exchange rate'):
                PostingInput.model_validate(payload)
            with pytest.raises(DBAPIError, match='FX conversion mismatch'):
                async with session.begin_nested():
                    await session.scalar(text('SELECT accounting.inbox_replay_model(CAST(:body AS json))'),
                                         {'body': json.dumps(payload)})
    assert not failures, failures


async def test_inbox_rate_scale_storage_boundary(pg_factory, pg_book, posting):  # noqa: F811
    import json

    from pydantic import ValidationError

    from core.domain.reference import Currency
    from modules.accounting.schemas import PostingInput

    async with pg_factory() as session:
        session.add(Currency(code='USD', title='Synthetic USD'))
        await session.commit()
        for scale in [2147483647, 2147483648, 1000000000000000000]:
            payload = posting(source=f'scale-{scale}').model_dump(mode='json')
            payload['lines'][0].update(currency='USD', original_amount='100.00', rate=str(scale),
                                       rate_scale=scale, rate_date='2026-09-01', rate_source='Synthetic rate')
            if scale > 2147483647:
                with pytest.raises(ValidationError, match='rate_scale'):
                    PostingInput.model_validate(payload)
                with pytest.raises(DBAPIError, match='scale'):
                    async with session.begin_nested():
                        await session.scalar(text('SELECT accounting.inbox_replay_model(CAST(:body AS json))'),
                                             {'body': json.dumps(payload)})
            else:
                expected = PostingInput.model_validate(payload).model_dump(mode='json')
                assert await session.scalar(text('SELECT accounting.inbox_replay_model(CAST(:body AS json))'),
                                            {'body': json.dumps(payload)}) == expected
            row = await service.receive(session, pg_book[0], f'scale-event-{scale}', '2026-09', payload)
            await session.commit()
            if scale > 2147483647:
                assert 'rate_scale' in row.error
                assert row.entry_id is None
                replay = await service.receive(session, pg_book[0], f'scale-event-{scale}', '2026-09', payload)
                assert replay.id == row.id and replay.payload == payload
            else:
                assert row.error is None
                entry = await service.confirm_inbox(session, pg_book[0], row.id, 'tester')
                await session.commit()
                assert row.entry_id == entry.id
