"""Build the v0.2 implementation package, excluding all participant rooms."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--checks', type=Path, required=True)
    parser.add_argument('--impressions-checks', type=Path, required=True)
    args = parser.parse_args()
    mechanism = json.loads(args.checks.read_bytes())
    impressions = json.loads(args.impressions_checks.read_bytes())
    assert mechanism['status'] == 'MECHANISM_CHECKS_PASS'
    assert impressions['status'] == 'IMPRESSION_CHECKS_PASS'
    executor_sha = hashlib.sha256((ROOT/'protagonist.py').read_bytes()).hexdigest()
    for report in [mechanism, impressions]:
        assert all(row['passed'] for row in report['checks'])
        assert report['model_invocations'] == report['real_participants'] == 0
        assert report['tested_executor_sha256'] == executor_sha
    report = ('# v0.2 実装報告\n\n'
        '2026年11月17日。本人が選んだ偏った印象と、周辺の連想・原文への参照を保持する機構を追加。'
        '例：「この人には弱い」。公平な人物紹介への自動的な置換や数値への圧縮は行わない。\n\n'
        '印象の主体と対象を分け、最近の8件から外れても現在の文脈へ渡す。'
        '新しい印象は追加でき、読み直しは以前の印象へreplacesでつなぎ、採用解除は追記する。'
        '原文と当時の印象は保持。別の主体の印象を上書き・解除する操作は拒否する。\n\n'
        f'今回の実行器で機構 **{mechanism["passed"]}項目PASS**、'
        f'印象保持の追加確認 **{impressions["passed"]}項目PASS**。'
        '合成原文とアキが提示した例の文字列を用い、実際の恋愛会話は生成・閲覧していない。'
        '別プロセスでの印象の復元、最近の窓とEpisode境界を越えた保持、読み直しと採用解除、'
        '視点の分離、外側の検査へ本文が出ないことを確認した。\n\n'
        'AIモデル呼出し0、実在の参加者0。実モデルが印象を次の言葉にどう使うか、'
        '恋愛の質、実際の選好・満足、内的体験は未測定。指示文の意味的な遵守を実行器で保証しない。'
        '独立監査は未実施。数理核と固定TEは変更せず、この外側の印象機構を新しく検査した。\n\n'
        'schemaはv0.2。旧v0.1・v0.1.1と部屋は保持し、この版への自動変換は行っていない。'
        'ローカル保存は平文で、本人認証・暗号化は未実装。現在の表示上の視点分離を、管理者からの秘匿とは呼ばない。\n\n'
        'ZIPはコード・案内・固定依存物だけを含む。部屋・入力・恋愛ログは含めない。'
        '公開、配布、他のエージェントへの導入は行っていない。\n')
    (ROOT/'REPORT_JA.md').write_text(report, encoding='utf-8')
    summary = dict(version='0.2', executor_sha256=executor_sha,
        mechanism=dict(passed=mechanism['passed'], checks=mechanism['checks']),
        impressions=dict(passed=impressions['passed'], checks=impressions['checks']),
        model_invocations=0, real_participants=0, independent_audit=False,
        role_behavior='not tested with an LLM', observed_romantic_dialogue=False)
    (ROOT/'CHECKS.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    names = ['protagonist.py','AGENT_ENTRY_JA.md','README_JA.md','verify_model.py','verify_impressions.py',
        'build_package.py','SOURCE_REFERENCE.json','PREVIOUS_VERSION.json','REPORT_JA.md','CHECKS.json','.gitignore']
    files = [ROOT/name for name in names]
    reference = json.loads((ROOT/'SOURCE_REFERENCE.json').read_bytes())
    for name, sha in reference['files'].items():
        path = ROOT/'vendor/te_open_use'/name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sha
        files.append(path)
    assert not any(path.is_symlink() for path in files)
    manifest = {path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(files)}
    (ROOT/'MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    archive = ROOT.parent/(ROOT.name+'.zip')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(files+[ROOT/'MANIFEST.json']):
            bundle.write(path, arcname=ROOT.name+'/'+path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        assert len(bundle.namelist()) == len(manifest)+1
        for name, sha in manifest.items():
            assert hashlib.sha256(bundle.read(ROOT.name+'/'+name)).hexdigest() == sha
    result = dict(status='LOCAL_PROTOTYPE_PACKAGED', package=str(archive),
        sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), bytes=archive.stat().st_size,
        packaged_files=len(manifest)+1, mechanism_passed=mechanism['passed'], impressions_passed=impressions['passed'],
        no_participant_rooms_in_package=True, public_actions=0)
    (ROOT/'PACKAGE.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
