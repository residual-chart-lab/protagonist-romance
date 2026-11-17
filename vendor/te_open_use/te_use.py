"""Optional source/interpretation/action notebook over the frozen TE runtime."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'runtime'))
from run_demo import Ledger

KINDS = ('interpretation', 'action', 'outcome', 'note')
USES = ('used', 'not_needed', 'not_chosen', 'not_considered', 'blocked', 'unknown')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def write_new(path, value):
    with path.open('xb') as stream:
        stream.write(encoded(value))


def verify_runtime():
    reference = json.loads((ROOT / 'RUNTIME_REFERENCE.json').read_bytes())
    for name, expected in reference['files'].items():
        if digest((ROOT / 'runtime' / name).read_bytes()) != expected:
            raise ValueError('fixed runtime differs: ' + name)


def index_commit(ws, state, op):
    write_new(ws / ('index-' + str(op).zfill(4) + '.json'), state)
    # Only the current pointer is replaced; checkpoints and old index snapshots remain.
    temp = ws / ('pointer-' + str(op).zfill(4) + '.tmp')
    write_new(temp, state)
    temp.replace(ws / 'STATE.json')


def open_ledger(ws, episode):
    cp = episode['checkpoint']
    path = (ws / cp['file']).resolve()
    if path.parent != ws:
        raise ValueError('checkpoint must remain in the notebook')
    return Ledger(ROOT / 'runtime/engine', [], path, cp['sha256'])


def find(state, identifier):
    for episode in state['episodes']:
        if identifier in episode['entries']:
            return episode, episode['entries'][identifier]
    raise ValueError('unknown record: ' + str(identifier))


def record(ledger, episode, value):
    if 128 - episode['commands'] < 24:
        raise ValueError('capacity low: use rollover; retained history will not be deleted')
    seq = ledger.put(value)
    cue = 'open-use/' + value['id']
    ledger.send(dict(op='goal', id='g-' + value['id'], text='Explicit retained notebook record.',
                     events=ledger.ids))
    ledger.send(dict(op='register', id='m-' + value['id'], goal='g-' + value['id'], cues=[cue],
                     summary=value['kind'] + ': ' + value['id']))
    episode['entries'][value['id']] = dict(cue=cue, kind=value['kind'], receipt_seq=seq,
                                         value_sha256=digest(encoded(value)))


def operations(ws):
    path = ws / 'OPERATIONS.jsonl'
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []


def observed(ops):
    reads = [op['id'] for op in ops if op.get('ok') and op['operation'] == 'read'
             and op.get('kind') == 'source']
    return dict(source_reads=reads, source_read_count=len(reads),
                successful_logged_operations=sum(bool(op.get('ok')) for op in ops),
                scope='Post-init commands in this notebook; probe/capabilities are separate. Not all model inputs or internal thoughts.')


@contextmanager
def notebook_lock(workspace):
    """Serialize processes sharing a notebook, including reads that append a log.

    The sibling lock file stays in place; the OS releases its lock if a process
    exits. Removing a lock file while another process has it open is unsafe.
    """
    workspace.parent.mkdir(parents=True, exist_ok=True)
    path = workspace.parent / ('.' + workspace.name + '.te-use.lock')
    with path.open('a+b') as stream:
        if path.stat().st_size == 0:
            stream.write(b'0')
            stream.flush()
        deadline = time.monotonic() + 90
        while True:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('notebook is busy; no operation was performed by this call')
                time.sleep(0.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def execute(args):
    if args.operation == 'capabilities' or args.workspace is None:
        return execute_serial(args)
    with notebook_lock(args.workspace.resolve()):
        return execute_serial(args)


def execute_serial(args):
    verify_runtime()
    ws = args.workspace.resolve() if args.workspace else None
    if args.operation == 'capabilities':
        return dict(available_commands=['init', 'status', 'put', 'read', 'record', 'usage', 'rollover', 'probe'],
                    runtime_integrity='verified', execution='this Python invocation succeeded',
                    storage='untested until init/probe', semantic_interpretation='caller supplied',
                    mode='choose operations as needed; no required Flower or reflection sequence')
    if ws is None:
        raise ValueError('--workspace is required for this operation')
    if args.operation == 'init':
        ws.mkdir(parents=True, exist_ok=False)
        ledger = Ledger(ROOT / 'runtime/engine', [])
        try:
            saved = ledger.save(ws / 'episode-001-op-0000.json')
        finally:
            ledger.close()
        state = dict(schema='te-open-use-v0.1', active=0, episodes=[dict(id='episode-001',
            checkpoint=saved, commands=saved['commands'], entries={})])
        index_commit(ws, state, 0)
        return dict(ok=True, state=state, usage_required=False)
    state = json.loads((ws / 'STATE.json').read_bytes())
    if state['schema'] != 'te-open-use-v0.1':
        raise ValueError('unexpected notebook schema')
    prior_ops = operations(ws)
    op_number = len(prior_ops) + 1
    log = dict(operation=args.operation, id=args.id, ok=False)
    ledger = None
    try:
        ep = state['episodes'][state['active']]
        if args.operation == 'status':
            result = dict(episodes=state['episodes'], remaining_commands=128 - ep['commands'],
                          observed=observed(prior_ops),
                          rollover_recommended=128 - ep['commands'] < 24)
        elif args.operation == 'read':
            old_ep, entry = find(state, args.id)
            ledger = open_ledger(ws, old_ep)
            scope = ledger.read_groups([entry['cue']])
            row = scope['records'][args.id]
            if row['seq'] != entry['receipt_seq'] or digest(encoded(row['value'])) != entry['value_sha256']:
                raise ValueError('source index differs from actual TE read')
            value = row['value']
            log['kind'] = entry['kind']
            result = dict(value=value, receipt_seq=row['seq'], read_horizon=scope['horizon'],
                          episode=old_ep['id'], original_checkpoint_sha256=old_ep['checkpoint']['sha256'])
        elif args.operation in ('put', 'record', 'usage'):
            if (not args.id or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,47}', args.id)
                    or '-piece-' in args.id or args.id.startswith('archive-')):
                raise ValueError('use a short unique record id without the reserved -piece- marker')
            if any(args.id in e['entries'] for e in state['episodes']):
                raise ValueError('record ids are append-only and globally unique in this notebook')
            refs = args.references.split(',') if args.references else []
            for ref in refs:
                find(state, ref)
            if args.operation == 'put':
                if not args.file:
                    raise ValueError('put requires --file containing UTF-8 text')
                raw = args.file.read_bytes()
                value = dict(kind='source', id=args.id, text=raw.decode('utf-8'),
                    original_utf8_sha256=digest(raw), original_bytes=len(raw),
                    provenance=dict(label=args.label or args.file.name, assurance='caller_declared'))
            elif args.operation == 'record':
                if not args.file:
                    raise ValueError('record requires --file containing a JSON object')
                payload = json.loads(args.file.read_bytes())
                if type(payload) is not dict:
                    raise ValueError('work record must be a JSON object')
                value = dict(kind=args.kind, id=args.id, payload=payload, references=refs,
                             relation_assurance='caller_declared; no semantic certification')
            else:
                if not args.use or not args.reason:
                    raise ValueError('usage requires --use and a short --reason')
                value = dict(kind='usage_report', id=args.id,
                    declared=dict(use=args.use, reason=args.reason, assurance='caller_self_report'),
                    observed=observed(prior_ops), references=refs,
                    notice='A choice not to use is not proof of inability or lack of an idea.')
            ledger = open_ledger(ws, ep)
            record(ledger, ep, value)
            saved = ledger.save(ws / (ep['id'] + '-op-' + str(op_number).zfill(4) + '.json'))
            ep.update(checkpoint=saved, commands=saved['commands'])
            index_commit(ws, state, op_number)
            log['kind'] = value['kind']
            result = dict(stored=True, id=args.id, kind=value['kind'], checkpoint=saved,
                          remaining_commands=128 - ep['commands'])
        elif args.operation == 'rollover':
            previous = dict(episode=ep['id'], checkpoint=ep['checkpoint'],
                            note='External archive pointer, not a merged certified TE history.')
            ledger = Ledger(ROOT / 'runtime/engine', [])
            new_ep = dict(id='episode-' + str(len(state['episodes']) + 1).zfill(3), commands=0, entries={})
            record(ledger, new_ep, dict(kind='archive_pointer', id='archive-' + new_ep['id'], payload=previous))
            saved = ledger.save(ws / (new_ep['id'] + '-op-' + str(op_number).zfill(4) + '.json'))
            new_ep.update(checkpoint=saved, commands=saved['commands'])
            state['episodes'].append(new_ep)
            state['active'] = len(state['episodes']) - 1
            index_commit(ws, state, op_number)
            result = dict(created_episode=new_ep['id'], retained_previous=previous,
                          original_sources_remain_readable_by_id=True)
        else:
            raise ValueError('unsupported operation')
        log.update(ok=True, result=result)
        return result
    except Exception as exc:
        log.update(error=type(exc).__name__, reason=str(exc), committed=False)
        raise
    finally:
        if ledger:
            write_new(ws / ('transport-' + str(op_number).zfill(4) + '.json'), ledger.log)
            ledger.close()
        with (ws / 'OPERATIONS.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(log, ensure_ascii=False) + '\n')


def probe(path):
    result = dict(schema='te-open-use-probe-v0.1', python=sys.version.split()[0],
                  capabilities={k: dict(status='untested') for k in ('write', 'process', 'save', 'restore', 'read')})
    stage, created = 'write', False
    if path.exists():
        result.update(ok=False, failure=dict(category='invalid_destination', type='FileExistsError',
            reason='Choose a new probe output directory. No write capability test was attempted.'))
        return result
    try:
        path.mkdir(parents=True, exist_ok=False)
        created = True
        result['capabilities']['write'] = dict(status='available', evidence='created new probe directory')
        value = dict(kind='source', id='probe-source', text='原文 🌿\n  改行と余白\t')
        stage = 'process'
        ledger = Ledger(ROOT / 'runtime/engine', [])
        try:
            result['capabilities']['process'] = dict(status='available', evidence='actual TE startup')
            ep = dict(commands=0, entries={})
            record(ledger, ep, value)
            stage = 'save'
            cp = ledger.save(path / 'probe.episode.json')
            result['capabilities']['save'] = dict(status='available', evidence=cp)
        finally:
            ledger.close()
        stage = 'restore'
        resumed = Ledger(ROOT / 'runtime/engine', [], path / cp['file'], cp['sha256'])
        try:
            result['capabilities']['restore'] = dict(status='available', evidence='fresh TE process, external SHA')
            stage = 'read'
            scope = resumed.read_groups([ep['entries']['probe-source']['cue']])
            if scope['records']['probe-source']['value'] != value:
                raise ValueError('probe source differs')
            result['capabilities']['read'] = dict(status='available', evidence='actual call/read, exact source')
        finally:
            resumed.close()
        result['ok'] = True
    except FileExistsError as exc:
        result.update(ok=False, failure=dict(category='invalid_destination', type=type(exc).__name__,
            reason=str(exc)))
    except Exception as exc:
        result['capabilities'][stage] = dict(status='unavailable', evidence=str(exc))
        result.update(ok=False, failure=dict(category='probe_execution_failure', stage=stage,
                                            type=type(exc).__name__, reason=str(exc)))
    if created:
        try:
            write_new(path / 'CAPABILITIES.json', result)
        except OSError as exc:
            result['report_save_failure'] = str(exc)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['capabilities','probe','init','status','put','read','record','usage','rollover'])
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--id')
    parser.add_argument('--file', type=Path)
    parser.add_argument('--label')
    parser.add_argument('--references')
    parser.add_argument('--kind', choices=KINDS, default='note')
    parser.add_argument('--use', choices=USES)
    parser.add_argument('--reason')
    args = parser.parse_args()
    try:
        if args.operation == 'probe':
            verify_runtime()
            if args.output is None:
                raise ValueError('probe requires a new --output directory')
            result = probe(args.output.resolve())
        else:
            result = execute(args)
        print(json.dumps(result, ensure_ascii=False))
        if result.get('ok') is False:
            raise SystemExit(2)
    except Exception as exc:
        print(json.dumps(dict(ok=False, error=type(exc).__name__, reason=str(exc),
                              execution_succeeded=False), ensure_ascii=False))
        raise SystemExit(2)


if __name__ == '__main__':
    main()
