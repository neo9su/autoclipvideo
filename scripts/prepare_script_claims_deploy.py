"""Remove unsupported default assertions without changing production timing/layout."""
import ast
import inspect
from pathlib import Path
from prepare_2k_deploy import raw_replacements
from prepare_remote_audio_deploy import build as backup_runner

SCENE_COPY = '''    scene_text = {
        "result_hook": f"先看{color or model or '这款假发'}的上脸效果，再看近景细节。",
        "pain_point": "选假发先看哪里？先看整体轮廓，再看刘海和发尾。",
        "product_proof": "近看头顶、发丝和发尾，具体细节放大给你看。",
        "tryon_result": "正脸、侧脸换个角度看，再对照整体轮廓和发尾。",
        "cta": "喜欢这个发型，先收藏，再对照细节选适合自己的款。",
    }'''
HOOK_COPY = '''    hooks = [
        f"先看{color or model or '这款假发'}的上脸效果，再看近景细节。",
        "先别急着选，正面和侧面看完，再决定适不适合自己。",
        "同一款换个角度看，留意刘海、发尾和整体轮廓。",
    ]'''


def patch_script(source):
    tree=ast.parse(source)
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='generate_qianchuan_script')
    edits=[]
    for node in function.body:
        if isinstance(node,ast.Assign):
            names={n.id for n in node.targets if isinstance(n,ast.Name)}
            if 'scene_text' in names:edits.append((node,SCENE_COPY))
            if 'hooks' in names:edits.append((node,HOOK_COPY))
        elif isinstance(node,ast.If) and isinstance(node.test,ast.Name) and node.test.id in {'learned_hook','learned_phrases'}:
            edits.append((node,'    # Learned copy is not product evidence; do not inject it into speech.'))
    if sum(isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='scene_text' for t in n.targets) for n in function.body)!=1:
        raise RuntimeError('Scene template drift')
    lines=source.splitlines(keepends=True)
    for node,replacement in sorted(edits,key=lambda item:item[0].lineno,reverse=True):
        lines[node.lineno-1:node.end_lineno]=[replacement+'\n']
    result=''.join(lines)
    replacements=[
        ('points + KEY_SELLING_POINTS','points'),
        (' or merged_points[:3]',''),
        ('"version": "1.0"','"version": "1.1"'),
        ('"selling_points": merged_points,','"selling_points": merged_points,\n        "selling_points_source": "caller_supplied_unverified" if points else "none",'),
    ]
    for old,new in replacements:
        if result.count(old)!=1:raise RuntimeError('Claim template drift: '+old)
        result=result.replace(old,new,1)
    compile(result,'qianchuan_script.py','exec')
    return result


def build():
    setup='from pathlib import Path\nimport ast,difflib\nSCENE_COPY='+repr(SCENE_COPY)+'\nHOOK_COPY='+repr(HOOK_COPY)+'\n'
    setup+=inspect.getsource(raw_replacements)+'\n'+inspect.getsource(patch_script)+r'''
p=Path(r'C:\Users\neo\douyin_backend\backend\qianchuan_script.py')
old=p.read_bytes().decode('utf-8');patched=patch_script(old.replace('\r\n','\n'))
PLAN=[(str(p),raw_replacements(old,patched))]
'''
    body=backup_runner().split('\n',1)[1].replace("'remote-audio-'","'script-default-claims-'")
    body=body.replace("old=old.replace('\\n',newline);new=new.replace('\\n',newline)",'pass')
    return setup+body


if __name__=='__main__':print(build())
