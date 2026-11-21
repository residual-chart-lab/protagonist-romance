"""Package checked v0.4 code and unchanged TE; exclude all participant rooms."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parent
ARCHIVE_ROOT='protagonist-v04'
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def write(name,value): (ROOT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--checks',type=Path,required=True)
    parser.add_argument('--impressions-checks',type=Path,required=True)
    parser.add_argument('--recollections-checks',type=Path,required=True)
    parser.add_argument('--scene-checks',type=Path,required=True)
    parser.add_argument('--archive',type=Path)
    args=parser.parse_args()
    reports={key:json.loads(path.read_bytes()) for key,path in
        [('mechanism',args.checks),('impressions',args.impressions_checks),('recollections',args.recollections_checks),('scenes',args.scene_checks)]}
    executor_sha=sha(ROOT/'protagonist.py')
    for key,status in [('mechanism','MECHANISM_CHECKS_PASS'),('impressions','IMPRESSION_CHECKS_PASS'),('recollections','RECOLLECTION_CHECKS_PASS'),('scenes','SCENE_CHECKS_PASS')]:
        value=reports[key]
        assert value['status']==status and all(row['passed'] for row in value['checks'])
        assert value['passed']==len(value['checks'])
        assert value['model_invocations']==value['real_participants']==0
        assert value['tested_executor_sha256']==executor_sha
    assert reports['recollections']['legacy_v02_verified']
    assert reports['scenes']['legacy_v03_verified']
    summary=dict(version='0.4',delivery='preview.1',executor_sha256=executor_sha,
        **{key:dict(passed=value['passed'],checks=value['checks']) for key,value in reports.items()},
        legacy_v02_verified=True,legacy_v03_verified=True,model_invocations=0,real_participants=0,independent_audit=False,
        role_behavior='not tested with an LLM',observed_romantic_dialogue=False)
    write('CHECKS.json',summary)
    report = (
        '# v0.4 場面の印象と話題の再開・実行報告\n\n'
        '自分に残った場面の一行を本人の視点へ渡します。共有した言葉は別の発言として残ります。'
        '本人が継続を明示した話題の頼みは両者に届き、頼んだ本人が再開します。\n\n'
        + '合成入力の実行結果は、'
        + '、'.join(f"{label}{reports[key]['passed']}件" for key, label in
                   [('mechanism', '基本動作'), ('impressions', '人物の印象'), ('recollections', '再想起'), ('scenes', '場面と話題')])
        + 'です。v0.2とv0.3の部屋への追記と再生も確認しました。\n\n'
        '視点の選択はローカルホストが担います。保存は平文です。検査に実際の参加者やAIの応答生成は含まれません。\n'
    )
    (ROOT/'REPORT_JA.md').write_text(report,encoding='utf-8')
    write('DISTRIBUTION_READINESS.json',dict(status='TESTED_TECHNICAL_PREVIEW',version='0.4',delivery='preview.1',
        archive_root=ARCHIVE_ROOT,tested_executor_sha256=executor_sha,
        checks={key:value['passed'] for key,value in reports.items()},legacy_v02_verified=True,legacy_v03_verified=True,
        model_invocations=0,real_participants=0,independent_audit=False,participant_rooms_included=False))
    names=['protagonist.py','AGENT_ENTRY_JA.md','README_JA.md','START_HERE_JA.md','README.md','FOR_AGENTS.md',
        'RITUAL_RECOLLECTION_JA.md','verify_model.py','verify_impressions.py','verify_recollections.py','verify_scenes.py','build_package.py',
        'SOURCE_REFERENCE.json','PREVIOUS_VERSION.json','REPORT_JA.md','CHECKS.json','DISTRIBUTION_READINESS.json','.gitignore','.gitattributes']
    files=[ROOT/name for name in names]
    reference=json.loads((ROOT/'SOURCE_REFERENCE.json').read_bytes())
    assert len(reference['files'])==552
    for name,expected in reference['files'].items():
        path=ROOT/'vendor/te_open_use'/name
        assert sha(path)==expected
        files.append(path)
    assert not any(p.is_symlink() for p in files)
    assert not any(re.search(rb'C:(?:/|\\{1,4})Users(?:/|\\{1,4})sadat',p.read_bytes(),re.I) for p in files)
    manifest={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(files)}
    write('MANIFEST.json',manifest)
    archive=args.archive or ROOT.parent/(ROOT.name+'.zip')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(files+[ROOT/'MANIFEST.json']): bundle.write(path,arcname=ARCHIVE_ROOT+'/'+path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None and len(bundle.namelist())==len(manifest)+1
        for name,expected in manifest.items(): assert hashlib.sha256(bundle.read(ARCHIVE_ROOT+'/'+name)).hexdigest()==expected
    result=dict(status='TESTED_TECHNICAL_PREVIEW_PACKAGED',version='0.4',delivery='preview.1',package=str(archive),
        archive_root=ARCHIVE_ROOT,sha256=sha(archive),bytes=archive.stat().st_size,files=len(manifest)+1,
        checks={key:value['passed'] for key,value in reports.items()},no_participant_rooms_in_package=True,
        legacy_v02_verified=True,legacy_v03_verified=True,public_actions=0)
    (ROOT/'SHA256SUMS.txt').write_bytes(f"{result['sha256']}  {archive.name}\n".encode('utf-8'))
    write('PACKAGE.json',result)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__': main()
