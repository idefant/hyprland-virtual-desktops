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
                  'hl.config({debug={disable_logs=false},animations={enabled=false},cursor={no_warps=false,warp_on_change_workspace=1}})\n')
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
        if not (original and stage == 'two outputs'):
            # A browser activation or explicit window focus enters the same
            # workspace.active path; it must switch the whole logical desktop.
            before = {w['address']:w['workspace'] for w in query('clients')}
            for target_desk in (2, 1):
                desk(3)
                target_window = next(a for a,d in expected.items() if d == target_desk)
                ctl('dispatch','hl.dsp.focus({window='+json.dumps('address:'+target_window)+'})')
                focused = next(d['id'] for d in query('printstate') if d['focused'])
                assert focused == target_desk, (stage,'external focus did not change logical desk',focused)
                assert {m['activeWorkspace']['id'] for m in query('monitors')} == layouts[target_desk], (stage,'external focus switched only one output')
                assert query('activewindow')['address'] == target_window, (stage,'activation lost target focus')
            assert before == {w['address']:w['workspace'] for w in query('clients')}
        assert not ctl('configerrors').strip()
        print('PASS', mode, stage, flush=True)

    if not original:
        def focus(address):
            ctl('dispatch', 'hl.dsp.focus({window=' + json.dumps('address:' + address) + '})')

        def assert_focus(address, stage):
            active = query('activewindow')
            assert active.get('address') == address, (stage, 'wrong remembered focus', active.get('address'), address)
            pos = query('cursorpos')
            center = [active['at'][i] + active['size'][i] / 2 for i in (0, 1)]
            assert abs(pos['x'] - center[0]) <= 2 and abs(pos['y'] - center[1]) <= 2, (stage, 'cursor not centered', pos, center)

        outputs = {m['name']: m['id'] for m in query('monitors')}
        windows = query('clients')
        left = next(w['address'] for w in windows if expected[w['address']] == 1 and w['monitor'] == outputs[primary])
        right = next(w['address'] for w in windows if expected[w['address']] == 2 and w['monitor'] == outputs['VTEST-2'])
        desk(1)
        focus(left)
        desk(2)
        focus(right)
        for _ in range(4):
            desk(1)
            assert_focus(left, 'return to first output')
            desk(2)
            assert_focus(right, 'return to second output')
        # Change the remembered window within a desktop, not just its output.
        desk(1)
        alternate = next(w['address'] for w in windows if expected[w['address']] == 1 and w['address'] != left)
        focus(alternate)
        desk(2)
        desk(1)
        assert_focus(alternate, 'updated last focus')
        # Silent moves invalidate old ownership without pulling the window back.
        lua('hl.plugin.virtual_desktops.movetodesksilent("3")')
        expected[alternate] = 3
        desk(2)
        desk(1)
        assert query('activewindow').get('address') != alternate
        # Moving with a desktop switch must follow the moved window even when
        # the destination already remembers another window on another output.
        desk(1)
        focus(left)
        lua('hl.plugin.virtual_desktops.movetodesk("2")')
        expected[left] = 2
        assert_focus(left, 'move and follow')
        lua('hl.plugin.virtual_desktops.movetodesk("1")')
        expected[left] = 1
        assert_focus(left, 'move and follow back')
        # A closed weak reference must never be dereferenced on return.
        desk(2)
        focus(right)
        ctl('dispatch', 'hl.dsp.window.close({window=' + json.dumps('address:' + right) + '})')
        for _ in range(50):
            if not any(w['address'] == right for w in query('clients')):
                break
            time.sleep(.05)
        del expected[right]
        desk(1)
        desk(2)
        assert query('activewindow').get('address') != right
        # Keep the original topology coverage symmetric after these regressions.
        add_window(2, 'VTEST-2')
        print('PASS', mode, 'per-desktop focus, centered cursor, moved/closed windows', flush=True)

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
