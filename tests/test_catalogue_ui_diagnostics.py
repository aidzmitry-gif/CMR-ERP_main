"""Public QA exports numbers only; raw browser diagnostics stay private."""
import base64
import copy
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'catalogue_ui_controller', Path(__file__).resolve().parents[1] / 'scripts/check_reference_catalog_ui.py',
)
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


def attachment(value):
    return {'attachments': [{'name': 'catalogue-http-numeric', 'contentType': 'application/json',
                             'body': base64.b64encode(json.dumps(value).encode()).decode()}]}


def valid():
    return {'total': 1, 'dropped': 0, 'entries': [{'pathId': 1, 'status': 403}]}


def test_valid_request_diagnostic():
    assert controller.request_diagnostic(attachment(valid())) == valid()


def test_unknown_route_allowed():
    value = valid()
    value['entries'][0]['pathId'] = 0
    assert controller.request_diagnostic(attachment(value)) == value


def test_missing_attachment():
    assert controller.request_diagnostic({'attachments': []}) is None


@pytest.mark.parametrize('defect', [
    'duplicate', 'enum', 'bool', 'body_size', 'path_only', 'pii', 'count', 'entries_overflow', 'status',
])
def test_invalid_request_diagnostic(defect):
    value = valid()
    attempt = attachment(value)
    if defect == 'duplicate':
        attempt['attachments'] *= 2
    elif defect == 'path_only':
        attempt['attachments'][0].pop('body')
        attempt['attachments'][0]['path'] = '/private/report.json'
    elif defect == 'body_size':
        attempt['attachments'][0]['body'] = 'A' * 8193
    else:
        if defect == 'enum':
            value['entries'][0]['pathId'] = 10
        elif defect == 'bool':
            value['entries'][0]['status'] = True
        elif defect == 'pii':
            value['entries'][0]['url'] = 'PRIVATE_SENTINEL_MUST_NOT_EXPORT'
        elif defect == 'count':
            value['total'] = 2
        elif defect == 'entries_overflow':
            value['entries'] *= 17
            value['total'] = 17
        elif defect == 'status':
            value['entries'][0]['status'] = 200
        attempt = attachment(value)
    with pytest.raises(AssertionError):
        controller.request_diagnostic(attempt)


def report():
    specs = []
    for project, filename, title in sorted(controller.EXPECTED_CASES):
        diagnostic = (attachment({'total': 0, 'dropped': 0, 'entries': []})
                      if filename == 'reference-catalog.spec.ts' else {})
        specs.append({'file': filename, 'title': title, 'tests': [{
            'projectId': project, 'expectedStatus': 'passed',
            'results': [{'retry': 0, 'status': 'passed', **diagnostic}],
        }]})
    return {'suites': [{'specs': specs}], 'errors': [], 'stats': {'duration': 1}}


def test_result_exports_only_valid_numbers():
    value = report()
    value['suites'][0]['specs'][0]['tests'][0]['results'][0]['error'] = {
        'message': 'PRIVATE_SENTINEL_MUST_NOT_EXPORT',
    }
    result = controller.results(value, 0)
    assert result['passed'] and result['passedCount'] == 4
    requests = [case['requests'] for case in result['cases'] if 'requests' in case]
    assert requests == [{'total': 0, 'dropped': 0, 'entries': []}] * 3
    assert 'PRIVATE_SENTINEL' not in json.dumps(result)


def test_original_failure_preserved():
    value = copy.deepcopy(report())
    value['suites'][0]['specs'][0]['tests'][0]['results'][0]['status'] = 'failed'
    value['suites'][0]['specs'][0]['tests'][0]['results'][0].update(attachment(valid()))
    result = controller.results(value, 1)
    assert not result['passed'] and result['passedCount'] == 3 and result['failedCount'] == 1


@pytest.mark.parametrize('defect', ['nonzero', 'missing'])
def test_passed_catalogue_requires_zero_diagnostic(defect):
    value = report()
    attempt = value['suites'][0]['specs'][0]['tests'][0]['results'][0]
    if defect == 'nonzero':
        attempt.update(attachment(valid()))
    else:
        attempt.pop('attachments')
    with pytest.raises(AssertionError):
        controller.results(value, 0)
