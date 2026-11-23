"""Retrieve the original formal report and receipt by report number."""

import json

from reports.isolation_receipt import decode_isolation_report
from reports.receipt import decode_report
from reports.storage import load_report_row


class ReportNotFound(LookupError):
    pass


def _payload_kind(payload):
    try:
        body = json.loads(payload)
    except ValueError:
        return 'fixed'
    return body.get('kind', 'fixed') if isinstance(body, dict) else 'fixed'


def read_report(archive, report_id):
    row = load_report_row(archive, report_id)
    if row is None:
        raise ReportNotFound(report_id)
    report_id_value, _plan_id, payload = row
    if _payload_kind(payload) == 'isolation':
        raise ValueError(f'report {report_id_value} is an isolation report, use read_isolation_report')
    return decode_report(*row)


def read_isolation_report(archive, report_id):
    row = load_report_row(archive, report_id)
    if row is None:
        raise ReportNotFound(report_id)
    report_id_value, _plan_id, payload = row
    if _payload_kind(payload) != 'isolation':
        raise ValueError(f'report {report_id_value} is a fixed public report, use read_report')
    return decode_isolation_report(*row)
