"""Package checked v0.3 code and unchanged TE; exclude all participant rooms."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parent
ARCHIVE_ROOT='protagonist-v03'
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def write(name,value): (ROOT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--checks',type=Path,required=True)
    parser.add_argument('--impressions-checks',type=Path,required=True)
    parser.add_argument('--recollections-checks',type=Path,required=True)
    args=parser.parse_args()
    reports={key:json.loads(path.read_bytes()) for key,path in
        [('mechanism',args.checks),('impressions',args.impressions_checks),('recollections',args.recollections_checks)]}
    executor_sha=sha(ROOT/'protagonist.py')
    for key,status in [('mechanism','MECHANISM_CHECKS_PASS'),('impressions','IMPRESSION_CHECKS_PASS'),('recollections','RECOLLECTION_CHECKS_PASS')]:
        value=reports[key]
        assert value['status']==status and all(row['passed'] for row in value['checks'])
        assert value['passed']==len(value['checks'])
        assert value['model_invocations']==value['real_participants']==0
        assert value['tested_executor_sha256']==executor_sha
    assert reports['recollections']['legacy_v02_verified']
    summary=dict(version='0.3',delivery='preview.1',executor_sha256=executor_sha,
        **{key:dict(passed=value['passed'],checks=value['checks']) for key,value in reports.items()},
        legacy_v02_verified=True,model_invocations=0,real_participants=0,independent_audit=False,
        role_behavior='not tested with an LLM',observed_romantic_dialogue=False)
    write('CHECKS.json',summary)
    counts=' + '.join(f'{value["passed"]} {key} checks' for key,value in reports.items())
    readme=ROOT/'README.md'
    readme.write_text(readme.read_text(encoding='utf-8').replace('CHECK_SUMMARY',counts),encoding='utf-8')
    report=('# v0.3 儀式的再想起・実装報告\n\n2026年11月17日。アキの提案を受け、'
        '「必要な情報はなくても、もう一度あの話をしたい」を選べるrecollectionを追加。'
        '元の出来事、当時の印象、今回の読み、相手の応答を分けて保存する。'
        '同じ参照・同じ文面も新しいイベントとなり、相手の応答は別actorのイベントとしてreply_toでつながる。'
        '原文や人物像を自動で書き換えず、相手の同意・親密さの増加も自動生成しない。\n\n'
        '最近の再想起4件を通常8件の会話窓とは別に渡す。それ以前も原文とともに保持し、'
        '再想起自体を次の参照元にできる。繰り返す義務、定期実行、肯定の目標値は置かない。\n\n'
        +f'今回の実行器で、機構 **{reports["mechanism"]["passed"]}件**、印象 **{reports["impressions"]["passed"]}件**、'
        +f'再想起・旧部屋継続 **{reports["recollections"]["passed"]}件**がPASS。'
        '中立の合成入力のみを使い、実在する二人の恋愛は生成・閲覧していない。'
        '別プロセス復元、同文の再想起、別主体の応答、変化した読み、窓とEpisodeを越えた原文保持、'
        'v0.2実行器で作成した部屋への追記と混在履歴の再生を確認した。\n\n'
        'schemaはv0.3。v0.2の過去のイベントとROOM.jsonを変更せず、追加分だけ新schemaを使う。'
        '新schemaを追記した部屋はv0.3で扱う。v0.1系の部屋は対象外。\n\n'
        'AIモデル呼出し0、実在の参加者0。自然な再想起、恋愛の質、選好、満足、主観的体験は未測定。'
        '指示の意味的遵守の保証と独立監査はない。552件の固定TE依存物は同一で、既存監査を本版へ拡張しない。\n\n'
        '部屋と入力はZIPに入れず、当事者のログ提出も求めない。保存は平文で認証・暗号化はない。'
        '配布物の取得・起動確認と公開の実施状況は、配布側の別の記録で扱う。\n')
    (ROOT/'REPORT_JA.md').write_text(report,encoding='utf-8')
    write('DISTRIBUTION_READINESS.json',dict(status='TESTED_TECHNICAL_PREVIEW',version='0.3',delivery='preview.1',
        archive_root=ARCHIVE_ROOT,tested_executor_sha256=executor_sha,
        checks={key:value['passed'] for key,value in reports.items()},legacy_v02_verified=True,
        model_invocations=0,real_participants=0,independent_audit=False,participant_rooms_included=False))
    names=['protagonist.py','AGENT_ENTRY_JA.md','README_JA.md','START_HERE_JA.md','README.md','FOR_AGENTS.md',
        'RITUAL_RECOLLECTION_JA.md','verify_model.py','verify_impressions.py','verify_recollections.py','build_package.py',
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
    archive=ROOT.parent/(ROOT.name+'.zip')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(files+[ROOT/'MANIFEST.json']): bundle.write(path,arcname=ARCHIVE_ROOT+'/'+path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None and len(bundle.namelist())==len(manifest)+1
        for name,expected in manifest.items(): assert hashlib.sha256(bundle.read(ARCHIVE_ROOT+'/'+name)).hexdigest()==expected
    result=dict(status='TESTED_TECHNICAL_PREVIEW_PACKAGED',version='0.3',delivery='preview.1',package=str(archive),
        archive_root=ARCHIVE_ROOT,sha256=sha(archive),bytes=archive.stat().st_size,files=len(manifest)+1,
        checks={key:value['passed'] for key,value in reports.items()},no_participant_rooms_in_package=True,
        legacy_v02_verified=True,public_actions=0)
    write('PACKAGE.json',result)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__': main()
