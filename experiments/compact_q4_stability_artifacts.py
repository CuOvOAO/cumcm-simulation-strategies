"""Keep per-case evidence intact while making the committed JSON diff compact."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
paths=list(ROOT.glob('q4_stability*.json'))+[ROOT/'q4_tail_diagnosis.json',ROOT/'q4_contraction_bound.json']
for path in paths:
    obj=json.loads(path.read_text(encoding='utf8'))
    fields=[]
    for key,value in obj.items():
        prefix='  '+json.dumps(key)+': '
        if key=='rows' and isinstance(value,list):
            body='[\n'+',\n'.join('    '+json.dumps(row,ensure_ascii=False,separators=(',',':')) for row in value)+'\n  ]'
        else:body=json.dumps(value,ensure_ascii=False,separators=(',',':'))
        fields.append(prefix+body)
    with path.open('w',encoding='utf8',newline='\n') as stream:stream.write('{\n'+',\n'.join(fields)+'\n}\n')
