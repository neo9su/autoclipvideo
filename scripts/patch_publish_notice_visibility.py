"""Move legacy quick links below dialogs and keep notices above dialogs."""
import re
from pathlib import Path

def patch_html(text):
    if 'publish-quick-links' in text:
        raise ValueError('Already patched')
    links = []
    for name in ['publish-review-entry', 'history-library-entry']:
        matches = list(re.finditer(r'<a\b[^>]*\bid="'+name+r'"[^>]*>.*?</a>', text, re.S))
        if len(matches) != 1:
            raise ValueError('Quick-link anchor drift: '+name)
        link = matches[0].group()
        text = text.replace(link, '', 1)
        links.append(re.sub(r'\sstyle="[^"]*"', '', link))
    style = '''<style id="publish-notice-visibility">
#publish-quick-links{position:fixed;left:16px;bottom:16px;z-index:50;display:flex;gap:8px;max-width:calc(100vw - 32px);flex-wrap:wrap}
#publish-quick-links a{position:static;background:#ed2852;color:white;padding:9px 12px;border-radius:8px;text-decoration:none;font:13px system-ui}
body:has(.modal-overlay) #publish-quick-links{display:none}
.toast-container{top:72px!important;bottom:auto!important;right:16px!important;z-index:10020!important;max-width:calc(100vw - 32px)}
.toast{overflow-wrap:anywhere}
</style>'''
    assert text.count('</body>') == 1
    return text.replace('</body>', style+'<nav id="publish-quick-links" aria-label="快捷入口">'+''.join(links)+'</nav></body>')

if __name__ == '__main__':
    import sys
    Path(sys.argv[2]).write_text(patch_html(Path(sys.argv[1]).read_text(encoding='utf-8')), encoding='utf-8')
