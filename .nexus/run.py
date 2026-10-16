import json, pathlib, subprocess, sys
config=json.loads(pathlib.Path('nexus-build.json').read_text(encoding='utf-8'))
step=sys.argv[1]
if step not in ('install','build','test'): raise SystemExit('Unknown build stage')
command=config[step]
if not command.strip():
    if step=='install': raise SystemExit(0)
    raise SystemExit('Missing required command')
print('NEXUS / '+step,flush=True)
try:
    result=subprocess.run(['bash','--noprofile','--norc','-eo','pipefail','-c',command],timeout=900)
    raise SystemExit(result.returncode)
except subprocess.TimeoutExpired:
    raise SystemExit('Stage exceeded 15 minutes')
