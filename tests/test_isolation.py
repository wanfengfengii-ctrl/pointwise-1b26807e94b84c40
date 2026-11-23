import json
from fractions import Fraction

from analysis.isolation_request import publish_isolation_report
from analysis.request import InvalidReviewRequest, publish_report
from isolation_case import GATE_LAYOUTS, receive_isolation_case
from plans.catalog import (
    PlanNotFound,
    load_any_plan,
    load_isolation_plan,
    load_plan,
)
from plans.freeze import FreezeError, freeze_plan
from plans.isolation_freeze import freeze_isolation_plan
from plans.isolation_snapshot import outcome_table
from reports.handover import HandoverEntry, handover
from reports.history import ReportNotFound, read_isolation_report, read_report
from reports.publish import PublishError
from reports.receipt import Receipt
from source.corrections import amend
from source.intake import receive
from source.revisions import Station, TransferCount
from tests.fixtures import DatabaseCase, receive_sample, sample


GATES_TABLE = {
    ('return_gate', 0): (Fraction(1, 3), Fraction(0), Fraction(0), Fraction(2, 3)),
    ('return_gate', Fraction(1, 2)): (Fraction(1, 5), Fraction(0), Fraction(4, 5), Fraction(0)),
    ('return_gate', 1): (Fraction(1, 7), Fraction(0), Fraction(6, 7), Fraction(0)),
    ('exit_gate', 0): (Fraction(1, 3), Fraction(0), Fraction(0), Fraction(2, 3)),
    ('exit_gate', Fraction(1, 2)): (Fraction(1, 7), Fraction(0), Fraction(6, 7), Fraction(0)),
    ('exit_gate', 1): (Fraction(0), Fraction(0), Fraction(1), Fraction(0)),
    ('unmarked_hold', Fraction(1, 2)): (Fraction(1, 5), Fraction(0), Fraction(1, 5), Fraction(3, 5)),
}


