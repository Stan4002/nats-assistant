from pathlib import Path
from types import SimpleNamespace

import pytest

from nats_assistant import cli, service
from nats_assistant.config import get_config_path


@pytest.fixture
def fake_systemd(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    executable = tmp_path / "development venv" / "nats-assistant"
    executable.parent.mkdir()
    executable.write_text("executable")
    executable.chmod(0o700)
    monkeypatch.setattr(service, "resolve_executable", lambda: executable)
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(service.subprocess, "run", run)
    return executable, calls


def test_install_generates_only_user_unit_without_activation(fake_systemd):
    executable, calls = fake_systemd
    assert cli.main(["service", "install"]) == 0
    unit = service.service_path()
    text = unit.read_text()
    assert f'ExecStart="{executable}" serve' in text
    assert f'Environment="NATS_CONFIG_FILE={get_config_path()}"' in text
    assert "Restart=on-failure" in text and "WantedBy=default.target" in text
    assert "UMask=0077" in text
    assert "client_secret" not in text and "token.json" not in text
    assert unit.stat().st_mode & 0o777 == 0o600
    assert calls == [(["systemctl", "--user", "daemon-reload"], {"check": False, "timeout": 30})]


@pytest.mark.parametrize("action", ["status", "start", "stop", "restart", "enable", "disable"])
def test_service_actions_use_fixed_safe_argv(fake_systemd, action):
    _, calls = fake_systemd
    assert cli.main(["service", action]) == 0
    assert calls[-1] == (["systemctl", "--user", action, "nats-assistant.service"], {"check": False, "timeout": 30})


def test_uninstall_stops_disables_removes_unit_and_preserves_config(fake_systemd):
    _, calls = fake_systemd
    get_config_path().parent.mkdir(parents=True)
    get_config_path().write_text('timezone = "UTC"')
    assert service.manage_service("install") == 0
    assert service.manage_service("uninstall") == 0
    assert not service.service_path().exists()
    assert get_config_path().exists()
    assert calls[-2][0] == ["systemctl", "--user", "disable", "--now", "nats-assistant.service"]
    assert calls[-1][0] == ["systemctl", "--user", "daemon-reload"]


def test_unmanaged_unit_not_replaced_or_stopped(fake_systemd):
    _, calls = fake_systemd
    path = service.service_path()
    path.parent.mkdir(parents=True)
    path.write_text("[Service]\nExecStart=/usr/bin/other\n")
    with pytest.raises(service.ServiceError):
        service.manage_service("install")
    with pytest.raises(service.ServiceError):
        service.manage_service("uninstall")
    assert calls == []


def test_unit_paths_are_quoted_and_specifiers_escaped():
    text = service.render_service(Path('/opt/with spaces/%literal/$money/nats-assistant'), Path('/tmp/with spaces/%literal/config.toml'))
    assert '%%literal/$money/nats-assistant' in text
    assert 'Environment="NATS_CONFIG_FILE=/tmp/with spaces/%%literal/config.toml"' in text
    with pytest.raises(service.ServiceError):
        service.render_service(Path("/tmp/newline\ncommand"), Path("/tmp/config.toml"))


@pytest.mark.parametrize("character", ['"', "'", "\\"])
def test_systemd_unsupported_executable_path_is_rejected(character):
    with pytest.raises(service.ServiceError, match="unsupported by systemd"):
        service.render_service(Path(f"/tmp/{character}/nats-assistant"), Path("/tmp/config.toml"))


def test_service_rejects_arbitrary_command():
    with pytest.raises(service.ServiceError):
        service.manage_service("restart; injected")


def test_resolve_executable_prefers_current_environment(monkeypatch, tmp_path):
    executable = tmp_path / "bin/nats-assistant"
    executable.parent.mkdir()
    executable.write_text("executable")
    executable.chmod(0o700)
    monkeypatch.setattr(service.sys, "executable", str(tmp_path / "bin/python"))
    monkeypatch.setattr(service.sys, "argv", ["unrelated"])
    monkeypatch.setattr(service.shutil, "which", lambda program: "/usr/bin/nats-assistant")
    assert service.resolve_executable() == executable


def test_systemctl_failure_is_controlled(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise FileNotFoundError("systemctl")
    monkeypatch.setattr(service.subprocess, "run", fail)
    assert cli.main(["service", "status"]) == 1
    assert "Unable to run systemctl --user" in capsys.readouterr().err
