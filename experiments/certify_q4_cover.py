"""Generate and independently check a complete finite cover proof."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from q4_stable.coverage import generate_certificate,verify_certificate

if __name__=='__main__':
    cert=generate_certificate(8)
    # JSON conversion reflects the coordinates in the actual wire format.
    cert=json.loads(json.dumps(cert))
    print(verify_certificate(cert),flush=True)
    (ROOT/'q4_stable/cover_8.json').write_text(json.dumps(cert,separators=(',',':')),encoding='utf8')
