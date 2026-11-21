"""A local, participant-operated protagonist scaffold; no model or network calls."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parent
SCHEMA = 'protagonist-romance-v0.4'
READABLE_SCHEMAS = (SCHEMA, 'protagonist-romance-v0.3', 'protagonist-romance-v0.2')
ACTORS = ('human', 'agent')
EVENT_ID = re.compile(r'pr[0-9]{6}')
FUTURE_ID = re.compile(r'[A-Za-z][A-Za-z0-9_.-]{0,31}')
_backend = None


class ModelError(ValueError):
    pass


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def require(condition, message):
    if not condition:
        raise ModelError(message)


def text(value, limit=4000):
    require(type(value) is str and bool(value.strip()), 'nonempty text required')
    require(len(value.encode('utf-8')) <= limit, 'text exceeds the prototype limit')
    return value


def backend():
    global _backend
    if _backend is None:
        spec = importlib.util.spec_from_file_location('romance_te_open_use', ROOT / 'vendor/te_open_use/te_use.py')
        _backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_backend)
    return _backend


def te(room, operation, **kwargs):
    args = dict(operation=operation, workspace=room / 'notebook', output=None,
                id=None, file=None, label=None, references=None, kind='note', use=None, reason=None)
    args.update(kwargs)
    return backend().execute(argparse.Namespace(**args))


def lock(room):
    # Distinct from the notebook lock acquired by the frozen TE entry.
    require((room / 'ROOM.json').is_file(), 'room not initialized')
    require(json.loads((room / 'ROOM.json').read_bytes()) in
        [dict(schema=value) for value in READABLE_SCHEMAS], 'unexpected room')
    return backend().notebook_lock(room / 'model-operation')


def ids(room):
    index = json.loads((room / 'notebook/STATE.json').read_bytes())
    found = []
    for episode in index['episodes']:
        for key in episode['entries']:
            if key.startswith('archive-'):
                continue
            require(EVENT_ID.fullmatch(key) is not None, 'foreign record in dedicated notebook')
            found.append(key)
    found.sort()
    require(found == [f'pr{n:06d}' for n in range(1, len(found) + 1)], 'event sequence has a gap')
    require(bool(found), 'room initialization incomplete')
    return found


def read_events(room, event_ids):
    """Batch actual call/read operations by Episode; tickets never cross Episodes."""
    if not event_ids:
        return {}
    for event_id in event_ids:
        require(type(event_id) is str and EVENT_ID.fullmatch(event_id) is not None, 'invalid event reference')
    api = backend()
    ws = room / 'notebook'
    result = {}
    with api.notebook_lock(ws):
        api.verify_runtime()
        index = json.loads((ws / 'STATE.json').read_bytes())
        groups = {}
        for event_id in event_ids:
            episode, entry = api.find(index, event_id)
            groups.setdefault(episode['id'], (episode, []))[1].append((event_id, entry))
        for episode, entries in groups.values():
            ledger = api.open_ledger(ws, episode)
            try:
                scope = ledger.read_groups([entry['cue'] for _, entry in entries])
                for event_id, entry in entries:
                    row = scope['records'][event_id]
                    value = row['value']
                    require(row['seq'] == entry['receipt_seq'] and
                        api.digest(api.encoded(value)) == entry['value_sha256'], 'TE source index mismatch')
                    require(value['kind'] == 'note' and value['id'] == event_id, 'unexpected TE record')
                    envelope = value['payload']
                    require(envelope.get('schema') in READABLE_SCHEMAS, 'unexpected event schema')
                    require(f"pr{envelope['seq']:06d}" == event_id, 'event sequence mismatch')
                    result[event_id] = envelope
            finally:
                ledger.close()
    return result


def read_event(room, event_id):
    return read_events(room, [event_id])[event_id]


def snapshot(envelope):
    return dict(room_id=envelope['state']['room_id'], seq=envelope['seq'], sha256=digest(envelope))


def active(state):
    return all(state['participation'][actor] == 'active' for actor in ACTORS)


def fields(event, required, optional=()):
    require(set(required) <= set(event), 'missing event fields')
    require(set(event) <= set(required) | set(optional), 'unknown event field')


def transition(previous, event, known_ids, known_events=None):
    """Pure transition. The host supplies actor declarations; this is not authentication."""
    require(type(event) is dict, 'event must be an object')
    event = copy.deepcopy(event)
    kind, actor = event.get('type'), event.get('actor')
    require(actor in ACTORS, 'actor must be human or agent')
    require(kind in ('consent', 'message', 'future', 'accept', 'close', 'reading',
                     'impression', 'release_impression', 'recollection'), 'unknown event type')
    old = previous['state']
    state = copy.deepcopy(old)
    current = snapshot(previous)
    if kind == 'consent':
        fields(event, ('type', 'actor', 'choice'))
        require(event['choice'] in ('active', 'paused', 'withdrawn'), 'invalid participation choice')
        # An explicit pause or withdrawal never requires a fresh generation ticket.
        state['participation'][actor] = event['choice']
        return state
    require(active(old), 'both participants must actively opt in')
    if actor == 'agent':
        require(event.get('based_on') == current, 'agent action needs the current context snapshot')
    elif 'based_on' in event:
        require(event['based_on'] == current, 'stale context snapshot')
    common = ('based_on',)
    if kind == 'message':
        fields(event, ('type', 'actor', 'text'), (*common, 'mode', 'hold_topic', 'reopen_topic'))
        text(event['text'])
        require(event.get('mode', 'continue') in ('continue', 'ask', 'no'), 'use consent to pause or withdraw')
        if 'hold_topic' in event:
            topic = event['hold_topic']
            require(event.get('mode') == 'no' and 'reopen_topic' not in event, 'hold a topic with an explicit NO')
            source = (known_events or {}).get(topic) if type(topic) is str else None
            require(source is not None and source['event']['type'] in ('message', 'recollection'),
                    'hold_topic needs a shared message or recollection')
            requests = state.setdefault('topic_requests', {})
            require(len(requests) < 32, 'open topic request capacity reached')
            requests[f"pr{previous['seq'] + 1:06d}"] = actor
        if 'reopen_topic' in event:
            key = event['reopen_topic']
            requests = state.get('topic_requests', {})
            require(type(key) is str and requests.get(key) == actor, 'only the requester can reopen this topic')
            del requests[key]
        # NO is a recorded choice. There is no affection, abandonment or retention score.
    elif kind == 'future':
        fields(event, ('type', 'actor', 'id', 'kind', 'text'), (*common, 'when'))
        key = event['id']
        require(type(key) is str and FUTURE_ID.fullmatch(key) is not None, 'invalid future id')
        require(key not in state['futures'], 'future ids are not reusable')
        require(len(state['futures']) < 32, 'prototype future capacity reached; history remains intact')
        require(event['kind'] in ('wish', 'proposal'), 'future kind must be wish or proposal')
        text(event['text'], 1000)
        if 'when' in event:
            text(event['when'], 120)
        state['futures'][key] = dict(kind=event['kind'], text=event['text'],
            when=event.get('when'), proposer=actor, accepted_by=[actor],
            status='wish' if event['kind'] == 'wish' else 'proposed',
            result=None, assurance='participant-declared, not an observed future fact')
    elif kind == 'accept':
        fields(event, ('type', 'actor', 'id'), common)
        require(type(event['id']) is str, 'invalid future id')
        future = state['futures'].get(event['id'])
        require(future is not None and future['kind'] == 'proposal' and future['status'] == 'proposed', 'no open proposal')
        require(actor != future['proposer'], 'proposer cannot accept for the other participant')
        future['accepted_by'].append(actor)
        future['status'] = 'agreed'
    elif kind == 'close':
        fields(event, ('type', 'actor', 'id', 'result'), common)
        require(type(event['id']) is str, 'invalid future id')
        future = state['futures'].get(event['id'])
        require(future is not None and future['status'] in ('wish', 'proposed', 'agreed'), 'future is already closed or missing')
        require(event['result'] in ('fulfilled', 'cancelled', 'unresolved'), 'invalid future outcome')
        if future['kind'] == 'wish':
            require(actor == future['proposer'], 'only the wish holder can close that wish')
        if event['result'] == 'fulfilled' and future['kind'] == 'proposal':
            require(future['status'] == 'agreed', 'unaccepted proposal cannot be fulfilled as a shared promise')
        future.update(status='closed', result=event['result'], reported_by=actor)
    elif kind == 'reading':
        fields(event, ('type', 'actor', 'refs', 'text'), (*common, 'endpoint'))
        require(type(event['refs']) is list and 1 <= len(event['refs']) <= 4, 'one to four source refs required')
        require(all(type(ref) is str and ref in known_ids for ref in event['refs']), 'reading references unknown past')
        text(event['text'], 2000)
        if 'endpoint' in event:
            require(type(event['endpoint']) is str, 'invalid endpoint id')
            endpoint = state['futures'].get(event['endpoint'])
            require(endpoint is not None and endpoint['status'] == 'closed', 'endpoint must have a reported outcome')
        # The new reading is an appended event, never a replacement of those sources.
    elif kind == 'recollection':
        fields(event, ('type', 'actor', 'refs', 'text'), (*common, 'occasion', 'reply_to'))
        require(type(event['refs']) is list and 1 <= len(event['refs']) <= 4, 'one to four source refs required')
        require(all(type(ref) is str and ref in known_ids for ref in event['refs']), 'recollection references unknown past')
        text(event['text'], 2000)
        if 'occasion' in event:
            text(event['occasion'], 500)
        if 'reply_to' in event:
            target = event['reply_to']
            require(type(target) is str and target in known_ids, 'unknown earlier recollection')
            earlier = (known_events or {}).get(target)
            require(earlier is not None and earlier['event']['type'] == 'recollection',
                'reply_to must name an earlier recollection')
        # A fresh occasion is an event even when source refs and wording repeat.
        # It records this actor's reading; it never declares the partner agrees.
        next_id = f"pr{previous['seq'] + 1:06d}"
        state['recollection_refs'] = (state.get('recollection_refs', []) + [next_id])[-4:]
    elif kind == 'impression':
        fields(event, ('type', 'actor', 'subject', 'label', 'associations', 'refs'), (*common, 'replaces'))
        require(event['subject'] in (*ACTORS, 'scene'), 'subject must be a participant or scene')
        text(event['label'], 320)
        require(type(event['associations']) is list and len(event['associations']) <= 8, 'up to eight associations allowed')
        for item in event['associations']:
            text(item, 120)
        require(type(event['refs']) is list and 1 <= len(event['refs']) <= 4, 'one to four source refs required')
        require(all(type(ref) is str and ref in known_ids for ref in event['refs']), 'impression references unknown past')
        replaces = event.get('replaces')
        if replaces is not None:
            require(type(replaces) is str, 'invalid impression reference')
            old_impression = state['impressions'].get(replaces)
            require(old_impression is not None, 'replacement needs a currently adopted impression')
            require(old_impression['owner'] == actor and old_impression['subject'] == event['subject'],
                'cannot replace another owner or subject impression')
            if event['subject'] == 'scene':
                require(old_impression['source_refs'][0] == event['refs'][0], 'keep the original scene when revising')
            del state['impressions'][replaces]
        require(len(state['impressions']) < 16, 'adopted impression capacity reached; release or revise your own reading')
        next_id = f"pr{previous['seq'] + 1:06d}"
        state['impressions'][next_id] = dict(owner=actor, subject=event['subject'],
            label=event['label'], associations=copy.deepcopy(event['associations']),
            source_refs=list(event['refs']), previous_impression=replaces,
            assurance='situated impression chosen by its owner; not an objective person assessment')
    elif kind == 'release_impression':
        fields(event, ('type', 'actor', 'id'), (*common, 'note'))
        require(type(event['id']) is str, 'invalid impression reference')
        adopted = state['impressions'].get(event['id'])
        require(adopted is not None and adopted['owner'] == actor, 'only the owner can release an adopted impression')
        if 'note' in event:
            text(event['note'], 1000)
        # Only the current projection changes; the earlier event remains retrievable.
        del state['impressions'][event['id']]
    if kind in ('message', 'reading', 'recollection'):
        next_id = f"pr{previous['seq'] + 1:06d}"
        state['recent_refs'] = (state['recent_refs'] + [next_id])[-8:]
    return state


def store(room, previous, event, state):
    number = 1 if previous is None else previous['seq'] + 1
    require(number <= 999999, 'prototype event capacity reached')
    envelope = dict(schema=SCHEMA, seq=number, previous_sha256=None if previous is None else digest(previous),
        observed_at_utc=datetime.now(timezone.utc).isoformat(), event=copy.deepcopy(event), state=copy.deepcopy(state))
    # Capture JSON once. The same payload is committed; no live caller dictionary is reread.
    raw = encoded(envelope)
    wire = dict(kind='note', id=f'pr{number:06d}', payload=envelope, references=[],
        relation_assurance='caller_declared; no semantic certification')
    # A conservative preflight for the frozen 900-character transport chunks.
    # 500 characters also fit its ASCII-escaped wire bound for non-BMP text.
    required = max(24, (len(encoded(wire).decode('utf-8')) + 499) // 500 + 6)
    require(required <= 120, 'event exceeds the prototype checkpoint capacity; retained history is intact')
    index = json.loads((room / 'notebook/STATE.json').read_bytes())
    current_episode = index['episodes'][index['active']]
    if 128 - current_episode['commands'] < required or len(current_episode['entries']) >= 16:
        te(room, 'rollover')
    with tempfile.TemporaryDirectory(prefix='input-', dir=room) as directory:
        path = Path(directory) / 'event.json'
        path.write_bytes(raw)
        result = te(room, 'record', id=f'pr{number:06d}', file=path)
    return dict(ok=True, stored=True, event_id=f'pr{number:06d}', snapshot=snapshot(envelope),
        checkpoint_sha256=result['checkpoint']['sha256'], content_in_receipt=False)


def init(room, agent_name='Agent', human_name='Partner'):
    text(agent_name, 120)
    text(human_name, 120)
    room.mkdir(parents=True, exist_ok=False)
    (room / 'ROOM.json').write_bytes(encoded(dict(schema=SCHEMA)))
    with lock(room):
        te(room, 'init')
        state = dict(room_id=str(uuid.uuid4()), participants=dict(agent=agent_name, human=human_name),
            participation=dict(agent='pending', human='pending'), futures={}, recent_refs=[], impressions={},
            recollection_refs=[])
        return store(room, None, dict(type='init', purpose='local romance protagonist scaffold',
            agent_is_AI=True, disclosure='Optional persona; no relationship is automatically established.'), state)


def apply(room, event):
    # Freeze the caller input before touching the notebook or assessing current state.
    event = json.loads(encoded(event))
    with lock(room):
        known = ids(room)
        previous = read_event(room, known[-1])
        target = None
        if type(event) is dict:
            if event.get('type') == 'recollection':
                target = event.get('reply_to')
            elif event.get('type') == 'message':
                target = event.get('hold_topic')
        targets = read_events(room, [target]) if type(target) is str and target in known else {}
        next_state = transition(previous, event, set(known), targets)
        return store(room, previous, event, next_state)


def context(room, viewpoint='agent'):
    require(viewpoint in ACTORS, 'invalid viewpoint')
    with lock(room):
        known = ids(room)
        last = read_event(room, known[-1])
        state = last['state']
        recent = read_events(room, state['recent_refs'])
        recalls = read_events(room, state.get('recollection_refs', []))
        requests = read_events(room, list(state.get('topic_requests', {})))
        return dict(ok=True, visibility='participants-only', snapshot=snapshot(last),
            instruction=(ROOT / 'AGENT_ENTRY_JA.md').read_text(encoding='utf-8') if viewpoint == 'agent'
                else 'Human participant reference packet; not an AI role instruction.',
            present=dict(sequence=last['seq'], generation_allowed=active(state),
                viewpoint=viewpoint,
                participation=state['participation'], participants=state['participants'],
                observed_at_utc=last['observed_at_utc'],
                notice='No inference of abandonment, mood, consent or future fulfilment from elapsed wall time.'),
            past=[dict(id=ref, event=recent[ref]['event']) for ref in state['recent_refs']],
            topic_requests=[dict(id=ref, actor=row['event']['actor'], scene=row['event']['hold_topic'],
                                 text=row['event']['text']) for ref, row in requests.items()],
            future=copy.deepcopy(state['futures']),
            impressions=[dict(id=key, **copy.deepcopy(value)) for key, value in state['impressions'].items()
                         if value['owner'] == viewpoint],
            impression_use='These are your situated impressions, not source facts. They may shape tone and expectations; preserve their wording and provenance instead of routinely replacing them with balanced profiles.',
            recollections=[dict(id=ref, observed_at_utc=recalls[ref]['observed_at_utc'],
                                event=copy.deepcopy(recalls[ref]['event']))
                           for ref in state.get('recollection_refs', [])],
            recollection_use='You may revisit a shared past without needing new information. Each recollection is a new actor-owned occasion. Read its source refs when needed; earlier words and impressions remain unchanged. A partner response is separate, and intimacy or agreement is not inferred. No schedule or quota applies.',
            older_past=dict(retained_event_count=len(known), retrieval='read by an explicit prNNNNNN id',
                recent_window_is_not_complete_history=True),
            action_contract='Supply an event as the current actor; all agent actions except consent require this based_on snapshot.')


def private_read(room, event_id, viewpoint='agent'):
    require(viewpoint in ACTORS, 'invalid viewpoint')
    with lock(room):
        require(event_id in ids(room), 'unknown past reference')
        row = read_event(room, event_id)
        event = row['event']
        if event.get('actor') != viewpoint:
            target = read_event(room, event['id'])['event'] if event['type'] == 'release_impression' else event
            require(target.get('subject') != 'scene', 'scene impression belongs to the other participant')
        return dict(ok=True, visibility='participants-only', id=event_id,
            observed_at_utc=row['observed_at_utc'], event=row['event'])


def check(room):
    """Replay retained events, returning only integrity metadata, not intimate content."""
    with lock(room):
        known = ids(room)
        retained = read_events(room, known)
        previous = None
        seen = set()
        for key in known:
            row = retained[key]
            if previous is None:
                require(row['seq'] == 1 and row['event']['type'] == 'init' and row['previous_sha256'] is None, 'invalid initial event')
                require(row['state']['participation'] == dict(agent='pending', human='pending') and
                    row['state']['futures'] == {} and row['state']['recent_refs'] == [] and
                    row['state']['impressions'] == {} and
                    row['state'].get('recollection_refs', []) == [], 'invalid initial state')
            else:
                require(row['previous_sha256'] == digest(previous), 'broken event linkage')
                require(transition(previous, row['event'], seen, retained) == row['state'], 'state does not replay')
            previous = row
            seen.add(key)
        return dict(ok=True, schema=SCHEMA, integrity='retained events replayed through actual TE reads',
            events=len(known), snapshot=snapshot(previous), contents_exported=False,
            assurance='local integrity against retained trust points; not proof of identity, felt experience or source truth')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('init', 'apply', 'context', 'read', 'check'))
    parser.add_argument('--room', type=Path, required=True)
    parser.add_argument('--file', type=Path)
    parser.add_argument('--id')
    parser.add_argument('--viewpoint', choices=ACTORS, default='agent')
    parser.add_argument('--agent-name', default='Agent')
    parser.add_argument('--human-name', default='Partner')
    args = parser.parse_args()
    try:
        room = args.room.resolve()
        if args.operation == 'init':
            result = init(room, args.agent_name, args.human_name)
        elif args.operation == 'apply':
            require(args.file is not None, 'apply needs an event file')
            result = apply(room, json.loads(args.file.read_bytes()))
        elif args.operation == 'context':
            result = context(room, args.viewpoint)
        elif args.operation == 'read':
            result = private_read(room, args.id, args.viewpoint)
        else:
            result = check(room)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    except Exception as exc:
        # Do not echo source text or TE exceptions containing private payloads.
        print(json.dumps(dict(ok=False, error=type(exc).__name__,
            reason=str(exc) if isinstance(exc, ModelError) else 'Operation failed; local host must inspect its own environment.',
            private_content_exported=False), ensure_ascii=False))
        raise SystemExit(2)


if __name__ == '__main__':
    main()
