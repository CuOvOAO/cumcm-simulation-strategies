"""Offline Q4 integrity audit, historical-case reproduction and official replay.

Never contacts HTTP. Regenerated historical inputs go only into results/ and
must match every original case SHA-256 before any benchmark is executed.
"""
import contextlib
from collections import Counter
from decimal import localcontext
import hashlib
import io
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments import run_q4_stability as bench
from experiments.audit_q4_stability import replay
from run_q4_official import main as official_main

REFERENCE = 'f3b934c'
OUT = ROOT/'results/q4_entry_audit'


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False)+'\n', encoding='utf8')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT).decode('utf8').strip()


def ledger(events):
    phase = Counter()
    components = Counter()
    counts = Counter()
    service = Counter()
    pos, channel = (0., 0.), 1
    max_error = 0.
    last_clear = 0.
    for event in events:
        move = math.dist(pos, event['position'])/5
        measure = event['action'] == 'measure'
        switch = int(measure and event['channel'] != channel)
        components['movement_s'] += move
        components['measure_s' if measure else 'clear_s'] += 5
        components['switch_s'] += switch
        cost = move+5+switch
        phase[event['phase']] += cost
        counts[event['action']] += 1
        if measure:
            counts[event['response']['measure_result']] += 1
            channel = event['channel']
        else:
            counts[event['response']['clear_result']] += 1
            last_clear = event['response']['virtual_time_s']
        if event['phase'] in ('localization', 'reacquisition', 'clear'):
            service[event['channel']] += cost
        max_error = max(max_error, abs(sum(components.values())-event['response']['virtual_time_s']))
        pos = event['position']
    return dict(phase_s=dict(phase), components_s=dict(components), counts=dict(counts),
                source_service_s=dict(service), reconstructed_s=sum(components.values()),
                max_cumulative_timing_error_s=max_error,
                after_last_clear_s=events[-1]['response']['virtual_time_s']-last_clear)


