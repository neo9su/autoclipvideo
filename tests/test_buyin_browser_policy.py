import ast,asyncio,sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from prepare_buyin_browser_deploy import replacements


def test_restart_budget_and_backoff_do_not_launch_browser():
    source=next(new for old,new in replacements() if old=='        self.restarts += 1\n')
    ns={};exec('async def guard(self):\n'+source+'        return True',{'time':SimpleNamespace(monotonic=lambda:1000),'min':min},ns)
    state=SimpleNamespace(restarts=0,next_restart=0)
    assert asyncio.run(ns['guard'](state)) is True
    assert state.restarts==1 and state.next_restart==1060
    assert asyncio.run(ns['guard'](state)) is False
    state.next_restart=0;state.restarts=3
    assert asyncio.run(ns['guard'](state)) is False


def test_profile_is_distinct_and_manual_action_resets_budget():
    changes=dict(replacements())
    assert 'chromium_profile_buyin_chrome' in next(iter(changes.values()))
    assert any('channel="chrome"' in value for value in changes.values())
    assert any('self.restarts = 0' in value and 'await self.ensure_browser()' in value for value in changes.values())
