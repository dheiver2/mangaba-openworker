"""list_artifacts nunca deve descer em diretórios de dados de aplicativos do SO.

No macOS 14+, apenas percorrer ~/Library/Application Support (containers de outros apps)
dispara a proteção App Data do TCC e o usuário vê um alerta assustador "Mangaba would like
to access data from other apps". O painel de artefatos atualiza a cada turno, então um
workspace no diretório home produzia esse alerta sem motivo. A poda precisa acontecer
DURANTE a caminhada (rglob desce primeiro e filtra depois, que foi o que causou o bug).
"""

import os

from mangaba.server.manager import SessionManager
from mangaba.tools.search import OS_DATA_DIRS


def _ws(tmp_path):
    ws = tmp_path / "home"
    (ws / "Library" / "Application Support" / "SomeOtherApp").mkdir(parents=True)
    (ws / "Library" / "Application Support" / "SomeOtherApp" / "secrets.json").write_text("{}")
    (ws / "Library" / "notes.md").write_text("# private")
    (ws / "node_modules" / "pkg").mkdir(parents=True)
    (ws / "node_modules" / "pkg" / "readme.md").write_text("# dep")
    (ws / "report.md").write_text("# real artifact")
    return ws


def test_os_data_dirs_are_not_traversed(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    walked: list[str] = []
    real_walk = os.walk

    def spy(top, *a, **k):
        for dirpath, dirs, files in real_walk(top, *a, **k):
            walked.append(dirpath)
            yield dirpath, dirs, files

    monkeypatch.setattr("mangaba.server.manager.os.walk", spy)
    m = SessionManager(data_dir=tmp_path / "data", workspace=str(ws))
    names = [a["name"] for a in m.list_artifacts("s1")]

    assert "report.md" in names
    # O arquivo privado é pulado E o diretório dele nunca foi visitado (o gatilho do TCC).
    assert "notes.md" not in names
    assert "secrets.json" not in names
    assert not any("Library" in p for p in walked), f"descended into Library: {walked}"
    assert not any("node_modules" in p for p in walked)


def test_os_data_dirs_cover_mac_and_windows():
    assert {"Library", "AppData", "Application Data"} <= OS_DATA_DIRS
