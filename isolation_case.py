"""Source fixture and baseline replay for the isolation-gate handover."""

import json
from contextlib import closing
from fractions import Fraction

from analysis.request import publish_report
from plans.freeze import freeze_plan
from plans.snapshot import PlanOutcome
from reports.handover import HandoverEntry, handover
from reports.history import read_report
from reports.storage import open_archive
from source.intake import receive
from source.revisions import Station, TransferCount
from source.storage import open_source

GATE_LAYOUTS = {
    "return_gate": (("P", "P"), ("Q", "Q")),
    "exit_gate": (("P", "B"), ("Q", "Q")),
    "unmarked_hold": (("P", "P"),),
}


def receive_isolation_case(source):
    stations = [Station("A", True), Station("B", True),
                Station("P", False), Station("Q", False)]
    counts = [TransferCount(origin, destination, 1) for origin, destination in (
        ("A", "P"), ("A", "Q"), ("P", "P"), ("P", "B"),
        ("Q", "Q"), ("B", "A"), ("B", "pass"),
    )]
    return receive(source, "CY-isolation", stations, "pass", "fail", counts)


def main():
    with closing(open_archive(":memory:")) as archive:
        with closing(open_source(":memory:")) as source:
            revision_id = receive_isolation_case(source)
            plan = freeze_plan(source, archive, revision_id)
        row = plan.row_for("A")
        if (row["B"], row[PlanOutcome.NEVER]) != (Fraction(1, 2), Fraction(1, 2)):
            raise AssertionError(f"unexpected V1 first-arrival row: {row!r}")
        report = publish_report(archive, plan.plan_id, "A", ("A", "B"))
        if (report.release_probability, report.retention_given_release) != (Fraction(1, 3), Fraction(1)):
            raise AssertionError(f"unexpected V1 report: {report!r}")
        if read_report(archive, report.report_id) != report:
            raise AssertionError("V1 stored report differs from issued report")
        if handover(archive, plan.plan_id) != [HandoverEntry(report.report_id, "A")]:
            raise AssertionError("V1 handover does not reference the issued report")
        print(json.dumps({
            "revision_id": revision_id,
            "plan_id": plan.plan_id,
            "next_B": str(row["B"]),
            "no_public_arrival": str(row[PlanOutcome.NEVER]),
            "report_id": report.report_id,
            "release": str(report.release_probability),
            "retained_given_release": str(report.retention_given_release),
        }))


if __name__ == "__main__":
    main()
