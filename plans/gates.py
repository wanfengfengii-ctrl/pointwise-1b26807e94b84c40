"""Gate layout validation against one frozen source revision."""

from collections import Counter

from plans.freeze import FreezeError


def validate_gate_keys(revision, gate_keys):
    """Return a deduplicated tuple of legal directed gate keys.

    A gate may only sit on a transfer whose combined count is positive and
    whose edge touches a private station. Public-to-public and
    public-to-terminal transfers cannot be gated. The empty layout is legal.
    """
    try:
        keys = tuple(gate_keys)
    except TypeError as error:
        raise FreezeError('gate_keys must be an iterable of directed pairs') from error

    station_names = {station.name for station in revision.stations}
    private_names = {station.name for station in revision.stations if not station.public}
    valid_destinations = station_names | {revision.release, revision.reject}

    combined = Counter()
    for row in revision.counts:
        combined[(row.origin, row.destination)] += row.count

    normalized = []
    seen = set()
    for position, key in enumerate(keys):
        if not isinstance(key, tuple) or len(key) != 2 or any(
            type(endpoint) is not str or not endpoint.strip() for endpoint in key
        ):
            raise FreezeError(f'gate {position} must be a (origin, destination) string pair')
        origin, destination = key
        if origin not in station_names or destination not in valid_destinations:
            raise FreezeError(f'gate {position} references an unknown transfer: {key!r}')
        if combined[(origin, destination)] <= 0:
            raise FreezeError(f'gate {position} has no positive transfer count: {key!r}')
        if origin not in private_names and destination not in private_names:
            raise FreezeError(
                f'gate {position} must touch a private station, public edges cannot be gated'
            )
        if key not in seen:
            seen.add(key)
            normalized.append(key)
    return tuple(normalized)
