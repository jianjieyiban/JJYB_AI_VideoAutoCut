import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


TEMPLATE = Path(__file__).resolve().parents[1] / 'frontend' / 'templates' / 'remix.html'


class RemixExportStateTests(unittest.TestCase):
    def run_js(self, body):
        self.assertIsNotNone(shutil.which('node'), 'Node.js is required for the frontend regression tests')
        source = TEMPLATE.read_text(encoding='utf-8')
        names = [
            'getCompletedRemixResult', 'rxNormalizeExportClip', 'getRemixExportTimeline',
            'updateRemixExportAvailability', 'clearRemixCompletedResult',
            'monitorRemixProgress', 'showRemixResult', 'exportJianyingDraft',
            'generalModeRemix', 'musicBeatRemix', 'processRemix',
        ]
        functions = []
        for name in names:
            match = re.search(r'        (?:async )?function ' + name + r'\([^\n]*\) \{.*?\n        \}', source, re.S)
            self.assertIsNotNone(match, name)
            functions.append(match.group())
        do_start = re.search(r'            const doStart = async \(\) => \{.*?\n            \};', source, re.S)
        script = r'''
const assert = require('node:assert/strict');
const window = globalThis;
const elements = new Map();
const document = {getElementById(id) {
    if (!elements.has(id)) elements.set(id, {style: {}, value: '', checked: false, setAttribute() {}, load() {}});
    return elements.get(id);
}};
const Notification = {success() {}, warning() {}, error() {}, info() {}};
window.Notification = Notification;
console.log = console.error = () => {};
let uploadedFiles = [], rxSegmentData = null, selectedBGM = '', selectedStyle = 'dynamic';
let selectedRemixMode = 'general', selectedTransition = 'fade', selectedVisionModel = '';
let selectedRemixTTSEngine = 'edge-tts', selectedRemixVoice = '';
const projectName = 'new', durationMode = 'custom', targetSeconds = 10;
const autoHighlight = false, autoTransition = false, autoBGM = false, resolvedMusicPath = '';
const updateProgress = () => {};
const simplifyBackendError = (message) => message;
const rxEscape = String, rxFormatData = JSON.stringify;
const getRemixVideoPaths = () => ['source.mp4'];
const rxEnsureUploadedVideoPaths = async () => ['source.mp4'];
let getRequiredRemixDuration = () => 10;
const getRemixDurationMode = () => 'custom';
const remixEffects = [];
const setRemixLoading = () => {};
const setRemixFailure = (message) => remixEffects.push(['failure', message]);
const renderRemixResult = (html) => remixEffects.push(['render', html]);
const setRemixDraftDirectoryStatus = () => {};
const resolveRemixJianyingDraftDir = async () => 'drafts';
const clip = {source_video: 'source.mp4', source_start: 1, source_end: 3};
const result = (project = 'A', task = 'task-A') => ({status: 'completed', project_id: project, task_id: task, timeline: [clip]});
const keys = ['remixCompletedResult', 'remixLastResult', 'remixGeneratedTimeline', 'remixResultData', 'remixGeneralResult', 'remixMusicBeatResult', 'remixPlan'];
function seed() {
    currentRemixProjectId = 'A'; currentRemixTaskId = 'task-A';
    for (const key of keys) window[key] = key === 'remixGeneratedTimeline' ? [clip] : result();
}
function respond(data) { return {ok: true, text: async () => JSON.stringify({code: 0, data}), json: async () => ({code: 0, data})}; }
async function poll(data) {
    fetch = async () => respond(data);
    await monitorRemixProgress(data.task_id || currentRemixTaskId);
    await new Promise(resolve => setImmediate(resolve));
}
'''
        script += '\n'.join(functions) + '\n' + do_start.group() + '\n'
        script += '(async () => {\n' + body + '\n})().catch(error => { process.stderr.write(error.stack); process.exitCode = 1; });'
        completed = subprocess.run(['node'], input=script, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_clear_removes_every_old_candidate(self):
        self.run_js('''seed(); clearRemixCompletedResult();
for (const key of keys) assert.equal(window[key], null, key);
assert.equal(getRemixExportTimeline(), null);''')

    def test_clear_advances_request_generation(self):
        self.run_js('''clearRemixCompletedResult();
const generation = window.remixRequestGeneration;
assert.equal(typeof generation, 'number');
clearRemixCompletedResult();
assert.equal(window.remixRequestGeneration, generation + 1);''')

    def test_advanced_out_of_order_responses_preserve_latest_result(self):
        modes = ['generalModeRemix', 'musicBeatRemix']
        for first in modes:
            for second in modes:
                for outcome in ['success', 'failure', 'rejection']:
                    with self.subTest(first=first, second=second, outcome=outcome):
                        self.run_js(f'''seed(); selectedBGM = 'bgm.mp3';
Notification.success = message => remixEffects.push(['success', message]);
Notification.error = message => remixEffects.push(['error', message]);
const requests = [];
fetch = () => new Promise((resolve, reject) => requests.push({{resolve, reject}}));
const firstPending = {first}();
await new Promise(resolve => setImmediate(resolve));
const secondPending = {second}();
await new Promise(resolve => setImmediate(resolve));
assert.equal(requests.length, 2);
requests[1].resolve(respond({{timeline: [clip], project_id: 'A', output_file: 'new.mp4'}}));
await secondPending;
const chosen = getRemixExportTimeline().result;
assert.equal(chosen.output_file, 'new.mp4');
const snapshot = JSON.stringify([keys.map(key => window[key]), remixEffects, [...elements]]);
if ({json.dumps(outcome)} === 'rejection') requests[0].reject(new Error('late failure'));
else if ({json.dumps(outcome)} === 'failure') requests[0].resolve({{json: async () => ({{code: 1, msg: 'late failure'}})}});
else requests[0].resolve(respond({{timeline: [clip], project_id: 'A', output_file: 'old.mp4'}}));
await firstPending;
assert.equal(getRemixExportTimeline().result, chosen);
assert.equal(JSON.stringify([keys.map(key => window[key]), remixEffects, [...elements]]), snapshot);''')

    def test_advanced_project_switch_ignores_pending_response(self):
        for name in ['generalModeRemix', 'musicBeatRemix']:
            for outcome in ['success', 'failure', 'rejection']:
                with self.subTest(mode=name, outcome=outcome):
                    self.run_js(f'''seed(); selectedBGM = 'bgm.mp3';
Notification.success = message => remixEffects.push(['success', message]);
Notification.error = message => remixEffects.push(['error', message]);
let resolveRequest, rejectRequest;
fetch = () => new Promise((resolve, reject) => {{ resolveRequest = resolve; rejectRequest = reject; }});
const pending = {name}();
await new Promise(resolve => setImmediate(resolve));
currentRemixProjectId = 'B'; currentRemixTaskId = 'task-B';
remixCompletedResult = result('B', 'task-B');
const chosen = getRemixExportTimeline().result;
const snapshot = JSON.stringify([keys.map(key => window[key]), remixEffects, [...elements]]);
if ({json.dumps(outcome)} === 'rejection') rejectRequest(new Error('late failure'));
else if ({json.dumps(outcome)} === 'failure') resolveRequest({{json: async () => ({{code: 1, msg: 'late failure'}})}});
else resolveRequest(respond({{timeline: [clip], project_id: 'A', output_file: 'old.mp4'}}));
await pending;
assert.equal(currentRemixProjectId, 'B');
assert.equal(currentRemixTaskId, 'task-B');
assert.equal(getRemixExportTimeline().result, chosen);
assert.equal(JSON.stringify([keys.map(key => window[key]), remixEffects, [...elements]]), snapshot);''')

    def test_new_confirmed_task_clears_before_request(self):
        self.run_js('''seed();
document.getElementById('sceneSegmentation').value = 'none';
fetch = async () => { assert.equal(getRemixExportTimeline(), null); throw new Error('upload/create failed'); };
await doStart();
assert.equal(getRemixExportTimeline(), null);''')

    def test_failed_task_removes_all_candidates(self):
        self.run_js('''seed(); await poll({status: 'failed', task_id: 'task-A', error: 'failed'});
assert.equal(getRemixExportTimeline(), null);
for (const key of keys) assert.equal(window[key], null, key);''')

    def test_project_and_task_must_match(self):
        self.run_js('''currentRemixProjectId = 'B'; currentRemixTaskId = 'task-B';
for (const key of keys) {
    window[key] = key === 'remixGeneratedTimeline' ? [clip] : result();
    assert.equal(getRemixExportTimeline(), null, key);
    window[key] = null;
}
remixLastResult = result('B', 'task-A');
assert.equal(getRemixExportTimeline(), null);''')

    def test_failed_result_and_plan_are_not_timelines(self):
        self.run_js('''currentRemixProjectId = 'A'; currentRemixTaskId = 'task-A';
remixPlan = {project_id: 'A', clips: [clip]};
assert.equal(getRemixExportTimeline(), null);
remixPlan = null; remixLastResult = {...result(), status: 'failed'};
assert.equal(getRemixExportTimeline(), null);''')

    def test_completed_poll_binds_project_and_task(self):
        self.run_js('''currentRemixProjectId = 'B'; currentRemixTaskId = 'task-B';
await poll({status: 'completed', timeline: [clip], duration_within_tolerance: true});
const chosen = getRemixExportTimeline();
assert.equal(chosen.result.project_id, 'B');
assert.equal(chosen.result.task_id, 'task-B');''')

    def test_stale_poll_does_not_overwrite_new_task(self):
        self.run_js('''seed(); currentRemixProjectId = 'B'; currentRemixTaskId = 'task-B';
remixLastResult = result('B', 'task-B'); remixCompletedResult = remixLastResult;
await poll({status: 'completed', project_id: 'A', task_id: 'task-A', timeline: [clip], duration_within_tolerance: true});
assert.equal(currentRemixProjectId, 'B');
assert.equal(getRemixExportTimeline().result.task_id, 'task-B');''')

    def test_advanced_success_remains_exportable(self):
        for name, key in [('generalModeRemix', 'remixGeneralResult'), ('musicBeatRemix', 'remixMusicBeatResult')]:
            with self.subTest(mode=name):
                self.run_js(f'''currentRemixProjectId = 'A'; currentRemixTaskId = 'old-task'; selectedBGM = 'bgm.mp3';
fetch = async () => respond({{timeline: [clip], project_id: 'A', output_file: 'out.mp4'}});
await {name}();
assert.ok(getRemixExportTimeline());
assert.equal(getRemixExportTimeline().result, window[{json.dumps(key)}]);''')

    def test_advanced_failure_and_validation_do_not_reuse_old_result(self):
        for name in ['generalModeRemix', 'musicBeatRemix']:
            with self.subTest(mode=name):
                self.run_js(f'''seed(); selectedBGM = 'bgm.mp3';
fetch = async () => {{ assert.equal(getRemixExportTimeline(), null); return {{json: async () => ({{code: 1, msg: 'failed'}})}}; }};
await {name}(); assert.equal(getRemixExportTimeline(), null);''')
                self.run_js(f'''seed(); selectedBGM = 'bgm.mp3';
getRequiredRemixDuration = () => {{ throw new Error('invalid duration'); }};
await {name}(); assert.ok(getRemixExportTimeline());''')

    def test_advanced_process_preserves_plan_only_for_request(self):
        self.run_js('''seed(); document.getElementById('projectName').value = 'new';
const plan = remixPlan; let processed = false;
fetch = async (url, options) => {
    assert.equal(getRemixExportTimeline(), null);
    if (url.endsWith('/create')) return respond({project_id: 'B'});
    processed = true;
    assert.deepEqual(JSON.parse(options.body).plan, plan);
    return {json: async () => ({code: 1, msg: 'failed'})};
};
await processRemix(); assert.ok(processed); assert.equal(remixPlan, null);
assert.equal(getRemixExportTimeline(), null);''')

    def test_export_keeps_selected_result_project_after_async_directory_lookup(self):
        self.run_js('''currentRemixProjectId = 'A'; currentRemixTaskId = 'task-A'; remixLastResult = result();
let posted;
requestRemixDraftJson = async (url, options) => { posted = JSON.parse(options.body); return {code: 0, data: {}}; };
const pending = exportJianyingDraft(); currentRemixProjectId = 'B';
await pending;
assert.equal(posted.project_id, 'A');''')


if __name__ == '__main__':
    unittest.main()
