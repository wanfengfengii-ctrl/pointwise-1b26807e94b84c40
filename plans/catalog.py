"""Plan numbering and immutable plan records in the archive database."""

import json

from plans.isolation_snapshot import decode_isolation_plan, encode_isolation_plan
from plans.snapshot import FixedPlan, decode_plan, encode_plan


class PlanNotFound(LookupError):
    pass


def initialize_plan_catalog(connection):
    connection.execute(
        'CREATE TABLE IF NOT EXISTS fixed_plans ('
        'plan_id INTEGER PRIMARY KEY, revision_id INTEGER NOT NULL, payload TEXT NOT NULL)'
    )


def _payload_kind(payload):
    try:
        body = json.loads(payload)
    except ValueError:
        return 'fixed'
    return body.get('kind', 'fixed') if isinstance(body, dict) else 'fixed'


def save_plan(connection, revision_id, stations, rows):
    payload = encode_plan(stations, rows)
    connection.execute('BEGIN IMMEDIATE')
    try:
        cursor = connection.execute(
            'INSERT INTO fixed_plans(revision_id, payload) VALUES (?, ?)',
            (revision_id, payload),
        )
        plan = FixedPlan(cursor.lastrowid, revision_id, stations, rows)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return plan


def save_isolation_plan(connection, revision_id, stations, graph, gates):
    payload = encode_isolation_plan(stations, graph, gates)
    connection.execute('BEGIN IMMEDIATE')
    try:
        cursor = connection.execute(
            'INSERT INTO fixed_plans(revision_id, payload) VALUES (?, ?)',
            (revision_id, payload),
        )
        plan_id = cursor.lastrowid
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return decode_isolation_plan(plan_id, revision_id, payload)


def _load_row(connection, plan_id):
    if type(plan_id) is not int or not 0 < plan_id < 2**63:
        raise PlanNotFound(plan_id)
    result = connection.execute(
        'SELECT revision_id, payload FROM fixed_plans WHERE plan_id = ?', (plan_id,)
    ).fetchone()
    if result is None:
        raise PlanNotFound(plan_id)
    return result


def load_plan(connection, plan_id):
    revision_id, payload = _load_row(connection, plan_id)
    if _payload_kind(payload) == 'isolation':
        raise ValueError(f'plan {plan_id} is an isolation plan, use load_isolation_plan')
    return decode_plan(plan_id, revision_id, payload)


def load_isolation_plan(connection, plan_id):
    revision_id, payload = _load_row(connection, plan_id)
    if _payload_kind(payload) != 'isolation':
        raise ValueError(f'plan {plan_id} is a fixed public plan, use load_plan')
    return decode_isolation_plan(plan_id, revision_id, payload)


def load_any_plan(connection, plan_id):
    """Load either plan kind, used by cross-kind archive queries such as handover."""
    revision_id, payload = _load_row(connection, plan_id)
    if _payload_kind(payload) == 'isolation':
        return decode_isolation_plan(plan_id, revision_id, payload)
    return decode_plan(plan_id, revision_id, payload)
