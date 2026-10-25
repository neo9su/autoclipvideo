"""Only untouched draft groups may accept new source material."""
OPEN_GROUP_SQL = ' AND '.join(
    f'coalesce({name},0)=0' for name in (
        'is_custom','merge_status','classic_status','director_status',
        'creative_status','realistic_status','conservative_status','qianchuan_status',
    )
)
