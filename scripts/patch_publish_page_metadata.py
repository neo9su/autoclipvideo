"""Patch metadata entry failure handling without replacing browser automation."""

def patch(source):
    replacements=[
        ('                        await title_el.fill(title[:30])\n',
         '                        await title_el.fill(title[:30])\n                        if await title_el.input_value() != title[:30]:\n                            raise RuntimeError("标题输入框内容与任务文案不一致")\n'),
        ('                        logger.warning(f"Title fill failed: {e}")',
         '                        raise RuntimeError("发布标题填写失败，请检查发布页面后重试") from e'),
        ('                        await desc_el.click(force=True)\n                        await asyncio.sleep(0.3)\n',
         '                        await desc_el.click(force=True)\n                        await desc_el.fill("")\n                        await asyncio.sleep(0.3)\n'),
        ('                        logger.warning(f"Description/tags fill failed: {e}")',
         '                        raise RuntimeError("发布描述或话题填写失败，请检查发布页面后重试") from e'),
    ]
    if '标题输入框内容与任务文案不一致' in source:raise ValueError('Page metadata patch already applied')
    for before,after in replacements:
        if source.count(before)!=1:raise ValueError('Page metadata source drifted: '+before.splitlines()[0])
        source=source.replace(before,after,1)
    compile(source,'publisher_douyin.py','exec');return source
