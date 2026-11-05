"""Human-launched Q4 rehearsal. Without --exercise this makes no HTTP request."""
import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import sys
import time
from q4_stable.controller import Controller,BEST_VARIANT
from q3.official_http_api import OfficialHttpSimulatorAdapter,OfficialRunLogger,DEFAULT_BASE_URL
from experiments.run_q4_stability import hashes
from q4_stable.coverage import certified_points

ROOT=Path(__file__).resolve().parent


class DeadlineAPI:
    """Deadline derives solely from public /enter response and local elapsed time."""
    def __init__(self,adapter,remaining,timeout):
        if isinstance(remaining,bool) or not isinstance(remaining,(int,float)) or not math.isfinite(remaining) or remaining<=10:
            raise RuntimeError('insufficient/invalid remaining_real_duration_s')
        self.adapter=adapter
        self.deadline=time.monotonic()+remaining
        self.margin=max(10.,2*timeout+2)
    def check(self):
        if time.monotonic()+self.margin>=self.deadline: raise RuntimeError('public runtime deadline nearly exhausted')
    def measure(self,*args): self.check();return self.adapter.measure(*args)
    def clear(self,*args): self.check();return self.adapter.clear(*args)


def main(argv=None,adapter_factory=OfficialHttpSimulatorAdapter):
    p=argparse.ArgumentParser(__doc__)
    p.add_argument('--exercise',action='store_true')
    p.add_argument('--base-url',default=DEFAULT_BASE_URL)
    p.add_argument('--timeout',type=float,default=5.)
    p.add_argument('--output-root',type=Path,default=ROOT/'results/q4_stability_official_rehearsal')
    args=p.parse_args(argv)
    if not args.exercise:
        print('REFUSED: manually start QUESTION 4 REHEARSAL, then pass --exercise. No HTTP sent.')
        return 2
    robot_id=os.environ.get('CUMCM_ROBOT_ID')
    if not robot_id:
        print('REFUSED: CUMCM_ROBOT_ID is required. No HTTP sent.')
        return 2
    frozen=json.loads((ROOT/'experiments/q4_stability_freeze.json').read_text(encoding='utf8'))
    if hashes()!=frozen['source_hashes'] or BEST_VARIANT!=frozen['variant']:
        print('REFUSED: frozen candidate hash changed. No HTTP sent.')
        return 2
    if not math.isfinite(args.timeout) or args.timeout<=0:
        print('REFUSED: timeout must be finite and positive. No HTTP sent.')
        return 2
    # Validate the static proof before /enter starts the official real-time clock.
    certified_points()
    folder=args.output_root/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    logger=OfficialRunLogger(folder)
    adapter=None;c=None;exited=None;error=None
    try:
        adapter=adapter_factory(robot_id=robot_id,base_url=args.base_url,timeout_s=args.timeout,max_retries=1,logger=logger)
        enter=adapter.enter()
        c=Controller(DeadlineAPI(adapter,enter['remaining_real_duration_s'],args.timeout))
        adapter.set_action_context_provider(lambda:c.action_context)
        c.run()
        exited=adapter.exit()
    except (Exception,KeyboardInterrupt) as exc:
        error=f'{type(exc).__name__}: {exc}'.replace(robot_id,'<redacted>')
        logger.message('STOPPED: '+error)
        # Adapter retries an uncertain action using the same ID. After it stops,
        # never issue a new action or speculative /exit from the error branch.
    finally:
        n=sum(s.cleared for s in c.sources.values()) if c else 0
        summary=dict(variant=BEST_VARIANT,normal_exit=exited is not None,error=error,
            virtual_time_s=c.time if c else None,cleared=n,
            seconds_per_cleared_source=c.time/n if c and n else None,
            total_source_truth=None,source_clear_rate=None,
            note='Read source totals from the official rehearsal UI after exit; transcript alone has no truth count.',
            diagnostics=c.diagnostics if c else None,wall_s=logger.elapsed_s(),python=sys.version,source_hashes=hashes())
        (folder/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
        if c: (folder/'certificates.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in c.events),encoding='utf8')
        print(json.dumps(summary,indent=2))
    return 0 if exited is not None else 1


if __name__=='__main__': raise SystemExit(main())