class IsolationFreezeCase(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.revision_id = receive_isolation_case(self.source)

    def freeze_layout(self, name):
        return freeze_isolation_plan(
            self.source, self.archive, self.revision_id, GATE_LAYOUTS[name]
        )

    def test_gates_oracle_table(self):
        plans = {name: self.freeze_layout(name) for name in GATE_LAYOUTS}
        for (name, gear), expected in GATES_TABLE.items():
            with self.subTest(layout=name, p=gear):
                actual = outcome_table(plans[name], 'A', Fraction(gear))
                self.assertEqual(actual, expected)
                self.assertEqual(sum(actual), 1)

    def test_empty_gate_layout_is_legal(self):
        plan = freeze_isolation_plan(self.source, self.archive, self.revision_id, [])
        self.assertEqual(plan.gates, frozenset())
        baseline = outcome_table(plan, 'A', Fraction(0))
        for gear in (0, Fraction(1, 3), Fraction(1, 2), 1):
            release, reject, isolated, never = outcome_table(plan, 'A', Fraction(gear))
            self.assertEqual(isolated, 0)
            self.assertEqual((release, reject, never), baseline[:2] + (baseline[3],))

    def test_gate_keys_are_deduped_and_set_interpreted(self):
        first = freeze_isolation_plan(
            self.source, self.archive, self.revision_id, [('P', 'P'), ('Q', 'Q')]
        )
        second = freeze_isolation_plan(
            self.source, self.archive, self.revision_id,
            [('Q', 'Q'), ('P', 'P'), ('P', 'P')],
        )
        self.assertEqual(first.gates, second.gates)

    def test_public_edges_cannot_be_gated(self):
        for key in (('B', 'A'), ('B', 'pass')):
            with self.subTest(key=key):
                with self.assertRaises(FreezeError):
                    freeze_isolation_plan(self.source, self.archive, self.revision_id, [key])
        self.assertEqual(
            [row[0] for row in self.archive.execute('SELECT plan_id FROM fixed_plans')], []
        )

    def test_gate_requires_positive_count_and_known_edge(self):
        revision = receive(
            self.source, 'zero-edge', [Station('A', True), Station('P', False)],
            'pass', 'fail',
            [TransferCount('A', 'P', 1), TransferCount('P', 'pass', 0),
             TransferCount('P', 'P', 2)],
        )
        for key in (('P', 'pass'), ('P', 'unknown'), ('A', 'unknown'), ('Z', 'P')):
            with self.subTest(key=key):
                with self.assertRaises(FreezeError):
                    freeze_isolation_plan(self.source, self.archive, revision, [key])
        self.assertEqual(
            [row[0] for row in self.archive.execute('SELECT plan_id FROM fixed_plans')], []
        )

    def test_gate_shape_validation(self):
        for bad in (('PP',), [('P',)], [('P', 'P', 'P')], [(1, 'P')], [('P', '')], [None]):
            with self.subTest(bad=bad):
                with self.assertRaises(FreezeError):
                    freeze_isolation_plan(self.source, self.archive, self.revision_id, bad)

    def test_private_to_terminal_and_private_to_public_gates_are_legal(self):
        revision = receive(
            self.source, 'mixed-gates', [Station('A', True), Station('P', False)],
            'pass', 'fail',
            [TransferCount('A', 'P', 1), TransferCount('P', 'pass', 1),
             TransferCount('P', 'A', 1)],
        )
        plan = freeze_isolation_plan(
            self.source, self.archive, revision, [('P', 'pass'), ('P', 'A')]
        )
        # r = r_P, r_P = (1-p)/2 + (1-p)/2 * r with p = 1/2  ->  release 1/3,
        # isolation = p / (1 - (1-p)/2) = 2/3, no never mass.
        values = outcome_table(plan, 'A', Fraction(1, 2))
        self.assertEqual(values, (Fraction(1, 3), Fraction(0), Fraction(2, 3), Fraction(0)))

    def test_unknown_or_unreadable_revision(self):
        with self.assertRaises(FreezeError):
            freeze_isolation_plan(self.source, self.archive, self.revision_id + 10, [])
        self.source.close()
        with self.assertRaises(FreezeError):
            freeze_isolation_plan(self.source, self.archive, self.revision_id, [])
        with self.assertRaises(PlanNotFound):
            load_isolation_plan(self.archive, 1)

    def test_plan_identity_and_anonymized_payload(self):
        plan = self.freeze_layout('exit_gate')
        self.assertEqual(plan.stations, ('A', 'B'))
        self.assertEqual(plan.revision_id, self.revision_id)
        payload = self.archive.execute(
            'SELECT payload FROM fixed_plans WHERE plan_id = ?', (plan.plan_id,)
        ).fetchone()[0]
        body = json.loads(payload)
        self.assertEqual(body['kind'], 'isolation')
        for secret in ('P', 'Q', 'pass', 'fail', 'CY-isolation'):
            self.assertNotIn(secret, payload)
        self.reopen_archive()
        self.assertEqual(load_isolation_plan(self.archive, plan.plan_id), plan)

    def test_plan_kind_guards(self):
        v1 = freeze_plan(self.source, self.archive, self.revision_id)
        isolation = self.freeze_layout('return_gate')
        with self.assertRaises(ValueError):
            load_plan(self.archive, isolation.plan_id)
        with self.assertRaises(ValueError):
            load_isolation_plan(self.archive, v1.plan_id)
        self.assertEqual(load_any_plan(self.archive, v1.plan_id).plan_id, v1.plan_id)
        self.assertEqual(load_any_plan(self.archive, isolation.plan_id).plan_id, isolation.plan_id)
        with self.assertRaises(PlanNotFound):
            load_isolation_plan(self.archive, 999)

    def test_repeated_observation_rows_are_combined(self):
        revision = receive(
            self.source, 'duplicates', [Station('A', True), Station('P', False)],
            'pass', 'fail',
            [TransferCount('A', 'P', 1), TransferCount('A', 'P', 3),
             TransferCount('P', 'P', 2), TransferCount('P', 'pass', 2)],
        )
        plan = freeze_isolation_plan(self.source, self.archive, revision, [('P', 'P')])
        # Only the self-loop is gated: r_P = 1/2 + 1/4 r_P -> 2/3,
        # i_P = 1/4 + 1/4 i_P -> 1/3, no never mass.
        values = outcome_table(plan, 'A', Fraction(1, 2))
        self.assertEqual(values, (Fraction(2, 3), Fraction(0), Fraction(1, 3), Fraction(0)))


class IsolationSigningCase(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.revision_id = receive_isolation_case(self.source)
        self.plans = {
            name: freeze_isolation_plan(self.source, self.archive, self.revision_id, gates)
            for name, gates in GATE_LAYOUTS.items()
        }
        self.v1_plan = freeze_plan(self.source, self.archive, self.revision_id)
        self.source.close()

    def test_signed_reports_match_oracle_and_round_trip(self):
        for (name, gear), expected in GATES_TABLE.items():
            with self.subTest(layout=name, p=gear):
                report = publish_isolation_report(
                    self.archive, self.plans[name].plan_id, 'A', Fraction(gear),
                )
                values = (report.release_probability, report.reject_probability,
                          report.isolation_probability, report.never_probability)
                self.assertEqual(values, expected)
                self.assertEqual(report.p, Fraction(gear))
                self.assertEqual(report.start, 'A')
                self.assertEqual(report.revision_id, self.revision_id)
                self.assertEqual(report.receipt, Receipt(report.report_id, report.plan_id))
                self.reopen_archive()
                self.assertEqual(read_isolation_report(self.archive, report.report_id), report)

    def test_integer_end_gears_are_accepted(self):
        plan_id = self.plans['return_gate'].plan_id
        zero = publish_isolation_report(self.archive, plan_id, 'A', 0)
        one = publish_isolation_report(self.archive, plan_id, 'A', 1)
        self.assertIs(type(zero.p), Fraction)
        self.assertEqual(zero.p, Fraction(0))
        self.assertEqual(one.p, Fraction(1))
        self.assertEqual((zero.release_probability, zero.never_probability),
                         (Fraction(1, 3), Fraction(2, 3)))
        self.assertEqual((one.release_probability, one.isolation_probability),
                         (Fraction(1, 7), Fraction(6, 7)))

    def test_invalid_gear_values(self):
        plan_id = self.plans['return_gate'].plan_id
        for bad in (0.5, 1.0, True, False, -1, 2, Fraction(-1, 2), Fraction(3, 2), '1/2', None):
            with self.subTest(bad=bad):
                with self.assertRaises(InvalidReviewRequest):
                    publish_isolation_report(self.archive, plan_id, 'A', bad)
        self.assertEqual(handover(self.archive, plan_id), [])

    def test_invalid_start_and_unknown_plan(self):
        plan_id = self.plans['return_gate'].plan_id
        with self.assertRaises(InvalidReviewRequest):
            publish_isolation_report(self.archive, plan_id, 'P', Fraction(1, 2))
        with self.assertRaises(InvalidReviewRequest):
            publish_isolation_report(self.archive, plan_id, 42, Fraction(1, 2))
        with self.assertRaises(PlanNotFound):
            publish_isolation_report(self.archive, plan_id + 100, 'A', Fraction(1, 2))

    def test_v1_plan_rejected_by_isolation_entry(self):
        with self.assertRaises(InvalidReviewRequest):
            publish_isolation_report(self.archive, self.v1_plan.plan_id, 'A', Fraction(1, 2))
        self.assertEqual(handover(self.archive, self.v1_plan.plan_id), [])

    def test_handover_lists_reports_in_signing_order(self):
        plan_id = self.plans['return_gate'].plan_id
        first = publish_isolation_report(self.archive, plan_id, 'A', 0)
        other = publish_isolation_report(self.archive, self.plans['exit_gate'].plan_id, 'A', 1)
        second = publish_isolation_report(self.archive, plan_id, 'A', Fraction(1, 2))
        self.assertEqual(
            handover(self.archive, plan_id),
            [HandoverEntry(first.report_id, 'A'), HandoverEntry(second.report_id, 'A')],
        )
        self.assertEqual(
            handover(self.archive, other.plan_id), [HandoverEntry(other.report_id, 'A')]
        )

    def test_commit_abort_leaves_no_trace_and_is_retriable(self):
        plan_id = self.plans['return_gate'].plan_id

        def fail(receipt):
            self.assertEqual(receipt.plan_id, plan_id)
            raise RuntimeError('night shift paused')

        with self.assertRaises(PublishError) as raised:
            publish_isolation_report(
                self.archive, plan_id, 'A', Fraction(1, 2), before_commit=fail
            )
        self.assertIsInstance(raised.exception.__cause__, RuntimeError)
        self.assertEqual(handover(self.archive, plan_id), [])
        with self.assertRaises(ReportNotFound):
            read_isolation_report(self.archive, 1)
        retry = publish_isolation_report(self.archive, plan_id, 'A', Fraction(1, 2))
        self.assertEqual(handover(self.archive, plan_id),
                         [HandoverEntry(retry.report_id, 'A')])
        self.assertEqual(retry.isolation_probability, Fraction(4, 5))

    def test_readback_kind_guards_and_unknown_report(self):
        report = publish_isolation_report(
            self.archive, self.plans['exit_gate'].plan_id, 'A', Fraction(1, 2)
        )
        with self.assertRaises(ValueError):
            read_report(self.archive, report.report_id)
        with self.assertRaises(ReportNotFound):
            read_isolation_report(self.archive, 999)

    def test_reopen_archive_readback(self):
        report = publish_isolation_report(
            self.archive, self.plans['return_gate'].plan_id, 'A', Fraction(1, 2)
        )
        self.reopen_archive()
        recovered = read_isolation_report(self.archive, report.report_id)
        self.assertEqual(recovered, report)
        self.assertEqual(handover(self.archive, report.plan_id),
                         [HandoverEntry(report.report_id, 'A')])

    def test_zero_gear_restores_original_baseline(self):
        report = publish_isolation_report(
            self.archive, self.plans['return_gate'].plan_id, 'A', 0
        )
        self.assertEqual(
            (report.release_probability, report.reject_probability,
             report.isolation_probability, report.never_probability),
            (Fraction(1, 3), Fraction(0), Fraction(0), Fraction(2, 3)),
        )


class IsolationCrossKindCase(DatabaseCase):
    def test_v1_and_isolation_reports_coexist_and_keep_their_readers(self):
        revision = receive_sample(self.source, sample('straight'))
        v1_plan = freeze_plan(self.source, self.archive, revision)
        isolation_plan = freeze_isolation_plan(self.source, self.archive, revision, [])
        self.source.close()
        v1_report = publish_report(self.archive, v1_plan.plan_id, 'A', ('A', 'B'))
        isolation_report = publish_isolation_report(
            self.archive, isolation_plan.plan_id, 'A', 0
        )
        self.assertNotEqual(v1_report.report_id, isolation_report.report_id)
        self.assertEqual(read_report(self.archive, v1_report.report_id), v1_report)
        self.assertEqual(
            read_isolation_report(self.archive, isolation_report.report_id), isolation_report
        )
        with self.assertRaises(ValueError):
            read_report(self.archive, isolation_report.report_id)
        with self.assertRaises(ValueError):
            read_isolation_report(self.archive, v1_report.report_id)
        self.assertEqual(handover(self.archive, v1_plan.plan_id),
                         [HandoverEntry(v1_report.report_id, 'A')])
        self.assertEqual(handover(self.archive, isolation_plan.plan_id),
                         [HandoverEntry(isolation_report.report_id, 'A')])

    def test_amendment_keeps_old_plan_signable_offline(self):
        data = sample('straight')
        parent = receive_sample(self.source, data)
        old_plan = freeze_isolation_plan(self.source, self.archive, parent, [])
        child = amend(self.source, parent, [TransferCount(*row) for row in data['amendment']])
        new_plan = freeze_isolation_plan(self.source, self.archive, child, [])
        self.source.close()
        old_report = publish_isolation_report(self.archive, old_plan.plan_id, 'A', 0)
        new_report = publish_isolation_report(self.archive, new_plan.plan_id, 'A', 0)
        self.reopen_archive()
        self.assertEqual(read_isolation_report(self.archive, old_report.report_id), old_report)
        self.assertEqual(read_isolation_report(self.archive, new_report.report_id), new_report)
        self.assertEqual(old_report.release_probability, Fraction(1))
        self.assertEqual(new_report.release_probability, Fraction(1))

    def test_two_step_reject_example(self):
        revision = receive(
            self.source, 'reject-step', [Station('A', True), Station('P', False)],
            'pass', 'fail',
            [TransferCount('A', 'P', 1), TransferCount('P', 'fail', 1)],
        )
        plan = freeze_isolation_plan(self.source, self.archive, revision, [('P', 'fail')])
        self.source.close()
        report = publish_isolation_report(self.archive, plan.plan_id, 'A', Fraction(1, 2))
        self.assertEqual(
            (report.release_probability, report.reject_probability,
             report.isolation_probability, report.never_probability),
            (Fraction(0), Fraction(1, 2), Fraction(1, 2), Fraction(0)),
        )

    def test_no_departure_is_never_even_fully_open(self):
        revision = receive(
            self.source, 'dead-end', [Station('A', True), Station('P', False)],
            'pass', 'fail',
            [TransferCount('P', 'P', 1)],
        )
        plan = freeze_isolation_plan(self.source, self.archive, revision, [('P', 'P')])
        self.source.close()
        report = publish_isolation_report(self.archive, plan.plan_id, 'A', 1)
        self.assertEqual(
            (report.release_probability, report.reject_probability,
             report.isolation_probability, report.never_probability),
            (Fraction(0), Fraction(0), Fraction(0), Fraction(1)),
        )
