"""Endpoint-relative stories over finite observations, outside the fixed TE core.

The 1-D environment and explanatory rules are declared, not inferred from prose.
Roles are derived from recorded choices and exhaustive support checks. They are
not inputs to the world, a measure of experience, or permission to change history.
"""
from copy import deepcopy
from itertools import combinations
import hashlib
import json

SCHEMA = 'te-flower-memory-v0.2'
_INTERNAL_RECONSTRUCTION = object()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


class Gap(Exception):
    def __init__(self, key):
        self.key = key


def outcome(center, position, half_width):
    if position < center - half_width:
        return 'left'
    if position > center + half_width:
        return 'right'
    return 'on'


def spec(identifier='ledge'):
    return dict(kind='world', id=identifier, centers=list(range(1, 8)),
                positions=list(range(9)), half_width=1, unit='cm',
                rule='closed-interval-v1')


def validate_world(world):
    if (set(world) != {'kind', 'id', 'centers', 'positions', 'half_width', 'unit', 'rule'}
            or world['kind'] != 'world' or world['rule'] != 'closed-interval-v1'
            or type(world['half_width']) is not int or world['half_width'] <= 0
            or world['unit'] != 'cm'):
        raise ValueError('complete finite world specification required')
    for name in ('centers', 'positions'):
        values = world[name]
        if (type(values) is not list or not 1 <= len(values) <= 21
                or any(type(x) is not int for x in values)
                or values != sorted(set(values))):
            raise ValueError('bounded distinct ordered integer coordinates required')


def consistent_centers(world, observations):
    """Linear scene consistency, not exponential minimal-support enumeration."""
    validate_world(world)
    for event in observations:
        if (event.get('kind') not in ('observation', 'placement')
                or event.get('world') != world['id']
                or type(event.get('position')) is not int
                or event['position'] not in world['positions']
                or event.get('outcome') not in ('left', 'right', 'on')):
            raise ValueError('observation must belong to this world and finite domain')
    centers = [c for c in world['centers'] if all(
        outcome(c, e['position'], world['half_width']) == e['outcome']
        for e in observations)]
    if not centers:
        raise ValueError('observations are inconsistent with the declared world')
    return centers


def possibilities(world, observations):
    if len(observations) > 8:
        raise ValueError('at most eight observations in this finite support experiment')
    centers = consistent_centers(world, observations)
    safe = [x for x in world['positions'] if all(
        outcome(c, x, world['half_width']) == 'on' for c in centers)]
    return dict(possible_centers=centers, safe_positions=safe)


def plan(world, observations, excluded_positions=()):
    result = possibilities(world, observations)
    excluded = sorted(set(excluded_positions))
    if any(type(x) is not int or x not in world['positions'] for x in excluded):
        raise ValueError('explicit previous positions in the declared domain required')
    choices = [x for x in result['safe_positions'] if x not in excluded]
    return dict(result, excluded_positions=excluded, choices=choices,
                action='place' if choices else 'ask_for_observation',
                selected=choices[0] if choices else None)


def support_sets(world, observations, selected):
    """All inclusion-minimal supports for this action, not post-hoc role labels."""
    observations = sorted(observations, key=lambda x: x['id'])
    if len({e['id'] for e in observations}) != len(observations):
        raise ValueError('distinct observations required')
    possibilities(world, observations)
    minimal = []
    for length in range(len(observations) + 1):
        for subset in combinations(observations, length):
            keys = frozenset(e['id'] for e in subset)
            if any(known <= keys for known in minimal):
                continue
            if selected in possibilities(world, list(subset))['safe_positions']:
                minimal.append(keys)
    return [sorted(s) for s in minimal]


def decision(identifier, world, observations, previous=(), memory=None, selected=None):
    result = plan(world, observations, [e['position'] for e in previous])
    if result['action'] != 'place':
        return None, result
    chosen = result['selected'] if selected is None else selected
    if type(chosen) is not int or chosen not in result['choices']:
        raise ValueError('current choice must be one of the actual admissible positions')
    event = dict(kind='decision', id=identifier, world=world['id'],
                 observations=[e['id'] for e in observations],
                 previous=[e['id'] for e in previous], memory=memory,
                 selected=chosen, policy='any-admissible-position-v1')
    return event, dict(result, selected=chosen)


