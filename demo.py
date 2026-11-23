"""Run a bench-to-handover shift in two disposable SQLite files."""

import json
from contextlib import closing
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from analysis.isolation_request import publish_isolation_report
from analysis.request import publish_report
from isolation_case import GATE_LAYOUTS, receive_isolation_case
from plans.freeze import freeze_plan
from plans.isolation_freeze import freeze_isolation_plan
from plans.snapshot import PlanOutcome
from reports.handover import handover
from reports.history import read_isolation_report, read_report
from reports.storage import open_archive
from source.corrections import amend
from source.intake import receive
from source.revisions import Station, TransferCount
from source.storage import open_source
from walks.replay import replay_walk


def _description(report):
    return {
        'report': report.report_id,
        'plan': report.plan_id,
        'release': str(report.release_probability),
        'retained_given_release': (None if report.retention_given_release is None
                                  else str(report.retention_given_release)),
    }


def _isolation_description(report):
    return {
        'report': report.report_id,
        'plan': report.plan_id,
        'revision': report.revision_id,
        'start': report.start,
        'gear': str(report.p),
        'outcomes': {
            'release': str(report.release_probability),
            'reject': str(report.reject_probability),
            'isolation': str(report.isolation_probability),
            'never': str(report.never_probability),
        },
    }


def run_isolation_demo(archive_path):
    """Issue both sample gate layouts while the source is open, then sign offline."""
    source_path = archive_path.parent / 'isolation_source.sqlite3'
    with closing(open_archive(archive_path)) as archive:
        with closing(open_source(source_path)) as source:
            revision_id = receive_isolation_case(source)
            return_gate = freeze_isolation_plan(
                source, archive, revision_id, GATE_LAYOUTS['return_gate']
            )
            exit_gate = freeze_isolation_plan(
                source, archive, revision_id, GATE_LAYOUTS['exit_gate']
            )
            plan_ids = {
                'return_gate': return_gate.plan_id,
                'exit_gate': exit_gate.plan_id,
            }
        # Source database is now closed; every signature below uses the archive only.
        zero = publish_isolation_report(archive, plan_ids['return_gate'], 'A', 0)
        half = publish_isolation_report(
            archive, plan_ids['return_gate'], 'A', Fraction(1, 2)
        )
        full = publish_isolation_report(archive, plan_ids['exit_gate'], 'A', 1)
        signed = [zero, half, full]
        handovers = {
            str(plan_id): [entry.report_id for entry in handover(archive, plan_id)]
            for plan_id in plan_ids.values()
        }
    with closing(open_archive(archive_path)) as archive:
        recovered = [read_isolation_report(archive, report.report_id) for report in signed]
        assert recovered == signed
    assert (zero.release_probability, zero.reject_probability,
            zero.isolation_probability, zero.never_probability) == \
        (Fraction(1, 3), Fraction(0), Fraction(0), Fraction(2, 3))
    assert (half.release_probability, half.isolation_probability) == \
        (Fraction(1, 5), Fraction(4, 5))
    assert full.isolation_probability == Fraction(1)
    return {
        'batch': 'CY-isolation',
        'source_revision': revision_id,
        'plans': plan_ids,
        'source_closed_before_signing': True,
        'signed_reports': [_isolation_description(report) for report in signed],
        'reopened_readback': [_isolation_description(report) for report in recovered],
        'handover': handovers,
    }


def main():
    sample_path = Path(__file__).resolve().parent / 'samples' / 'shift.json'
    data = json.loads(sample_path.read_text(encoding='utf-8'))['returning']
    with TemporaryDirectory() as directory:
        source_path = Path(directory) / 'source.sqlite3'
        archive_path = Path(directory) / 'archive.sqlite3'
        with closing(open_archive(archive_path)) as archive:
            with closing(open_source(source_path)) as source:
                revision = receive(
                    source, data['batch'], [Station(*row) for row in data['stations']],
                    data['release'], data['reject'], [TransferCount(*row) for row in data['counts']],
                )
                plan = freeze_plan(source, archive, revision)
            walk = replay_walk(archive, plan.plan_id, 'A', (*data['walk'], PlanOutcome.RELEASE))
            original = publish_report(archive, plan.plan_id, 'A', ('A', 'B'))
            with closing(open_source(source_path)) as source:
                corrected = amend(source, revision, [TransferCount(*row) for row in data['amendment']])
                new_plan = freeze_plan(source, archive, corrected)
            amended = publish_report(archive, new_plan.plan_id, 'A', ('A', 'B'))
        with closing(open_archive(archive_path)) as archive:
            original_copy = read_report(archive, original.report_id)
            amended_copy = read_report(archive, amended.report_id)
            lists = {
                str(plan_id): [entry.report_id for entry in handover(archive, plan_id)]
                for plan_id in (plan.plan_id, new_plan.plan_id)
            }
        row = plan.row_for('A')
        assert (row['B'], row['C'], row[PlanOutcome.NEVER]) == (Fraction(1, 4), Fraction(1, 2), Fraction(1, 4))
        assert walk.actual == ('A', 'B', 'A', 'C') and walk.retained == ('A', 'C')
        assert (original.release_probability, original.retention_given_release) == (Fraction(3, 7), Fraction(1, 3))
        assert (amended.release_probability, amended.retention_given_release) == (Fraction(1, 2), Fraction(0))
        assert original_copy == original and amended_copy == amended
        assert lists == {str(plan.plan_id): [original.report_id], str(new_plan.plan_id): [amended.report_id]}
        isolation_summary = run_isolation_demo(Path(directory) / 'isolation_archive.sqlite3')
        print(json.dumps({
            'batch': data['batch'],
            'source_revisions': [plan.revision_id, new_plan.revision_id],
            'next_outcomes_from_A': {
                key.value if isinstance(key, PlanOutcome) else key: str(value) for key, value in row.items()
            },
            'walk': {'actual': walk.actual, 'retained': walk.retained, 'erasures': walk.erasures,
                     'terminal': walk.terminal.value},
            'original_report': _description(original_copy),
            'amended_report': _description(amended_copy),
            'handover': lists,
            'isolation_demo': isolation_summary,
        }, ensure_ascii=False))


if __name__ == '__main__':
    main()
