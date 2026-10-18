"""Drift-checked Buyin browser replacement; preserve original profile for rollback."""
import hashlib
from pathlib import Path
from prepare_remote_audio_deploy import build as backup_runner


def replacements():
    return [
        ('PROFILE_DIR = os.path.join(BASE, "chromium_profile_buyin")', 'PROFILE_DIR = os.path.join(BASE, "chromium_profile_buyin_chrome")'),
        ('PROFILE_DIR, headless=False, locale="zh-CN", timezone_id="Asia/Shanghai",', 'PROFILE_DIR, channel="chrome", headless=False, locale="zh-CN", timezone_id="Asia/Shanghai",'),
        ('        self.restarts = 0', '        self.restarts = 0\n        self.next_restart = 0.0'),
        ('        self.restarts += 1\n', '''        if self.restarts >= 3 or time.monotonic() < self.next_restart:
            return False
        self.restarts += 1
        self.next_restart = time.monotonic() + min(300, 60 * (2 ** (self.restarts - 1)))
'''),
        ('        await self.show_window()\n        try:\n            await self.page.goto(LOGIN_URL_OUT if relogin else LOGIN_URL,', '''        if not await self.browser_alive():
            self.restarts = 0
            self.next_restart = 0.0
            if not await self.ensure_browser():
                return
        await self.show_window()
        try:
            await self.page.goto(LOGIN_URL_OUT if relogin else LOGIN_URL,'''),
        ('                    if not await self.ensure_browser():\n                        continue', '''                    if not await self.ensure_browser():
                        self.online = False
                        set_state("need_login", "浏览器恢复已暂停，请点击显示登录窗口重试；不会持续弹窗")
                        await self.handle_show_flag()
                        await asyncio.sleep(1.5)
                        continue'''),
    ]


def patch(source):
    for old,new in replacements():
        if source.count(old) != 1:
            raise RuntimeError('Buyin service source drift: ' + old[:65])
        source=source.replace(old,new)
    compile(source,'buyin_session_service.py','exec')
    return source


def build(baseline):
    patch(baseline.decode('utf-8').replace('\r\n','\n'))
    setup='PLAN = '+repr([(r'C:\douyin_login\buyin_session_service.py',replacements())])+'\n'
    body=backup_runner().split('\n',1)[1].replace('remote-audio-', 'buyin-browser-').replace('Code restored; restart backend and GPU only when idle. No database changed.', 'Buyin code restored; restart only DouyinBuyinSessionOnLogon. Original browser profile remains untouched. No database changed.')
    preflight='''from pathlib import Path
import hashlib,shutil
p=Path(r'C:\\douyin_login\\buyin_session_service.py')
assert hashlib.sha256(p.read_bytes()).hexdigest()==BASELINE_HASH, 'Source drift'
old_profile=p.parent/'chromium_profile_buyin'
new_profile=p.parent/'chromium_profile_buyin_chrome'
assert not new_profile.exists(), 'Chrome profile already exists; inspect before deploying'
# Keep the original profile byte-for-byte untouched. Profile data stays on-host.
if old_profile.exists():
    shutil.copytree(old_profile,new_profile)
else:
    new_profile.mkdir()
'''
    return 'BASELINE_HASH = '+repr(hashlib.sha256(baseline).hexdigest())+'\n'+preflight+setup+body


if __name__=='__main__':
    print(build(Path(__import__('sys').argv[1]).read_bytes()))