def official_replay(folder, frozen):
    summary = read(folder/'summary.json')
    events = [json.loads(s) for s in (folder/'certificates.jsonl').read_text(encoding='utf8').splitlines()]
    actions = [json.loads(s) for s in (folder/'actions.jsonl').read_text(encoding='utf8').splitlines()]
    action_rows = [a for a in actions if a['path'] in ('/measure', '/clear')]
    assert len(action_rows) == len(events)
    for action, event in zip(action_rows, events):
        assert action['accepted'] is True
        assert action['path'] == '/'+event['action']
        assert action['channel'] == event['channel']
        assert [action['position']['x'], action['position']['y']] == event['position']
        assert action['virtual_time_after_s'] == event['response']['virtual_time_s']
        for field in ('measure_result', 'clear_result', 'svd_deg'):
            assert action.get(field) == event['response'].get(field)
    assert summary['source_hashes'] == frozen['source_hashes']

    class TranscriptAdapter:
        def __init__(self, **kwargs):
            self.index = 0
            self.context = None

        def enter(self):
            return {'remaining_real_duration_s': 1200.}

        def set_action_context_provider(self, provider):
            self.context = provider

        def step(self, action, position, channel):
            event = events[self.index]
            assert action == event['action']
            assert list(position) == event['position']
            assert channel == event['channel']
            assert self.context()['phase'] == event['phase']
            self.index += 1
            return dict(event['response'])

        def measure(self, *args):
            return self.step('measure', *args)

        def clear(self, *args):
            return self.step('clear', *args)

        def exit(self):
            assert self.index == len(events)
            return {'exit_reason': 'OFFLINE_REPLAY_ONLY'}

    target = OUT/'official_replay'/folder.name
    with patch.dict(os.environ, {'CUMCM_ROBOT_ID': 'OFFLINE_AUDIT_ONLY'}), contextlib.redirect_stdout(io.StringIO()):
        assert official_main(['--exercise', '--output-root', str(target)], TranscriptAdapter) == 0
    new_folder = max(target.iterdir(), key=lambda p: p.name)
    reproduced = [json.loads(s) for s in (new_folder/'certificates.jsonl').read_text(encoding='utf8').splitlines()]
    assert reproduced == events
    # Adapt our own transcript copy for the existing independent Decimal audit.
    # Original official logs are read-only and remain untouched.
    api = [{k: e[k] for k in ('action', 'position', 'channel', 'response')} for e in events]
    for name, data in (('api.jsonl', api), ('decisions.jsonl', events)):
        (new_folder/name).write_text(''.join(json.dumps(e)+'\n' for e in data), encoding='utf8')
    with localcontext() as ctx:
        ctx.prec = 50
        independent = replay(new_folder)
    return dict(folder=folder.relative_to(ROOT).as_posix(),
                variant=summary['variant'], normal_exit=summary['normal_exit'],
                cleared=summary['cleared'], virtual_time_s=summary['virtual_time_s'],
                seconds_per_cleared_source=summary['seconds_per_cleared_source'],
                source_total_not_in_transcript=True,
                frozen_hashes_match=True, canonical_entry_exact_replay=True,
                diagnostics=summary['diagnostics'], retries=sum(a['retries'] for a in actions),
                independent_audit=independent, **ledger(events))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    frozen = read(ROOT/'experiments/q4_stability_freeze.json')
    historical = read(ROOT/'experiments/q4_stability_final_holdout.json')
    hashes = bench.hashes()
    assert hashes == frozen['source_hashes'] == historical['source_hashes']
    scope = ['q4', 'q4_stable', 'simulator.py', 'strategies/__init__.py',
             'strategies/d/__init__.py', 'strategies/d/geometry.py', 'q3/__init__.py',
             'q3/official_http_api.py', 'run_q4_stability_official.py',
             'experiments/run_q4.py', 'experiments/run_q4_stability.py',
             'experiments/audit_q4_stability.py', 'experiments/q4_stability_freeze.json']
    difference = git('diff', '--name-status', REFERENCE, '--', *scope)
    assert not difference, difference
    old_rows = [r for r in historical['rows'] if r['variant'] == frozen['variant']]
    assert len(old_rows) == 240
    # Cleanup removed the ignored case directory. Restore exact bytes into a
    # new audit directory using the unchanged historical generator and seed.
    with patch.object(bench, 'ROOT', OUT):
        bench.generate('final_holdout', len(old_rows))
    cases = OUT/'cases_extra/q4_stability/final_holdout'
    for old in old_rows:
        assert hashlib.sha256((cases/old['case']).read_bytes()).hexdigest() == old['sha256'], old['case']
    print('Frozen sources, historical Git scope and 240 case hashes match.', flush=True)
    rows = []
    # CPU/runtime values and absolute log paths are intentionally excluded.
    compared = ('sha256', 'profile', 'variant', 'error_mode', 'total_sources', 'cleared',
                'cleared_fraction', 'virtual_time_s', 'average_clear_time_s', 'distance_m',
                'measure', 'switch', 'clear_success', 'clear_fail', 'error', 'diagnostics',
                'audit', 'phase_s', 'p0', 'seconds_per_source')
    for index, old in enumerate(old_rows, 1):
        with contextlib.redirect_stdout(io.StringIO()):
            row = bench.run_one((str(cases/old['case']), frozen['variant'], str(OUT/'benchmark'), 'hash'))
        assert all(row[k] == old[k] for k in compared), old['case']
        rows.append(row)
        if index % 60 == 0:
            print(f'Historical cases exactly reproduced: {index}/240', flush=True)
    save(OUT/'comparison.json', dict(rows=rows, summary=bench.aggregate(rows)))
    official = []
    for path in sorted((ROOT/'results/q4_stability_official_rehearsal').glob('*/summary.json')):
        official.append(official_replay(path.parent, frozen))
        print(f'Official transcript replay verified: {path.parent.name}', flush=True)
    n10 = [r for r in rows if r['total_sources'] == 10]
    evidence = dict(
        command='python -X utf8 experiments/audit_q4_entry.py', python=sys.version,
        branch=git('branch', '--show-current'), historical_commit=git('rev-parse', REFERENCE),
        baseline_variant=frozen['variant'], source_hashes=hashes, historical_git_scope=scope,
        historical_git_diff=difference, frozen_and_holdout_hashes_match=True,
        historical_case_sha256_matches=len(rows), per_case_performance_exact_matches=len(rows),
        compared_fields=compared, reproduced_summary=bench.aggregate(rows),
        ten_source_summary=bench.aggregate(n10),
        ten_source_mean_phase_per_source={k: statistics.fmean(r['phase_s'][k]/10 for r in n10)
                                          for k in n10[0]['phase_s']},
        official_replays=official, official_http_requests_sent=0,
        entry_change='run_q4_official now delegates to unchanged frozen stable runner; --run and --exercise are aliases',
        limitation='Historical 240-case regression, not a new holdout or a universal time bound. Official source totals/types require UI evidence.')
    save(ROOT/'experiments/q4_entry_audit.json', evidence)
    print(json.dumps({k: evidence['reproduced_summary'][k] for k in
                      ('cases', 'complete_cases', 'cleared', 'mean', 'p95', 'worst')}, indent=2))


if __name__ == '__main__':
    main()
