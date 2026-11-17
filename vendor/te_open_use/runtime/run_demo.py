"""Run the local Flower experiment through the unchanged public TE protocol."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from flower_memory import (SCHEMA, decision, digest, encode, explain, intersections,
                           next_from_memory, outcome, plan, role_transition, spec,
                           flower_binding, validate_flower)

ROOT = Path(__file__).resolve().parent
WIRE = 'te-flower-source-parts-v1'


def write(path, value):
    with path.open('xb') as stream:
        stream.write(encode(value))


class Ledger:
    def __init__(self, runtime, log, checkpoint=None, sha=None):
        args = [sys.executable, '-I', '-B', '-X', 'utf8', str(runtime / 'run_recollection.py')]
        if checkpoint is not None:
            args += ['--episode', str(checkpoint), '--trusted-episode-sha256', sha]
        self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)
        self.log = log
        self.ids = []
        self.receive(None)

    def receive(self, command, allow_error=False):
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError(self.process.stderr.read().decode('utf-8', 'replace'))
        value = json.loads(line)
        self.log.append(dict(command=command, response=value))
        if not value.get('ok') and not allow_error:
            raise ValueError(value)
        return value

    def send(self, command, allow_error=False):
        self.process.stdin.write(json.dumps(command, ensure_ascii=True).encode() + b'\n')
        self.process.stdin.flush()
        return self.receive(command, allow_error)

    def record(self, identifier, source, text):
        result = self.send(dict(op='record', id=identifier, origin='reported_in_session',
                                source=json.dumps(source, ensure_ascii=True, separators=(',', ':')),
                                text=text))
        self.ids.append(identifier)
        return result['status']['accepted_commands']

    def put(self, value):
        identifier = value['id']
        body = encode(value).decode('utf-8')
        # These are ordinary E4 records, with no changed byte or command limits.
        parts = []
        start, index = 0, 0
        while start < len(body):
            key = f'{identifier}-piece-{index}'
            meta = dict(schema=WIRE, kind='part', parent=identifier, index=index,
                        encoding='json-string-v1')
            end = min(start + 900, len(body))
            # Account for non-BMP characters and both JSON quoting layers.
            while True:
                piece = json.dumps(body[start:end], ensure_ascii=False)
                command = dict(op='record', id=key, origin='reported_in_session',
                               source=json.dumps(meta, separators=(',', ':')), text=piece)
                if len(json.dumps(command, ensure_ascii=True, separators=(',', ':')).encode()) < 7500:
                    break
                end -= 1
            self.record(key, meta, piece)
            parts.append(key)
            start, index = end, index + 1
        seq = self.record(identifier, dict(schema=WIRE, kind='value'),
                          json.dumps(dict(codec=WIRE, parts=parts, sha256=digest(value)),
                                     separators=(',', ':')))
        return seq

    def scope(self, name):
        groups = []
        for index, start in enumerate(range(0, len(self.ids), 32)):
            goal = f'goal-{name}-{index}'
            cue = f'flower-memory/{name}/{index}/'
            self.send(dict(op='goal', id=goal, text='Read explicit records for this local scene.',
                           events=self.ids[start:start + 32]))
            self.send(dict(op='register', id=f'memory-{name}-{index}', goal=goal, cues=[cue],
                           summary='Local finite scene; the original records are read separately.'))
            groups.append(cue)
        return self.read_groups(groups)

    def read_groups(self, groups):
        raw = {}
        packets = []
        for cue in groups:
            recalled = self.send(dict(op='call', cue=cue))
            if recalled['packet']['status'] != 'MATCH':
                raise ValueError('explicit matched TE recollection required')
            packets.append(recalled)
            for ref in recalled['packet']['references']:
                read = self.send(dict(op='read', ticket=recalled['ticket'], event=ref['id']))
                raw[ref['id']] = read['event']
        if len({p['packet']['as_of'] for p in packets}) != 1:
            raise ValueError('scope groups must be read at one receipt horizon')
        records = {}
        for key, row in raw.items():
            source = json.loads(row['source'])
            if source.get('schema') != WIRE or source.get('kind') != 'value':
                continue
            header = json.loads(row['text'])
            if set(header) != {'codec', 'parts', 'sha256'} or header['codec'] != WIRE:
                raise ValueError('complete source-part header required')
            if not header['parts'] or len(set(header['parts'])) != len(header['parts']):
                raise ValueError('distinct source parts required')
            texts = []
            for index, part in enumerate(header['parts']):
                piece = raw[part]
                expected = dict(schema=WIRE, kind='part', parent=key, index=index)
                metadata = json.loads(piece['source'])
                if metadata not in (expected, dict(expected, encoding='json-string-v1')) or piece['seq'] >= row['seq']:
                    raise ValueError('source parts changed identity, order or receipt time')
                texts.append(json.loads(piece['text']) if metadata.get('encoding') else piece['text'])
            value = json.loads(''.join(texts))
            if value['id'] != key or digest(value) != header['sha256']:
                raise ValueError('source payload differs from its actual TE readback')
            records[key] = dict(seq=row['seq'], value=value)
        horizon = packets[0]['packet']['as_of']
        return dict(records=records, horizon=horizon, groups=groups, packets=packets)

    def save(self, path):
        result = self.send(dict(op='save', path=str(path)))
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != result['sha256']:
            raise ValueError('external checkpoint hash mismatch')
        return dict(file=path.name, sha256=actual, bytes=path.stat().st_size,
                    commands=result['status']['accepted_commands'])

    def close(self):
        if self.process.poll() is None:
            self.send(dict(op='quit'))
            self.process.stdin.close()
        code = self.process.wait(timeout=30)
        if code:
            raise RuntimeError(self.process.stderr.read().decode('utf-8', 'replace'))
        self.process.stdout.close()
        self.process.stderr.close()


def check_flowers(scope, expected):
    rows = {key: row for key, row in scope['records'].items()
            if row['value'].get('kind') == 'flower'}
    if set(rows) != set(expected):
        raise ValueError('read Flower ids differ from the external descriptor')
    for key, row in rows.items():
        validate_flower(row, scope['records'], read_horizon=scope['horizon'], expected=expected[key])


def readback(runtime, directory, descriptor):
    log = []
    ledger = Ledger(runtime, log, directory / descriptor['file'], descriptor['sha256'])
    try:
        scope = ledger.read_groups(descriptor['groups'])
        check_flowers(scope, descriptor['flowers'])
        actual = explain(descriptor['endpoint'], scope['records'], horizon=scope['horizon'])
        if actual != descriptor['view']:
            raise ValueError('separate-process endpoint reconstruction differs')
        return dict(checkpoint=descriptor['file'], ok=True,
                    reconstructed_view_sha256=digest(actual),
                    sources_read=len(scope['records']), source_bytes_restored=True), log
    finally:
        ledger.close()


def run(runtime, output, first=3):
    output.mkdir(parents=True, exist_ok=False)
    log, checkpoints, expected_flowers = [], [], {}
    ledger = Ledger(runtime, log)
    # Only the environment gets this value. Recipient packets get observations.
    hidden_center = 4
    write(output / 'WORLD_TRUTH.json', dict(center=hidden_center,
        note='Only the finite environment uses this ground truth; never a recipient input.'))

    def observe(identifier, position):
        value = dict(kind='observation', id=identifier, world='ledge', position=position,
                     outcome=outcome(hidden_center, position, 1))
        ledger.put(value)
        return value

    def take_scene(name, endpoint):
        scope = ledger.scope(name)
        check_flowers(scope, expected_flowers)
        view = explain(endpoint, scope['records'], horizon=scope['horizon'])
        write(output / f'{name}.view.json', view)
        saved = ledger.save(output / f'{name}.episode.json')
        checkpoints.append(dict(saved, groups=scope['groups'], endpoint=endpoint, view=view,
                                flowers=deepcopy(expected_flowers)))
        return scope, view

    def remember(identifier, view):
        binding = flower_binding(identifier, deepcopy(view))
        seq = ledger.put(dict(kind='flower', id=identifier, view=deepcopy(view)))
        expected_flowers[identifier] = dict(binding, receipt_seq=seq)
        # Read immediately after the write, using caller intent retained outside
        # the payload. A valid Flower for another endpoint is still the wrong one.
        check_flowers(ledger.scope('verify-' + identifier), expected_flowers)

    try:
        ledger.put(spec())
        ledger.put(dict(kind='note', id='unrelated-note', text='棚の色を記録した。位置決めの根拠ではない。'))
        observe('left-miss', 1)
        initial, before = take_scene('00-first-miss', 'left-miss')
        old_ticket = initial['packets'][0]['ticket']
        remember('flower-miss', before)
        observe('right-miss', 6)
        prechoice = ledger.scope('prechoice')
        data = prechoice['records']
        choice, first_plan = decision('choose-first', data['ledge']['value'],
            [data['left-miss']['value'], data['right-miss']['value']], selected=first)
        if choice is None:
            raise ValueError('the declared initial observations did not yield a safe choice')
        ledger.put(choice)
        pre_success, _ = take_scene('01-before-success', 'left-miss')
        ledger.put(dict(kind='placement', id='first-success', world='ledge', decision=choice['id'],
                        position=choice['selected'], outcome=outcome(hidden_center, choice['selected'], 1)))
        complete, first_view = take_scene('02-first-success', 'first-success')
        remember('flower-success', first_view)
        change = role_transition(before, first_view)
        write(output / 'ROLE_CHANGE.json', change)
        ledger.put(dict(kind='note', id='role-change', text=json.dumps(change, ensure_ascii=False)))

        # Read the stored Flower through a fresh call/read, not the local variable.
        memory_scope = ledger.scope('memory-use')
        check_flowers(memory_scope, expected_flowers)
        memory = memory_scope['records']['flower-success']
        second_choice, second_plan = next_from_memory('choose-next', memory, memory_scope['records'],
            expected=expected_flowers['flower-success'], read_horizon=memory_scope['horizon'])
        if second_choice is None:
            raise ValueError('retained Flower could not support the next declared task')
        ledger.put(second_choice)
        ledger.put(dict(kind='placement', id='second-success', world='ledge',
                        decision=second_choice['id'], position=second_choice['selected'],
                        outcome=outcome(hidden_center, second_choice['selected'], 1)))
        final_scope, second_view = take_scene('03-second-success', 'second-success')
        # The final view is stored as well, then independently read and reconstructed.
        remember('flower-next', second_view)
        stored_final, stored_final_view = take_scene('04-retained-flowers', 'second-success')
        stale = ledger.send(dict(op='read', ticket=old_ticket, event='first-success'), allow_error=True)
        if stale['ok']:
            raise ValueError('a historical ticket gained a future source')
        write(output / 'HISTORICAL_READ_REFUSAL.json', stale)

        all_data = final_scope['records']
        raw_plan = plan(all_data['ledge']['value'],
            [all_data[e]['value'] for e in ('left-miss', 'right-miss', 'first-success')],
            [all_data['first-success']['value']['position']])
        endpoint_plan = plan(all_data['ledge']['value'],
            [all_data['first-success']['value']], [all_data['first-success']['value']['position']])
        if raw_plan != second_plan:
            raise ValueError('same complete facts and rules must match the Flower plan')
        controls = dict(same_full_facts_without_TE=raw_plan,
                        endpoint_only=endpoint_plan,
                        limited_observer=explain('first-success',
                            {k: v for k, v in complete['records'].items() if k != 'left-miss'},
                            observer='partial-recipient', horizon=complete['horizon']))
        write(output / 'CONTROLS.json', controls)
        crossings = intersections([before, first_view, second_view])
        write(output / 'INTERSECTIONS.json', crossings)
        write(output / 'CHECKPOINTS.json', checkpoints)
    finally:
        ledger.close()
    write(output / 'TRANSCRIPT.json', log)

    cold_results = []
    for descriptor in checkpoints:
        result, cold_log = readback(runtime, output, descriptor)
        cold_results.append(result)
        write(output / (descriptor['file'] + '.readback.json'), cold_log)
    # Check append-only preservation at the E4 journal level, independently of the model.
    originals = [json.loads((output / c['file']).read_bytes()) for c in checkpoints]
    prefix = all(later['journal'][:len(earlier['journal'])] == earlier['journal']
                 for earlier, later in zip(originals, originals[1:]))
    unchanged = all(hashlib.sha256((output / c['file']).read_bytes()).hexdigest() == c['sha256']
                    for c in checkpoints)
    if not prefix or not unchanged:
        raise ValueError('old source/journal/checkpoint was changed')
    summary = dict(schema=SCHEMA + '-result', first_plan=first_plan, next_plan=second_plan,
        first_endpoint='first-success', second_endpoint='second-success',
        recontextualized=change['recontextualized_observations'],
        first_success_roles=first_view['roles']['first-success'],
        later_first_success_roles=second_view['roles']['first-success'],
        shared_flower_relations=crossings, controls=controls,
        cold_readbacks=cold_results, old_journal_prefix_preserved=prefix,
        original_checkpoints_unchanged=unchanged, historical_ticket_rejects_future=True,
        fixed_driver=True, independent_recipient_trial=False,
        selection='one admissible position, selected explicitly or by the fixed driver',
        meaning_rule='declared finite endpoint reconstruction and minimal-support enumeration',
        subjective_experience_measurement='open research question; not measured by this run',
        unique_TE_effect_claimed=False)
    write(output / 'RESULT.json', summary)
    print(json.dumps(dict(ok=True, output=str(output), recontextualized=summary['recontextualized'],
                         choices=[first_plan['selected'], second_plan['selected']],
                         cold_readbacks=len(cold_results), full_fact_control_matches=True),
                     ensure_ascii=False))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', type=Path, default=ROOT / 'engine')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--first-position', type=int, default=3)
    args = parser.parse_args()
    run(args.runtime_root.resolve(), args.output_dir.resolve(), args.first_position)


if __name__ == '__main__':
    main()
