"""Check impression retention with synthetic source text and user-supplied phrase examples."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('impression_subject', ROOT/'protagonist.py')
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    tested_hash = hashlib.sha256((ROOT/'protagonist.py').read_bytes()).hexdigest()
    room = out/'synthetic-room'
    checks = []

    def check(name, condition):
        assert condition, name
        checks.append(dict(name=name, passed=True))

    def context(viewpoint='agent'):
        return model.context(room, viewpoint)

    def event(event_type, actor='human', **data):
        value = dict(type=event_type, actor=actor, **data)
        if actor == 'agent' and event_type != 'consent':
            value['based_on'] = context()['snapshot']
        return model.apply(room, value)

    def reject(name, value):
        before = context()['snapshot']
        try:
            model.apply(room, value)
        except model.ModelError:
            pass
        else:
            raise AssertionError(name)
        check(name, context()['snapshot'] == before)

    model.init(room)
    for actor in ['human', 'agent']:
        event('consent', actor=actor, choice='active')
    source = event('message', text='[中立の合成原文A]\n  余白\t🌿')['event_id']
    original = model.private_read(room, source)
    check('no impression inferred automatically from a source', context()['impressions'] == [])
    labels = ['この人、ずるい', 'この人には弱い', 'この人、妙に色っぽい', 'この人は私を困らせる']
    adopted = []
    for label in labels:
        adopted.append(event('impression', actor='agent', subject='human', label=label,
            associations=['[連想A]', '[連想B]'], refs=[source])['event_id'])
    packet = context()
    check('all four subjective phrases remain exact, without balanced-profile substitution',
        [row['label'] for row in packet['impressions']] == labels)
    check('associations and source provenance remain attached to the owner and subject', all(
        row['owner'] == 'agent' and row['subject'] == 'human' and row['source_refs'] == [source] and
        row['associations'] == ['[連想A]', '[連想B]'] for row in packet['impressions']))
    human_impression = event('impression', subject='agent', label='[人間視点の印象A]', associations=[], refs=[source])['event_id']
    check('agent view does not adopt the other participant impression',
        len(context()['impressions']) == 4 and len(context('human')['impressions']) == 1)
    event('future', id='plan-A', kind='proposal', text='[合成の予定A]')
    preserved_future = context()['future']
    old_impression = model.private_read(room, adopted[0])
    for number in range(10):
        event('message', text=f'[中立の合成入力 {number}]')
    packet = context()
    check('impressions persist beyond the recent eight-event source window',
        source not in [row['id'] for row in packet['past']] and [row['label'] for row in packet['impressions']] == labels)
    check('original source is still exact after rollover', model.private_read(room, source) == original)
    check('event storage crossed an Episode boundary',
        len(json.loads((room/'notebook/STATE.json').read_bytes())['episodes']) > 1)
    new_source = event('message', text='[中立の合成原文B]')['event_id']
    new_impression = event('impression', actor='agent', subject='human', label='[読み直した印象A]',
        associations=['[新しい連想C]'], refs=[source, new_source], replaces=adopted[0])['event_id']
    packet = context()
    new_row = next(row for row in packet['impressions'] if row['id'] == new_impression)
    check('revised impression links to its predecessor instead of overwriting it',
        new_row['previous_impression'] == adopted[0] and model.private_read(room, adopted[0]) == old_impression)
    check('other contradictory or partial impressions survive revision',
        [row['label'] for row in packet['impressions'] if row['id'] != new_impression] == labels[1:])
    old_released = model.private_read(room, adopted[1])
    event('release_impression', actor='agent', id=adopted[1])
    check('release changes adoption, while the past impression remains retrievable',
        adopted[1] not in [row['id'] for row in context()['impressions']] and model.private_read(room, adopted[1]) == old_released)
    reject('cannot replace the other participant private interpretation', dict(type='impression', actor='agent',
        subject='agent', label='[不正な置換]', associations=[], refs=[source], replaces=human_impression, based_on=context()['snapshot']))
    reject('cannot release another participant interpretation', dict(type='release_impression', actor='agent',
        id=human_impression, based_on=context()['snapshot']))
    reject('cannot silently move a prior impression to another subject', dict(type='impression', actor='agent',
        subject='agent', label='[不正な対象変更]', associations=[], refs=[source], replaces=adopted[2], based_on=context()['snapshot']))
    reject('cannot invent a missing source', dict(type='impression', actor='agent', subject='human',
        label='[未確認の印象]', associations=[], refs=['pr999999'], based_on=context()['snapshot']))
    check('impression updates do not turn a proposal into consent or change participation',
        context()['future'] == preserved_future and context()['present']['participation'] == dict(human='active', agent='active'))
    proc = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', str(ROOT/'protagonist.py'),
        'context', '--room', str(room)], capture_output=True, check=False)
    cold = json.loads(proc.stdout)
    check('separate process restores the currently adopted impression bundle',
        proc.returncode == 0 and cold['impressions'] == context()['impressions'])
    proc = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', str(ROOT/'protagonist.py'),
        'check', '--room', str(room)], capture_output=True, check=False)
    receipt = json.loads(proc.stdout)
    check('external integrity receipt exports no impressions or their wording',
        proc.returncode == 0 and receipt['ok'] and not receipt['contents_exported'] and
        not any(label in proc.stdout.decode('utf-8') for label in labels) and 'impressions' not in receipt)
    assert hashlib.sha256((ROOT/'protagonist.py').read_bytes()).hexdigest() == tested_hash
    result = dict(status='IMPRESSION_CHECKS_PASS', passed=len(checks), checks=checks,
        tested_executor_sha256=tested_hash, model_invocations=0, real_participants=0,
        observed_romantic_dialogue=False, role_behavior='not tested with an LLM',
        scope='Explicitly adopted subjective impressions are retained and returned; no automatic interpretation or felt-experience claim.')
    (out/'RESULT.json').write_bytes(model.encoded(result))
    print(json.dumps(dict(status=result['status'], passed=result['passed'], result=str(out/'RESULT.json'),
        model_invocations=0, role_behavior=result['role_behavior']), ensure_ascii=False))


if __name__ == '__main__':
    main()
