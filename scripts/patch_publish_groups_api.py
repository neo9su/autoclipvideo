"""Change only the picker file checks; preserve deployed ingestion and matching code."""


def patch(source):
    before = '        from video_path_resolver import resolve_artifact_path\n'
    after = '        from group_artifact_snapshot import GroupArtifactSnapshot\n'
    anchors = [
        (before, after),
        ('        result = []\n        for row in rows:\n',
         '        inventory = GroupArtifactSnapshot(versions, values=(dict(row).get(field) for row in rows for field in versions.values()))\n        result = []\n        for row in rows:\n'),
        ('                path, reason = resolve_artifact_path(item.get(field), version)\n',
         '                path, reason = inventory.resolve(item.get(field), version)\n'),
    ]
    for old, new in anchors:
        if source.count(old) != 1:
            raise ValueError('Publish group API source drift')
        source = source.replace(old, new, 1)
    compile(source, '<patched api_codex>', 'exec')
    return source