def _record(records, key, horizon):
    if key not in records or records[key]['seq'] > horizon:
        raise Gap(key)
    row = records[key]
    if (type(row['seq']) is not int or row['seq'] < 1
            or type(row['value']) is not dict or row['value'].get('id') != key):
        raise ValueError('unaltered source id and receipt sequence required')
    return row


def explain(endpoint, records, observer='recipient', horizon=None):
    """Reconstruct this observer's story from the actual endpoint and its trace.

    Missing sources yield GAP. Available evidence that contradicts the declared
    execution raises ValueError. Later observations never justify an earlier
    choice: every dependency must precede its consumer in the E4 journal.
    """
    records = deepcopy(records)
    if horizon is None:
        horizon = max((r['seq'] for r in records.values()), default=0)
    if type(horizon) is not int or horizon < 0 or not isinstance(observer, str) or not observer:
        raise ValueError('explicit observer and finite historical horizon required')
    records = {k: v for k, v in records.items() if v['seq'] <= horizon}
    roles, links, supports, checked, active = {}, [], {}, set(), set()
    decisions = {}

    def role(key, value):
        roles.setdefault(key, set()).add(value)

    def visit(key, consumer=None):
        row = _record(records, key, horizon)
        if consumer is not None and row['seq'] >= records[consumer]['seq']:
            raise ValueError('a later observation cannot justify an earlier choice')
        if key in active:
            raise ValueError('causal trace cycle')
        if key in checked:
            return row['value']
        active.add(key)
        value = row['value']
        kind = value.get('kind')

        def dependency(source, relation):
            child = visit(source, key)
            links.append(dict(source=source, target=key, relation=relation))
            return child

        if kind == 'world':
            validate_world(value)
            role(key, 'declared_world_rule')
        elif kind == 'observation':
            world = dependency(value['world'], 'measurement_rule')
            possibilities(world, [value])
            role(key, 'recorded_observation')
        elif kind == 'decision':
            if (set(value) != {'kind', 'id', 'world', 'observations', 'previous',
                              'memory', 'selected', 'policy'}
                    or value['policy'] != 'any-admissible-position-v1'
                    or type(value['observations']) is not list
                    or len(set(value['observations'])) != len(value['observations'])
                    or type(value['previous']) is not list
                    or len(set(value['previous'])) != len(value['previous'])):
                raise ValueError('complete bounded choice record required')
            world = dependency(value['world'], 'choice_rule')
            observations = [dependency(e, 'considered_observation') for e in value['observations']]
            previous = [dependency(e, 'previous_placement') for e in value['previous']]
            if any(e['kind'] != 'placement' or e['outcome'] != 'on'
                   or e['world'] != world['id'] for e in previous):
                raise ValueError('previous successes in the same world required')
            for e in previous:
                role(e['id'], 'previous_success_exclusion')
            if value['memory'] is not None:
                memory = dependency(value['memory'], 'recalled_flower')
                if memory['kind'] != 'flower' or memory['view']['observer'] != observer:
                    raise ValueError('explicit same-observer recalled Flower required')
                expected = memory_observations(memory['view'], records)
                if set(value['observations']) != set(expected):
                    raise ValueError('choice inputs differ from the recalled Flower and endpoint')
                if value['previous'] != [memory['view']['endpoint']]:
                    raise ValueError('recalled endpoint must be the declared previous success')
            rebuilt, calculated = decision(key, world, observations, previous,
                                           value['memory'], value['selected'])
            if rebuilt != value:
                raise ValueError('recorded choice is not supported by the pre-choice observations')
            family = support_sets(world, observations, value['selected'])
            supports[key] = family
            decisions[key] = calculated
            for e in observations:
                count = sum(e['id'] in s for s in family)
                role(e['id'], 'necessary_decision_evidence' if count == len(family)
                     else 'alternative_decision_evidence' if count else 'considered_nonessential')
            role(key, 'executed_choice')
        elif kind == 'placement':
            choice = dependency(value['decision'], 'executed_position')
            if (choice['kind'] != 'decision' or choice['world'] != value['world']
                    or type(value['position']) is not int or choice['selected'] != value['position']
                    or value['outcome'] != 'on'):
                raise ValueError('successful endpoint must match the actual supported choice')
            role(key, 'recorded_success')
        elif kind == 'flower':
            validate_flower(row, records, read_horizon=horizon)
            role(key, 'recalled_flower')
        else:
            raise ValueError('world, observation, decision, placement or Flower trace required')
        active.remove(key)
        checked.add(key)
        return value

    try:
        end = visit(endpoint)
    except Gap as gap:
        return dict(schema=SCHEMA, observer=observer, horizon=horizon, endpoint=endpoint,
                    status='GAP', missing=[gap.key], available=sorted(records),
                    roles={}, links=[], support_families={},
                    story='終端から辿る途中の原文が足りない。欠けた関係は確定しない。')
    # Consistency of the scene is distinct from the evidence available when each
    # earlier choice was made. Never feed later receipts into those old choices.
    measured = {}
    for key in checked:
        value = records[key]['value']
        if value.get('kind') in ('observation', 'placement'):
            measured.setdefault(value['world'], []).append(value)
    for world_id, observations in measured.items():
        consistent_centers(records[world_id]['value'], observations)
    role(endpoint, 'endpoint')
    if end['kind'] == 'observation':
        role(endpoint, 'endpoint_nonplacement' if end['outcome'] != 'on' else 'endpoint_on')
        story = f"位置{end['position']}では{end['outcome']}だった。この観測を終端とした場面。"
    elif end['kind'] == 'placement':
        root = end['decision']
        calculated = decisions[root]
        story = (f"位置{end['position']}で成立した。選択前に残っていた中心候補は"
                 f"{calculated['possible_centers']}、成立を保証できる位置は"
                 f"{calculated['safe_positions']}。その選択を支えた最小の原文集合は"
                 f"{supports[root]}。")
        if records[root]['value']['memory']:
            story += '前のFlowerを読み戻し、その終端とは別の位置を選んだ。'
    else:
        raise ValueError('an actual observed outcome is required as endpoint')
    for key in records:
        if key not in checked:
            role(key, 'outside_this_story')
    return dict(schema=SCHEMA, observer=observer, horizon=horizon, endpoint=endpoint,
                status='CONNECTED', available=sorted(records),
                source_hashes={k: digest(records[k]) for k in sorted(checked)},
                available_hashes={k: digest(records[k]) for k in sorted(records)},
                roles={k: sorted(v) for k, v in sorted(roles.items())},
                links=sorted(links, key=lambda e: (e['target'], e['source'], e['relation'])),
                support_families=dict(sorted(supports.items())), story=story)


