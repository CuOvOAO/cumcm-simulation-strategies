"""Run frozen Q4_STABLE15 in the official simulator's current mode.

Start Q4 in the simulator UI (rehearsal or formal simulation), then pass --run
or the compatible --exercise flag. These flags authorize HTTP; they do not
select the simulator mode. The historical stable runner remains frozen.
"""
import argparse
from pathlib import Path

from run_q4_stability_official import (
    BEST_VARIANT,
    DEFAULT_BASE_URL,
    DeadlineAPI,
    OfficialHttpSimulatorAdapter,
    ROOT,
    main as _stable_main,
)


def main(argv=None, adapter_factory=OfficialHttpSimulatorAdapter):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', '--exercise', dest='launch', action='store_true',
                        help='connect to the current Q4 session (either simulator mode)')
    parser.add_argument('--base-url', default=DEFAULT_BASE_URL)
    parser.add_argument('--timeout', type=float, default=5.)
    parser.add_argument('--output-root', type=Path, default=ROOT/'results/q4_official')
    args = parser.parse_args(argv)
    if not args.launch:
        print('Select Q4 in the simulator UI, then pass --run or --exercise. No HTTP sent.')
        return 2
    print(f'Q4 candidate: {BEST_VARIANT}; using the mode selected in the simulator UI.', flush=True)
    return _stable_main([
        '--exercise', '--base-url', args.base_url, '--timeout', str(args.timeout),
        '--output-root', str(args.output_root),
    ], adapter_factory)


if __name__ == '__main__':
    raise SystemExit(main())
