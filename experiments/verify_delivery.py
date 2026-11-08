"""Verify the final source/input/binary/report delivery hashes."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


if __name__=='__main__':
    manifest=json.loads((ROOT/'experiments/scientific/delivery_manifest.json').read_text())
    failed=[name for name,value in manifest['files'].items() if sha(ROOT/name)!=value]
    if failed:raise SystemExit('Changed final artifacts: '+', '.join(failed))
    print('Final delivery verified:',len(manifest['files']),'source/input/binary/result/report files')