def memory_observations(view, records):
    if view['status'] != 'CONNECTED':
        raise ValueError('an incomplete Flower cannot supply a choice')
    end = _record(records, view['endpoint'], view['horizon'])['value']
    if end['kind'] != 'placement' or end['outcome'] != 'on':
        raise ValueError('a successful observed endpoint required for this continuation')
    families = view['support_families'].get(end['decision'], [])
    if not families:
        raise ValueError('recorded minimal support family required')
    return sorted({e for support in families for e in support} | {end['id']})


def flower_binding(identifier, view):
    """Capture caller intent BEFORE writing; do not derive it from the read row."""
    return dict(id=identifier, endpoint=view['endpoint'], observer=view['observer'],
                horizon=view['horizon'], view_sha256=digest(view))


def require_binding(expected):
    if (type(expected) is not dict or set(expected) != {
            'id', 'endpoint', 'observer', 'horizon', 'view_sha256', 'receipt_seq'}
            or any(type(expected[k]) is not str or not expected[k]
                   for k in ('id', 'endpoint', 'observer', 'view_sha256'))
            or type(expected['horizon']) is not int or expected['horizon'] < 0
            or type(expected['receipt_seq']) is not int or expected['receipt_seq'] < 1):
        raise ValueError('external caller binding with all six fields required before using a Flower')


