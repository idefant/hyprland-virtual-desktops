#!/usr/bin/env python3
"""Integration regression in an isolated nested Hyprland; needs Hyprland and foot.

Usage: python3 tests/hotplug.py ./virtual-desktops.so [monitors|size|none]
Never disconnects outputs in the parent session. Test windows contain sleep only.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

plugin = str(Path(sys.argv[1]).resolve())
mode = sys.argv[2] if len(sys.argv) > 2 else 'monitors'
root = Path(tempfile.mkdtemp(prefix='vdesk-hotplug-test-'))
config = root / 'test.lua'
config.write_text('hl.monitor({output="",mode="800x600@60",position="auto",scale=1})\n'
                  'hl.config({debug={disable_logs=false},animations={enabled=false},cursor={no_warps=true}})\n')
env = os.environ.copy()
env.update(AQ_DRM_DEVICES='/dev/null', HYPRLAND_NO_SD_VARS='1',
           HYPRLAND_NO_SD_NOTIFY='1', HYPRLAND_NO_RT='1')
log = (root / 'compositor.log').open('w')
process = subprocess.Popen(['Hyprland', '--config', str(config)], env=env,
                           stdout=log, stderr=subprocess.STDOUT)
try:
    instance = None
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError('Nested compositor exited; see ' + str(root))
        instances = json.loads(subprocess.check_output(['hyprctl', 'instances', '-j']))
        instance = next((i['instance'] for i in instances if i['pid'] == process.pid), None)
        if instance:
            break
        time.sleep(.1)
    assert instance

    def ctl(*args):
        result = subprocess.run(['hyprctl', '-i', instance, *args], capture_output=True, text=True)
        if result.returncode or (result.stdout.startswith('error')):
            raise RuntimeError((args, result.stdout, result.stderr, str(root)))
        return result.stdout

    def query(command):
        return json.loads(ctl('-j', command))

    def lua(code):
        result = ctl('eval', code)
        assert result.strip() == 'ok', result

    def desk(number):
        lua('hl.plugin.virtual_desktops.vdesk(' + json.dumps(str(number)) + ')')

    for _ in range(50):
        if query('monitors'):
            break
        time.sleep(.1)
    primary = query('monitors')[0]['name']
    original = os.environ.get('VDESK_TEST_UPGRADE_FROM')
    ctl('plugin', 'load', original or plugin)
    lua('hl.config({plugin={virtual_desktops={cycleworkspaces=0,notifyinit=0,verbose_logging=1,rememberlayout='
        + json.dumps(mode) + ',monitor_order=' + json.dumps(primary+',VTEST-2,VTEST-3') + '}}})')
    # Start with one output, then attach another before creating windows.
    ctl('output', 'create', 'headless', 'VTEST-2')
    time.sleep(.2)
    expected = {}

    def add_window(number, output):
        desk(number)
        ctl('dispatch', 'hl.dsp.focus({monitor=' + json.dumps(output) + '})')
        existing = {w['address'] for w in query('clients')}
        lua('hl.exec_cmd("foot --app-id=VDESK-HOTPLUG-TEST -- /usr/bin/sleep 300")')
        for _ in range(50):
            added = [w for w in query('clients') if w['address'] not in existing]
            if added:
                break
            time.sleep(.1)
        assert len(added) == 1
        expected[added[0]['address']] = number

    for number in (1, 2, 3):
        for output in (primary, 'VTEST-2'):
            add_window(number, output)

    def verify(stage):
        clients = query('clients')
        assert set(expected) == {w['address'] for w in clients}, (stage, 'window lost')
        state = query('printstate')
        layouts = {d['id']: set(d['workspaces']) for d in state}
        seen = set()
        count = len(query('monitors'))
        for layout in layouts.values():
            if not layout:
                continue
            assert len(layout) == count, (stage, 'incomplete layout', layout)
            assert not seen.intersection(layout), (stage, 'shared ownership')
            seen.update(layout)
        for window in clients:
            number = expected[window['address']]
            assert window['workspace']['id'] in layouts[number], (stage, 'orphan', number, window['workspace'])
        for number in sorted(set(expected.values())):
            desk(number)
            active = {m['activeWorkspace']['id'] for m in query('monitors')}
            assert active == layouts[number], (stage, 'not visible', number, active, layouts[number])
            visible = {w['address'] for w in query('clients') if w['workspace']['id'] in active}
            assert visible == {a for a, d in expected.items() if d == number}, (stage, 'desktop leakage')
        assert not ctl('configerrors').strip()
        print('PASS', mode, stage, flush=True)

    verify('two outputs')
    if original:
        before = {w['address']: w['workspace'] for w in query('clients')}
        ctl('plugin', 'unload', original)
        ctl('plugin', 'load', plugin)
        lua('hl.config({plugin={virtual_desktops={cycleworkspaces=0,notifyinit=0,rememberlayout='
            + json.dumps(mode) + ',monitor_order=' + json.dumps(primary+',VTEST-2,VTEST-3') + '}}})')
        for number in sorted(set(expected.values())):
            desk(number)
        assert before == {w['address']: w['workspace'] for w in query('clients')}
        verify('live plugin replacement')
    # Native migration must also retain floating/fullscreen window states.
    floating = next(w['address'] for w in query('clients') if expected[w['address']] == 1)
    ctl('dispatch','hl.dsp.window.float({window='+json.dumps('address:'+floating)+',action="on"})')
    fullscreen = next(w['address'] for w in query('clients') if expected[w['address']] == 2)
    ctl('dispatch','hl.dsp.window.fullscreen({window='+json.dumps('address:'+fullscreen)+',mode="fullscreen"})')
    for cycle in range(3):
        desk(2)
        ctl('output', 'remove', 'VTEST-2')
        time.sleep(.15)
        assert next(d['id'] for d in query('printstate') if d['focused']) == 2
        verify('unplug ' + str(cycle))
        ctl('output', 'create', 'headless', 'VTEST-2')
        time.sleep(.15)
        verify('reconnect ' + str(cycle))
    ctl('output', 'create', 'headless', 'VTEST-3')
    time.sleep(.15)
    add_window(4, 'VTEST-3') # New desktop after layouts have been renumbered.
    verify('three outputs, new desktop')
    ctl('output', 'remove', 'VTEST-2')
    ctl('output', 'remove', 'VTEST-3')
    time.sleep(.15)
    verify('three to one')
    ctl('reload')
    verify('reload')
    final = {w['address']: w for w in query('clients')}
    assert final[floating]['floating']
    assert final[fullscreen]['fullscreen'] != 0
    print('PASS',mode,'floating/fullscreen retained',flush=True)
except Exception:
    if process.poll() is None:
        (root/'rolling.log').write_text(ctl('rollinglog'))
    print('Diagnostics:',root,flush=True)
    raise
finally:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    log.close()
