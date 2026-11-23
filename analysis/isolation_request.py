"""Sign isolation reports against a fixed plan after the source has closed."""

from fractions import Fraction

from analysis.request import InvalidReviewRequest
from plans.catalog import load_isolation_plan
from plans.isolation_snapshot import outcome_table
from reports.isolation_publish import issue_isolation_report
from reports.isolation_receipt import IsolationReportCandidate


def _validate_gear(p):
    if type(p) is bool or isinstance(p, float):
        raise InvalidReviewRequest('gear must be an exact Fraction in [0, 1]')
    if type(p) is int:
        if p not in (0, 1):
            raise InvalidReviewRequest('integer gears are only accepted as end positions 0 or 1')
        return Fraction(p)
    if type(p) is not Fraction or not 0 <= p <= 1:
        raise InvalidReviewRequest('gear must be a Fraction within [0, 1]')
    return p


def publish_isolation_report(archive, plan_id, start, p, *, before_commit=None):
    try:
        plan = load_isolation_plan(archive, plan_id)
    except ValueError as error:
        raise InvalidReviewRequest(str(error)) from error
    gear = _validate_gear(p)
    if type(start) is not str or start not in plan.stations:
        raise InvalidReviewRequest('start is not a public station on this isolation plan')
    release, reject, isolated, never = outcome_table(plan, start, gear)
    candidate = IsolationReportCandidate(
        plan.plan_id, plan.revision_id, start, gear,
        release, reject, isolated, never,
    )
    return issue_isolation_report(archive, candidate, before_commit=before_commit)