def validate_flower(memory, records, *, read_horizon, expected=_INTERNAL_RECONSTRUCTION):
    """Check a real receipt, its causal time, and optionally external caller intent.

    Self-consistency alone cannot tell a valid but unintended Flower apart.
    Consumers must supply expected; nested historical reconstruction uses the
    common receipt/time checks and its decision's explicit observer constraint.
    """
    if (type(memory) is not dict or set(memory) != {'seq', 'value'}
            or type(memory['seq']) is not int or memory['seq'] < 1
            or type(memory['value']) is not dict):
        raise ValueError('an actual read Flower record with its receipt time is required')
    value = memory['value']
    if value.get('kind') != 'flower' or not isinstance(value.get('id'), str):
        raise ValueError('a read Flower record required')
    if records.get(value['id']) != memory:
        raise ValueError('the Flower must be the same source record in the current read packet')
    if (type(read_horizon) is not int or read_horizon < memory['seq']):
        raise ValueError('Flower receipt must not be later than the actual read horizon')
    view = value.get('view')
    if (type(view) is not dict or type(view.get('horizon')) is not int
            or view['horizon'] < 0 or view['horizon'] >= memory['seq']):
        raise ValueError('a Flower cannot contain a view from its own future')
    if view.get('schema') != SCHEMA or view.get('status') != 'CONNECTED':
        raise ValueError('complete connected Flower view required for reuse')
    if expected is not _INTERNAL_RECONSTRUCTION:
        require_binding(expected)
        actual_binding = dict(flower_binding(value['id'], view), receipt_seq=memory['seq'])
        if expected != actual_binding:
            raise ValueError('Flower differs from the caller expected id, endpoint, observer, time or view')
    original = {e: _record(records, e, view['horizon']) for e in view['available']}
    if explain(view['endpoint'], original, view['observer'], view['horizon']) != view:
        raise ValueError('recalled Flower must reconstruct before use')
    return original


def next_from_memory(identifier, memory, records, selected=None, *, expected, read_horizon):
    require_binding(expected)
    original = validate_flower(memory, records, read_horizon=read_horizon, expected=expected)
    value = memory['value']
    view = value['view']
    end = original[view['endpoint']]['value']
    world = original[end['world']]['value']
    inputs = [original[e]['value'] for e in memory_observations(view, original)]
    return decision(identifier, world, inputs, [end], value['id'], selected)


def role_transition(before, after):
    if (before['status'] != 'CONNECTED' or after['status'] != 'CONNECTED'
            or before['observer'] != after['observer'] or after['horizon'] <= before['horizon']):
        raise ValueError('same observer and a genuinely later view required')
    shared = set(before['roles']) & set(after['roles'])
    if any(before['available_hashes'][k] != after['available_hashes'][k] for k in shared):
        raise ValueError('role change requires the same retained source, not a changed past')
    changed = []
    for key in sorted(set(before['roles']) & set(after['roles'])):
        old, new = before['roles'][key], after['roles'][key]
        if old != new:
            changed.append(dict(event=key, before=old, after=new))
    recontextualized = [c['event'] for c in changed if
        'endpoint_nonplacement' in c['before'] and
        set(c['after']) & {'necessary_decision_evidence', 'alternative_decision_evidence'}]
    return dict(before_endpoint=before['endpoint'], after_endpoint=after['endpoint'],
                changed=changed, recontextualized_observations=recontextualized,
                kind='endpoint_relative_role_change')


def intersections(views):
    result = []
    ordered = sorted(views, key=lambda v: (v['horizon'], v['observer'], v['endpoint']))
    for i, left in enumerate(ordered):
        if left['status'] != 'CONNECTED':
            continue
        for right in ordered[i + 1:]:
            if right['status'] != 'CONNECTED':
                continue
            common = sorted(set(left['source_hashes']) & set(right['source_hashes']))
            if any(left['source_hashes'][k] != right['source_hashes'][k] for k in common):
                raise ValueError('crossing Flowers must share the same source records')
            result.append(dict(left=left['endpoint'], right=right['endpoint'], shared=common,
                               earlier_endpoint_reused=(left['endpoint'] in common
                                   if left['horizon'] < right['horizon'] else None)))
    return result
