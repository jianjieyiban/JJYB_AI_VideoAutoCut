import copy
import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace

import pytest
from flask import Flask

from backend.api import advanced_routes, jianying_draft_api
from backend.config import paths
from backend.engine.multi_format_exporter import MultiFormatExporter


@pytest.fixture
def package_client(tmp_path, monkeypatch):
    monkeypatch.setattr(jianying_draft_api, 'PROJECT_ROOT', tmp_path)
    project = {'id': 'p', 'name': 'Test', 'config': {}, 'materials': []}
    app = Flask(__name__)
    jianying_draft_api.register_jianying_draft_routes(app, SimpleNamespace(get_project=lambda _: project))
    return app.test_client(), project, tmp_path


def read_timeline(client, root, payload):
    response = client.post('/api/jianying-drafts/export', json=payload)
    assert response.status_code == 200, response.json
    return json.loads((root / response.json['data']['directory'] / 'timeline.json').read_text(encoding='utf-8'))


def test_sequential_assets_duration_is_total(package_client):
    client, _, root = package_client
    for name in ('a.mp4', 'b.mp4'):
        (root / name).write_bytes(b'media')
    timeline = read_timeline(client, root, {'assets': [{'path': 'a.mp4', 'duration': 3}, {'path': 'b.mp4', 'duration': 5}]})
    assert timeline['duration'] == 8


@pytest.mark.parametrize('field', ['source', 'path', 'source_path'])
@pytest.mark.parametrize('from_project', [False, True])
def test_tracks_collect_and_rebase_assets_without_mutating_config(package_client, field, from_project):
    client, project, root = package_client
    (root / 'only.mp4').write_bytes(b'media')
    tracks = [{'type': 'video', 'clips': [{field: 'only.mp4', 'start': 3, 'duration': 5}]}]
    project['config']['tracks'] = tracks if from_project else []
    original = copy.deepcopy(project)
    payload = {'project_id': 'p', 'subtitles': [{'text': '字幕', 'start': 0, 'end': 10}]}
    if not from_project:
        payload['timeline'] = {'tracks': tracks, 'duration': 2}
    timeline = read_timeline(client, root, payload)
    asset = timeline['assets'][0]
    clip = timeline['tracks'][0]['clips'][0]
    assert clip[field] == asset['path']
    assert clip['asset_id'] == asset['id']
    assert (root / 'output' / 'jianying_drafts').exists()
    assert timeline['duration'] == 10
    assert project == original


def test_tracks_end_defines_duration(package_client):
    client, _, root = package_client
    (root / 'a.mp4').write_bytes(b'media')
    timeline = read_timeline(client, root, {'assets': ['a.mp4'], 'timeline': {'tracks': [{'clips': [{'start': 4, 'end': 12}]}]}})
    assert timeline['duration'] == 12


def test_outside_timeline_asset_is_not_exported(package_client, tmp_path):
    client, _, root = package_client
    outside = root.parent / (root.name + '-outside.mp4')
    outside.write_bytes(b'private')
    try:
        response = client.post('/api/jianying-drafts/export', json={'timeline': {'tracks': [{'clips': [{'source': str(outside)}]}]}})
        assert response.status_code == 400
    finally:
        outside.unlink()


@pytest.mark.parametrize('results, status, partial', [
    ({'srt': 'ERROR: failed'}, 500, False),
    ({'srt': 'ok.srt', 'ass': 'ERROR: failed'}, 200, True),
    ({}, 500, False),
    ({'srt': 'ok.srt'}, 200, False),
])
def test_multi_format_result_status(tmp_path, monkeypatch, results, status, partial):
    monkeypatch.setattr(paths, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(MultiFormatExporter, 'from_universal_timeline', lambda *_: SimpleNamespace(project_name='Test', duration=1, tracks=[]))
    monkeypatch.setattr(MultiFormatExporter, 'export_all_formats', lambda *_: results)
    app = Flask(__name__)
    app.register_blueprint(advanced_routes.advanced_bp)
    response = app.test_client().post('/api/advanced/export/multi-format', json={'timeline': {'duration': 1}, 'formats': list(results) or ['srt']})
    assert response.status_code == status
    assert response.json['code'] == (0 if status == 200 else 1)
    data = response.json['data']
    assert data['partial_success'] is partial
    assert bool(data['failures']) == (status != 200 or partial)


def extract_function(template, name):
    source = (Path(__file__).resolve().parents[1] / 'frontend' / 'templates' / template).read_text(encoding='utf-8')
    return re.search(r'        (?:async )?function ' + name + r'\([^\n]*\) \{.*?\n        \}', source, re.S).group()


def test_commentary_rejects_failed_or_invalid_export_responses():
    function = extract_function('commentary.html', 'psExportDraft')
    script = '''const assert = require('node:assert/strict');
const window = {currentProjectId: 'p', psSyncData: {timeline: [{subtitle_text: 'test'}]}};
const document = {getElementById() { return null; }};
const messages = [];
const Notification = Object.fromEntries(['warning','error','success'].map(k => [k, msg => messages.push([k,msg])]));
let response;
const API = {post: async () => response};
''' + function + '''
(async () => {
for (response of [{code:1,msg:'failed'}, {success:true}, {code:0,data:[]}, {code:0,data:{}}, {code:0,data:null}]) {
 messages.length = 0; const btn = {}; await psExportDraft(btn);
 assert.equal(messages.filter(x => x[0] === 'success').length, 0, JSON.stringify(response));
 assert.equal(messages[0][0], 'error'); assert.equal(btn.disabled, false);
}
for (const encrypted of [true, false]) {
 response = {code:0, data:{draft_path:'draft', native_jianying_project:true,client_version_info:{version:'6.0',draft_encrypted:encrypted}}};
 messages.length = 0; await psExportDraft({});
 assert.ok(messages.some(x => x[1].includes('兼容性未验证')));
 assert.ok(!messages.some(x => /无法打开|禁止打开|自动扫描|不加密，可直接打开/.test(x[1])));
}
})().catch(e => {process.stderr.write(e.stack);process.exitCode=1;});'''
    result = subprocess.run(['node'], input=script, text=True, capture_output=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr


def test_remix_compatibility_does_not_infer_openability():
    function = extract_function('remix.html', 'rxClientCompatibilityTip')
    script = function + '''
const assert = require('node:assert/strict');
for (const info of [null, {}, {version:'6.0',draft_encrypted:true}, {version:'5.9',draft_encrypted:false}]) {
 const tip = rxClientCompatibilityTip(info);
 assert.ok(tip.includes('兼容性未验证'));
 assert.ok(!/禁止打开|无法打开|不加密，可直接打开/.test(tip));
}
'''
    result = subprocess.run(['node'], input=script, text=True, capture_output=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
