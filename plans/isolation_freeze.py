"""Freeze a fixed isolation plan with its gate layout from one source revision."""

import sqlite3

from plans.catalog import save_isolation_plan
from plans.freeze import FreezeError
from plans.gates import validate_gate_keys
from plans.isolation_snapshot import build_isolation_graph
from source.revisions import RevisionNotFound, load_revision
from source.validation import validate_batch


def freeze_isolation_plan(source, archive, revision_id, gate_keys):
    try:
        revision = load_revision(source, revision_id)
        validate_batch(
            revision.batch, revision.stations, revision.release,
            revision.reject, revision.counts,
        )
        gates = validate_gate_keys(revision, gate_keys)
        stations, graph, aliased_gates = build_isolation_graph(revision, gates)
        return save_isolation_plan(archive, revision.revision_id, stations, graph, aliased_gates)
    except (RevisionNotFound, sqlite3.Error, ValueError, TypeError) as error:
        if isinstance(error, FreezeError):
            raise
        raise FreezeError(f'could not freeze isolation plan from revision {revision_id!r}') from error
