"""Exercise participant views, explicit sharing and topic requests through the CLI."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--legacy-package', type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    room = out / 'room'
    runner = Path(__file__).with_name('protagonist.py').resolve()
    legacy = args.legacy_package / 'protagonist.py' if args.legacy_package else runner
    if args.legacy_package:
        assert hashlib.sha256(legacy.read_bytes()).hexdigest() == '56b5f942ff1a9794e71eac78a79154385df1728f3dc46409038e57419edf0dde'
    checks = []

    def check(name, condition):
        assert condition, name
        checks.append(dict(name=name, passed=True))

    def cli(op, *flags, program=runner, reject=False):
        command = [sys.executable, '-I', '-B', '-X', 'utf8', str(program), op, '--room', str(room), *flags]
        process = subprocess.run(command, capture_output=True)
        result = json.loads(process.stdout)
        assert process.returncode == (2 if reject else 0) and result['ok'] == (not reject), result
        return result

    snap = cli('init', program=legacy)['snapshot']

    def put(kind, actor, *, program=runner, reject=False, **fields):
        nonlocal snap
        event = dict(type=kind, actor=actor, **fields)
        if actor == 'agent' and kind != 'consent':
            event['based_on'] = snap
        path = out / 'input.json'
        path.write_text(json.dumps(event, ensure_ascii=False), encoding='utf-8')
        result = cli('apply', '--file', str(path), program=program, reject=reject)
        if not reject:
            snap = result['snapshot']
            return result['event_id']
        return result

    for actor in ('human', 'agent'):
        put('consent', actor, choice='active', program=legacy)
    anchor = put('message', 'human', text='雨、やんだよ。', program=legacy)
    header = (room / 'ROOM.json').read_bytes()
    source = cli('read', '--id', anchor, program=legacy)
    old_context = cli('context', program=legacy)
    check('existing room opens at the same snapshot', cli('context')['snapshot'] == old_context['snapshot'])
    words = '雨がやんだのが、ちょっと残念だった。'
    scene = dict(subject='scene', associations=[], refs=[anchor])
    mine = put('impression', 'agent', label=words, **scene)
    theirs = put('impression', 'human', label='帰りに歌った変な歌。', **scene)
    hold = put('message', 'human', mode='no', hold_topic=anchor, text='雨宿りの話は、私から切り出すまで。')
    put('message', 'agent', text='私が再開する', reopen_topic=hold, reject=True)
    put('message', 'human', mode='no', text='今はやめておこう')
    for i in range(8):
        put('message', 'human', text=f'別の話 {i}')
    agent = cli('context')
    human = cli('context', '--viewpoint', 'human')
    check('each viewpoint restores only its own impression of the same scene',
          [i['id'] for i in agent['impressions']] == [mine] and [i['id'] for i in human['impressions']] == [theirs])
    check('unspoken words stay outside partner context',
          words not in json.dumps(human, ensure_ascii=False) and agent['impressions'][0]['label'] == words)
    check('one explicit request survives the recent window in both views',
          hold not in [i['id'] for i in agent['past']] and agent['topic_requests'] == human['topic_requests'] ==
          [dict(id=hold, actor='human', scene=anchor, text='雨宿りの話は、私から切り出すまで。')])
    check('partner read omits private words', words not in json.dumps(
          cli('read', '--id', mine, '--viewpoint', 'human', reject=True), ensure_ascii=False))
    cli('read', '--id', theirs, reject=True)
    put('message', 'human', reopen_topic=hold, text='あの雨の日の話、しよう。')
    check('requester can reopen without changing the impressions',
          cli('context')['topic_requests'] == [] and cli('context')['impressions'] == agent['impressions'])
    revised = put('impression', 'agent', label='あの沈黙が好きだった。', replaces=mine, **scene)
    put('impression', 'human', label='置換', replaces=revised, reject=True, **scene)
    spoken = put('message', 'agent', text='あの沈黙が好きだった。')
    partner = cli('context', '--viewpoint', 'human')
    check('the partner sees the words chosen for sharing as a separate event',
          partner['past'][-1]['id'] == spoken and partner['past'][-1]['event']['text'] == 'あの沈黙が好きだった。'
          and partner['impressions'] == human['impressions'])
    check('revision retains original wording and its link',
          cli('read', '--id', mine)['event']['label'] == words and cli('read', '--id', revised)['event']['replaces'] == mine)
    released = put('release_impression', 'agent', id=revised, note='自分だけの追記')
    cli('read', '--id', released, '--viewpoint', 'human', reject=True)
    check('release removes adoption and retains both the old impression and the owner’s note',
          cli('context')['impressions'] == [] and cli('read', '--id', released)['event']['note'] == '自分だけの追記')
    check('history and room header survive append and fresh replay',
          (room / 'ROOM.json').read_bytes() == header and cli('read', '--id', anchor) == source and cli('check')['ok'])
    report = dict(status='SCENE_CHECKS_PASS', passed=len(checks), checks=checks, model_invocations=0,
                  real_participants=0, legacy_v03_verified=bool(args.legacy_package),
                  tested_executor_sha256=hashlib.sha256(runner.read_bytes()).hexdigest())
    (out / 'RESULT.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(dict(status=report['status'], passed=len(checks))))


if __name__ == '__main__':
    main()
