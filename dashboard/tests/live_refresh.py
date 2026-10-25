"""Acceptance check for the real startup scheduler, source fetchers and image exporter."""
from pathlib import Path
import hashlib
import json
import time
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[2]
base='http://127.0.0.1:8741'
def get(path):
    with urlopen(base+path,timeout=10) as response:return json.load(response)
started=time.monotonic()
while True:
    state=get('/api/status')
    data=get('/api/data')
    if not state['updating'] and data.get('reference_sha256'):
        break
    assert time.monotonic()-started<300,'Startup refresh exceeded five-minute acceptance window'
    time.sleep(2)
assert data['days']==4 and data['through']=='2026-10-22'
assert len(data['counties'])==9
assert all(c['status']=='current' for c in data['counties']),[(c['id'],c['status'],c['error']) for c in data['counties']]
assert hashlib.sha256((ROOT/'dashboard/data/reference.json').read_bytes()).hexdigest()==data['reference_sha256']
output=ROOT/'analysis/updated-through-2026-10-22'
assert json.loads((output/'snapshot.json').read_text())['generated_at']==data['generated_at']
assert len(list(output.glob('*.png')))==11
assert len(list(output.glob('*.svg')))==11
assert (output/'report.md').exists()
assert (output/'reference-data.json').read_bytes()==(ROOT/'dashboard/data/reference.json').read_bytes()
result={'status':'passed','startup_scheduler':True,'all_nine_sources_current':True,'automatic_image_exports':22,'reference_sha256':data['reference_sha256'],'generated_at':data['generated_at']}
(output/'qa/live-refresh-verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
