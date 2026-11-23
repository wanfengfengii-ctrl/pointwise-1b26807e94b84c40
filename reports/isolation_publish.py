"""Stage and commit one isolation report and its handover entry as a unit."""

from reports.isolation_receipt import (
    IsolationReport,
    IsolationReportCandidate,
    encode_isolation_report,
    validate_isolation_candidate,
)
from reports.publish import PublishError
from reports.receipt import Receipt
from reports.storage import insert_handover_entry, insert_report, publication_transaction


def issue_isolation_report(archive, candidate: IsolationReportCandidate, *, before_commit=None):
    validate_isolation_candidate(candidate)
    payload = encode_isolation_report(candidate)
    try:
        with publication_transaction(archive):
            report_id = insert_report(archive, candidate.plan_id, payload)
            insert_handover_entry(archive, report_id, candidate.plan_id, candidate.start)
            receipt = Receipt(report_id, candidate.plan_id)
            report = IsolationReport(
                receipt, candidate.revision_id, candidate.start, candidate.p,
                candidate.release_probability, candidate.reject_probability,
                candidate.isolation_probability, candidate.never_probability,
            )
            if before_commit is not None:
                before_commit(receipt)
    except Exception as error:
        raise PublishError(
            f'isolation publication failed for plan {candidate.plan_id}'
        ) from error
    return report
