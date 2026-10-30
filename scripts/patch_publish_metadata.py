"""Apply a narrow metadata forwarding fix to the current production scheduler."""
from pathlib import Path
import argparse


def patch(source):
    replacements = [
        ('        title = task.get("title")\n        description = task.get("description")\n',
         '        title = task.get("title")\n        description = task.get("description")\n        tags = task.get("tags")\n'),
        ('        task_ctx = dict(task)\n',
         '        task_ctx = dict(task)\n        task_ctx.update(title=title, description=description, tags=tags)\n'),
        ('        title = task.get("title") or f"任务#{task_id}"\n        asyncio.create_task(notify(f"✅ 抖音发布成功：{title}"))',
         '        title = task_ctx.get("title") or f"任务#{task_id}"\n        asyncio.create_task(notify(f"✅ 抖音发布成功：{title}"))'),
    ]
    if '        task_ctx.update(title=title, description=description, tags=tags)' in source:
        raise ValueError('Metadata patch already applied')
    for before, after in replacements:
        if source.count(before) != 1: raise ValueError('Metadata source drifted: '+before.splitlines()[0])
        source = source.replace(before, after, 1)
    compile(source, 'publish_scheduler.py', 'exec')
    return source


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    with a.output.open('x',encoding='utf-8') as f:f.write(patch(a.source.read_text(encoding='utf-8-sig')))
