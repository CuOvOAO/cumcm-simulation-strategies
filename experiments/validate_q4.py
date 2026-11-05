"""Frozen candidate only. Never select a variant or tune on this split."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.run_q4 import hashes,main as run


def main():
    p=argparse.ArgumentParser(__doc__)
    p.add_argument('--count',type=int,default=128)
    p.add_argument('--jobs',type=int,default=4)
    p.add_argument('--out',type=Path,default=ROOT/'results/q4_validation_reproduction')
    p.add_argument('--summary',type=Path)
    args=p.parse_args()
    frozen=json.loads((ROOT/'experiments/q4_candidate_freeze.json').read_text(encoding='utf8'))
    if hashes()!=frozen['source_hashes']: raise RuntimeError('candidate changed after freeze')
    command=['--generate','validation','--count',str(args.count),'--limit',str(args.count),
         '--cases',str(ROOT/'cases_extra/q4/validation'),'--variants',frozen['variant'],
         '--jobs',str(args.jobs),'--out',str(args.out)]
    if args.summary is not None: command += ['--summary',str(args.summary)]
    result=run(command)
    if not all(row['p0'] for row in result['rows']):
        raise RuntimeError('frozen candidate failed validation; see persisted summary')


if __name__=='__main__': main()
