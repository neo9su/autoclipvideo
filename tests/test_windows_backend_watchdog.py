import importlib.util
from pathlib import Path
import pytest

@pytest.fixture
def guard(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('guard',Path(__file__).parents[1]/'backend/windows_backend_watchdog.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    m.MISSES=tmp_path/'miss';m.LOG=tmp_path/'log';return m

def test_healthy_resets_stale_failure_counter(guard,monkeypatch):
    guard.MISSES.write_text('12');monkeypatch.setattr(guard,'listeners',lambda:[10]);monkeypatch.setattr(guard,'process_session',lambda pid:2);monkeypatch.setattr(guard,'healthy',lambda:True)
    assert guard.run_once()=='healthy' and guard.MISSES.read_text()=='0'

def test_busy_listener_is_preserved(guard,monkeypatch):
    monkeypatch.setattr(guard,'listeners',lambda:[10]);monkeypatch.setattr(guard,'process_session',lambda pid:2);monkeypatch.setattr(guard,'healthy',lambda:False)
    monkeypatch.setattr(guard,'start_desktop_task',lambda:pytest.fail('Must not restart a busy listener'))
    assert guard.run_once()=='listener-present-http-unavailable'

def test_service_session_is_reported_without_killing_work(guard,monkeypatch):
    monkeypatch.setattr(guard,'listeners',lambda:[10]);monkeypatch.setattr(guard,'process_session',lambda pid:0)
    monkeypatch.setattr(guard,'start_desktop_task',lambda:pytest.fail('Must not duplicate Session 0 listener'))
    assert guard.run_once()=='session0'

def test_absent_listener_only_starts_desktop_task(guard,monkeypatch):
    calls=[];monkeypatch.setattr(guard,'listeners',lambda:[]);monkeypatch.setattr(guard,'start_desktop_task',lambda:calls.append(guard.TASK) or 0)
    assert guard.run_once()=='waiting';assert guard.run_once()=='waiting';assert guard.run_once()=='desktop-requested'
    assert calls==['DouyinBackend8899SusunInteractive']

def test_missing_login_never_falls_back_to_system(guard,monkeypatch):
    monkeypatch.setattr(guard,'listeners',lambda:[]);monkeypatch.setattr(guard,'start_desktop_task',lambda:1)
    assert guard.run_once(miss_limit=1)=='desktop-login-required'
