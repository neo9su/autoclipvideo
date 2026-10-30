"""Stage narrow analyzer hook plus a dormant, hash-checked evidence module."""
from pathlib import Path
import hashlib,json,datetime,ast,sys
ROOT=Path(r'C:\Users\neo\douyin_backend')
BEFORE='    result = await _call_bedrock(text)'
AFTER='''    product_match_text = text  # Model hints must never become observed speech.
    # Retrieve names from every original cue before bounded LLM analysis.
    # Saved candidates remain unverified; this does not authorize a cart.
    try:
        from wig_name_recall import enrich
        text = await enrich(srt_path, recording_id, room_id, text)
    except Exception as exc:
        logger.warning("Full-cue name recall failed for %s: %s", recording_id, type(exc).__name__)
    result = await _call_bedrock(text)'''

def patch(source):
    source=source.replace('\r\n','\n')
    if source.count(BEFORE)!=1:raise ValueError('Analyzer source drift')
    result=source.replace(BEFORE,AFTER,1)
    result=result.replace('match_products(text, await load_short_names())', 'match_products(product_match_text, await load_short_names())')
    compile(result,'analyzer','exec');return result


def main(stage):
    target=ROOT/'backend/analyzer.py';before=target.read_bytes();after=patch(before.decode('utf-8-sig')).encode()
    module=ROOT/'backend/wig_name_recall.py';data=(stage/'wig_name_recall.py').read_bytes();compile(data,str(module),'exec')
    if module.exists() and module.read_bytes()!=data:raise ValueError('Existing recall module differs')
    # Ensure deployed dependencies are the inspected versions supplied in manifest.
    dependencies=json.loads((stage/'dependencies.json').read_text())
    for name,digest in dependencies.items():
        if hashlib.sha256((ROOT/'backend'/name).read_bytes()).hexdigest()!=digest:raise ValueError('Dependency drift: '+name)
    b=ROOT/'codex_rollbacks'/('name-recall-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));b.mkdir()
    (b/'analyzer.py.before').write_bytes(before);(b/'analyzer.py.after').write_bytes(after)
    m=[dict(target=str(target),name='analyzer.py',before=hashlib.sha256(before).hexdigest(),after=hashlib.sha256(after).hexdigest())]
    (b/'manifest.json').write_text(json.dumps(m,indent=2))
    (b/'module.json').write_text(json.dumps({'target':str(module),'sha256':hashlib.sha256(data).hexdigest(),'new':not module.exists()}))
    (b/'wig_name_recall.py').write_bytes(data)
    # Not imported by current analyzer. Rollback analyzer disconnects this module.
    module.write_bytes(data)
    (b/'rollback.py').write_text('''from pathlib import Path
import hashlib,json,os
b=Path(__file__).parent;m=json.loads((b/'manifest.json').read_text())[0];p=Path(m['target'])
assert hashlib.sha256(p.read_bytes()).hexdigest() in (m['before'],m['after'])
data=(b/'analyzer.py.before').read_bytes();assert hashlib.sha256(data).hexdigest()==m['before']
t=p.with_suffix('.restore-tmp');t.write_bytes(data);os.replace(t,p)
print('Analyzer restored; idle interactive backend restart required. Evidence retained.')
''')
    print(json.dumps({'backup':str(b),'activated':False}))
if __name__=='__main__':main(Path(sys.argv[1]))
