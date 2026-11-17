"""Mechanism checks using neutral synthetic inputs; no romantic conversations or LLM calls."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('protagonist_test_subject', ROOT / 'protagonist.py')
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    tested_executor_sha256 = hashlib.sha256((ROOT/'protagonist.py').read_bytes()).hexdigest()
    room = out / 'synthetic-room'
    checks = []

    def passed(name, condition):
        assert condition, name
        checks.append(dict(name=name, passed=True))

    def packet():
        return model.context(room)

    def event(event_type, actor='human', **data):
        value = dict(type=event_type, actor=actor, **data)
        if actor == 'agent' and event_type != 'consent':
            value['based_on'] = packet()['snapshot']
        return model.apply(room, value)

    def rejected(name, value):
        before = packet()['snapshot']
        try:
            model.apply(room, value)
        except model.ModelError:
            pass
        else:
            raise AssertionError(name)
        passed(name, packet()['snapshot'] == before)

    model.init(room, agent_name='Synthetic Agent', human_name='Synthetic Partner')
    passed('initialization does not assume a relationship', not packet()['present']['generation_allowed'])
    rejected('one-sided input cannot start the relationship', dict(type='message', actor='human', text='[合成入力A]'))
    event('consent', choice='active')
    passed('human opt-in does not speak for the agent', not packet()['present']['generation_allowed'])
    event('consent', actor='agent', choice='active')
    passed('both declared choices enable this local role', packet()['present']['generation_allowed'])
    first = event('message', text='[合成原文A]\n  改行・余白\t🌿')
    first_id = first['event_id']
    stale = packet()['snapshot']
    event('message', text='[合成追加入力B]')
    rejected('stale draft cannot overwrite an intervening turn',
        dict(type='message', actor='agent', text='[合成返答]', based_on=stale))
    rejected('agent cannot omit its observation point', dict(type='message', actor='agent', text='[合成返答]'))
    event('message', actor='agent', text='[合成NO]', mode='no')
    passed('NO does not damage participation or create a penalty', packet()['present']['generation_allowed'])
    event('future', id='wish-A', kind='wish', text='[合成の願いA]')
    rejected('wish is not the other participant consent',
        dict(type='accept', actor='agent', id='wish-A', based_on=packet()['snapshot']))
    event('future', actor='agent', id='plan-A', kind='proposal', text='[合成の予定A]', when='1900-01-01')
    rejected('proposer cannot accept on behalf of the other participant',
        dict(type='accept', actor='agent', id='plan-A', based_on=packet()['snapshot']))
    rejected('unaccepted future is not a fulfilled shared promise',
        dict(type='close', actor='human', id='plan-A', result='fulfilled'))
    event('accept', id='plan-A')
    passed('mutual acceptance is explicit; elapsed dates do not imply failure', packet()['future']['plan-A']['status'] == 'agreed')
    event('close', actor='agent', id='plan-A', result='fulfilled')
    source_before = model.private_read(room, first_id)
    event('reading', actor='agent', refs=[first_id], endpoint='plan-A', text='[終端後に加えた読みA]')
    passed('later interpretation is visible without changing original text',
        model.private_read(room, first_id) == source_before and
        any(e['event'].get('text') == '[終端後に加えた読みA]' for e in packet()['past']))
    rejected('cannot retrospectively edit the past', dict(type='edit', actor='human', id=first_id, text='[変更]'))
    rejected('cannot cite a nonexistent past', dict(type='reading', actor='human', refs=['pr999999'], text='[読み]'))
    rejected('cannot recycle an old future identity', dict(type='future', actor='human', id='plan-A', kind='proposal', text='[別の予定]'))
    old_checkpoints = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (room/'notebook').glob('*.json') if p.name.startswith('episode-')}
    for n in range(20):
        event('message', text=f'[中立の合成入力 {n}]')
    index = json.loads((room/'notebook/STATE.json').read_bytes())
    passed('registration capacity rolls over before command capacity is exhausted',
        len(index['episodes'][0]['entries']) == 16 and index['episodes'][0]['commands'] < 104)
    passed('capacity rollover retains old episode checkpoints', len(index['episodes']) > 1 and
        all(hashlib.sha256((room/'notebook'/name).read_bytes()).hexdigest() == sha for name, sha in old_checkpoints.items()))
    passed('original is still retrievable after leaving the recent window',
        first_id not in [row['id'] for row in packet()['past']] and model.private_read(room, first_id) == source_before)
    event('consent', actor='agent', choice='paused')
    rejected('pause stops role actions without deleting history', dict(type='message', actor='human', text='[停止中の入力]'))
    passed('participant can still retrieve their retained record after pausing', model.private_read(room, first_id) == source_before)
    event('consent', actor='agent', choice='active')
    other = out/'other-room'
    model.init(other)
    rejected('another room snapshot is not transferable',
        dict(type='message', actor='agent', text='[別室の返答]', based_on=model.context(other)['snapshot']))
    event('consent', choice='withdrawn')
    passed('withdrawal is explicit and survives restoration', not packet()['present']['generation_allowed'])
    process = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', str(ROOT/'protagonist.py'),
        'read', '--room', str(room), '--id', first_id], capture_output=True, check=False)
    cold_read = json.loads(process.stdout)
    passed('separate process retrieves exact original bytes as UTF-8 text', process.returncode == 0 and cold_read == source_before)
    process = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', str(ROOT/'protagonist.py'),
        'check', '--room', str(room)], capture_output=True, check=False)
    receipt = json.loads(process.stdout)
    passed('separate process replays all committed transitions', process.returncode == 0 and receipt['ok'])
    passed('observer check exposes no dialogue or private interpretation',
        b'\xe5\x90\x88\xe6\x88\x90' not in process.stdout and not receipt['contents_exported'] and
        all(key not in receipt for key in ['event', 'past', 'future', 'state', 'participants', 'impressions']))
    reference = json.loads((ROOT/'SOURCE_REFERENCE.json').read_bytes())
    passed('vendored TE entry and runtime are byte-identical', all(
        hashlib.sha256((ROOT/'vendor/te_open_use'/name).read_bytes()).hexdigest() == sha for name, sha in reference['files'].items()))
    source_available = Path(reference['source']).is_dir()
    if source_available:
        passed('original fixed distribution remains unchanged', all(
            hashlib.sha256((Path(reference['source'])/name).read_bytes()).hexdigest() == sha for name, sha in reference['files'].items()))
    result = dict(status='MECHANISM_CHECKS_PASS', checks=checks, passed=len(checks),
        all_inputs='neutral synthetic fixtures; no romantic exchanges generated',
        model_invocations=0, real_participants=0, independent_audit=False,
        relationship_quality='not tested', felt_experience='not tested',
        external_messages=0, private_real_dialogue_read=False,
        original_distribution_check='passed' if source_available else 'not available on this host; vendored copies checked',
        tested_executor_sha256=tested_executor_sha256,
        separate_process_receipt=receipt)
    (out/'RESULT.json').write_bytes(model.encoded(result))
    assert hashlib.sha256((ROOT/'protagonist.py').read_bytes()).hexdigest() == tested_executor_sha256
    print(json.dumps(dict(status=result['status'], passed=result['passed'], result=str(out/'RESULT.json'),
        model_invocations=0, relationship_quality='not tested', real_participants=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
