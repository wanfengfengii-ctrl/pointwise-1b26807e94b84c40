"""Identity and payload encoding for fixed isolation-plan reports."""

import json
from dataclasses import dataclass
from fractions import Fraction

from reports.receipt import Receipt


@dataclass(frozen=True, slots=True)
class IsolationReportCandidate:
    plan_id: int
    revision_id: int
    start: str
    p: Fraction
    release_probability: Fraction
    reject_probability: Fraction
    isolation_probability: Fraction
    never_probability: Fraction


@dataclass(frozen=True, slots=True)
class IsolationReport:
    receipt: Receipt
    revision_id: int
    start: str
    p: Fraction
    release_probability: Fraction
    reject_probability: Fraction
    isolation_probability: Fraction
    never_probability: Fraction

    @property
    def report_id(self):
        return self.receipt.report_id

    @property
    def plan_id(self):
        return self.receipt.plan_id


def validate_isolation_candidate(candidate):
    if type(candidate.plan_id) is not int or not 0 < candidate.plan_id < 2**63:
        raise ValueError('invalid plan number')
    if type(candidate.revision_id) is not int or not 0 < candidate.revision_id < 2**63:
        raise ValueError('invalid revision number')
    if type(candidate.start) is not str or not candidate.start.strip():
        raise ValueError('report start is required')
    values = (
        candidate.p, candidate.release_probability, candidate.reject_probability,
        candidate.isolation_probability, candidate.never_probability,
    )
    if any(type(value) is not Fraction for value in values):
        raise ValueError('all isolation report values must be exact fractions')
    if not 0 <= candidate.p <= 1:
        raise ValueError('isolation gear must lie in [0, 1]')
    if any(not 0 <= value <= 1 for value in values[1:]):
        raise ValueError('isolation outcome probabilities must lie in [0, 1]')
    if sum(values[1:]) != 1:
        raise ValueError('isolation outcome probabilities must total one')


def _encode_fraction(value):
    return [format(value.numerator, 'x'), format(value.denominator, 'x')]


def _decode_fraction(value):
    numerator, denominator = value
    return Fraction(int(numerator, 16), int(denominator, 16))


def encode_isolation_report(candidate):
    body = {
        'kind': 'isolation',
        'revision_id': candidate.revision_id,
        'start': candidate.start,
        'p': _encode_fraction(candidate.p),
        'release': _encode_fraction(candidate.release_probability),
        'reject': _encode_fraction(candidate.reject_probability),
        'isolation': _encode_fraction(candidate.isolation_probability),
        'never': _encode_fraction(candidate.never_probability),
    }
    return json.dumps(body, ensure_ascii=False, separators=(',', ':'))


def decode_isolation_report(report_id, plan_id, payload):
    body = json.loads(payload)
    if body.get('kind') != 'isolation':
        raise ValueError('payload is not an isolation report')
    receipt = Receipt(report_id, plan_id)
    return IsolationReport(
        receipt, body['revision_id'], body['start'], _decode_fraction(body['p']),
        _decode_fraction(body['release']), _decode_fraction(body['reject']),
        _decode_fraction(body['isolation']), _decode_fraction(body['never']),
    )
