"""Offline-replayable evidence for a fixed isolation plan.

The archive must stay usable after the source database closes, so the plan
payload carries a fully normalized transfer graph. Private stations and
terminals are replaced by stable aliases before export; only the public
station names leave the source boundary verbatim. Every mass is stored as an
exact rational, which lets any legal gear ``p`` be recomputed without ever
re-reading private names, raw counts, or terminal names.
"""

import json
from dataclasses import dataclass
from fractions import Fraction

from plans.absorption import hitting_probabilities

RELEASE = 'release'
REJECT = 'reject'
ISOLATION = 'isolation'
NEVER = 'never'
TERMINAL_OUTCOMES = (RELEASE, REJECT, ISOLATION)


@dataclass(frozen=True, slots=True)
class IsolationPlan:
    plan_id: int
    revision_id: int
    stations: tuple[str, ...]
    graph: dict[object, dict[object, Fraction]]
    gates: frozenset[tuple[object, object]]


def _references(revision):
    public = tuple(station.name for station in revision.stations if station.public)
    private = tuple(station.name for station in revision.stations if not station.public)
    aliases = {name: ('public', name) for name in public}
    aliases.update(
        (name, ('private', index)) for index, name in enumerate(private)
    )
    aliases[revision.release] = ('terminal', RELEASE)
    aliases[revision.reject] = ('terminal', REJECT)
    return aliases


def build_isolation_graph(revision, gate_keys):
    """Aggregate same-direction counts, normalize rows, and anonymize nodes."""
    totals = {}
    weights = {}
    for row in revision.counts:
        if row.count <= 0:
            continue
        totals[row.origin] = totals.get(row.origin, 0) + row.count
        key = (row.origin, row.destination)
        weights[key] = weights.get(key, 0) + row.count
    aliases = _references(revision)
    graph = {}
    for origin, total in totals.items():
        outgoing = {}
        for (raw_origin, destination), count in weights.items():
            if raw_origin == origin:
                outgoing[aliases[destination]] = Fraction(count, total)
        graph[aliases[origin]] = outgoing
    gates = frozenset((aliases[origin], aliases[destination]) for origin, destination in gate_keys)
    stations = tuple(station.name for station in revision.stations if station.public)
    return stations, graph, gates


def _fraction_json(value):
    return [format(value.numerator, 'x'), format(value.denominator, 'x')]


def encode_isolation_plan(stations, graph, gates):
    ordered_graph = {
        json.dumps(origin): {
            json.dumps(destination): _fraction_json(weight)
            for destination, weight in sorted(outgoing.items())
        }
        for origin, outgoing in sorted(graph.items())
    }
    ordered_gates = sorted((list(origin), list(destination)) for origin, destination in gates)
    body = {
        'kind': 'isolation',
        'stations': list(stations),
        'graph': ordered_graph,
        'gates': ordered_gates,
    }
    return json.dumps(body, ensure_ascii=False, separators=(',', ':'))


def _decode_reference(value):
    kind, identity = value
    if kind == 'terminal':
        return ('terminal', identity)
    if kind == 'public':
        return ('public', identity)
    if kind == 'private':
        return ('private', int(identity))
    raise ValueError('unknown node reference in isolation payload')


def decode_isolation_plan(plan_id, revision_id, payload):
    body = json.loads(payload)
    if body.get('kind') != 'isolation':
        raise ValueError('payload is not an isolation plan')
    stations = tuple(body['stations'])
    graph = {}
    for origin_json, outgoing in body['graph'].items():
        origin = _decode_reference(json.loads(origin_json))
        graph[origin] = {
            _decode_reference(json.loads(destination_json)):
                Fraction(int(numerator, 16), int(denominator, 16))
            for destination_json, (numerator, denominator) in outgoing.items()
        }
    gates = frozenset(
        (_decode_reference(origin), _decode_reference(destination))
        for origin, destination in body['gates']
    )
    return IsolationPlan(plan_id, revision_id, stations, graph, gates)


def outcome_table(plan, start, p):
    """Exact absorption masses (release, reject, isolation, never) from start."""
    zero = Fraction(0)
    gear = Fraction(p)
    transitions = {}
    for origin, outgoing in plan.graph.items():
        row = {}
        for destination, weight in outgoing.items():
            if (origin, destination) in plan.gates and gear > 0:
                row[('terminal', ISOLATION)] = row.get(('terminal', ISOLATION), zero) + weight * gear
                if gear < 1:
                    row[destination] = row.get(destination, zero) + weight * (1 - gear)
            else:
                row[destination] = row.get(destination, zero) + weight
        transitions[origin] = row
    start_ref = ('public', start)
    release = hitting_probabilities(transitions, ('terminal', RELEASE)).get(start_ref, zero)
    reject = hitting_probabilities(transitions, ('terminal', REJECT)).get(start_ref, zero)
    isolated = hitting_probabilities(transitions, ('terminal', ISOLATION)).get(start_ref, zero)
    never = Fraction(1) - release - reject - isolated
    return release, reject, isolated, never
