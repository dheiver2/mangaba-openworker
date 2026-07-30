"""Motor local (Mangaba Local / Ollama) — detecção, auto-start e instalação sob demanda.

Antes disso o app só *apontava* para uma instalação que o usuário tinha de providenciar e manter
no ar: se o Ollama estivesse instalado mas parado, "Detectar" apenas falhava. Estes testes fixam
os três estados que a UI precisa distinguir (rodando / parado / ausente) e as duas garantias que
custam caro se quebrarem: não iniciar processo em máquina alheia, e não executar instalador
silenciosamente. Sem rede e sem spawn real — httpx e Popen são monkeypatchados.
"""

from __future__ import annotations

from types import SimpleNamespace

from mangaba.providers import local_engine as le


def _serving(monkeypatch, ok: bool):
    def fake_get(url, **kwargs):
        if not ok:
            raise RuntimeError("connection refused")
        return SimpleNamespace(status_code=200, json=lambda: {"data": [{"id": "qwen3:4b"}]})

    monkeypatch.setattr("httpx.get", fake_get)


# -- engine_status: os três estados que a UI usa para decidir o que oferecer ------
def test_status_running(monkeypatch):
    _serving(monkeypatch, True)
    monkeypatch.setattr(le, "find_binary", lambda: "/usr/local/bin/ollama")
    assert le.engine_status()["state"] == "running"


def test_status_stopped_when_installed_but_silent(monkeypatch):
    _serving(monkeypatch, False)
    monkeypatch.setattr(le, "find_binary", lambda: "/usr/local/bin/ollama")
    st = le.engine_status()
    # "stopped" é o estado que justifica o auto-start; confundi-lo com "absent" faria a UI
    # oferecer um download de centenas de MB para quem já tem o motor instalado.
    assert st["state"] == "stopped" and st["installed"] is True


def test_status_absent_when_no_binary(monkeypatch):
    _serving(monkeypatch, False)
    monkeypatch.setattr(le, "find_binary", lambda: None)
    assert le.engine_status()["state"] == "absent"


# -- ensure_running --------------------------------------------------------------
def test_ensure_running_is_idempotent(monkeypatch):
    """Já servindo ⇒ nenhum spawn. Um Popen por clique em Detectar seria um vazamento."""
    _serving(monkeypatch, True)
    spawned = []
    monkeypatch.setattr(le.subprocess, "Popen", lambda *a, **k: spawned.append(a))
    assert le.ensure_running()["ok"] is True
    assert spawned == []


def test_ensure_running_without_binary_reports_absent(monkeypatch):
    _serving(monkeypatch, False)
    monkeypatch.setattr(le, "find_binary", lambda: None)
    res = le.ensure_running()
    assert res["ok"] is False and res["state"] == "absent"


def test_ensure_running_spawns_then_waits(monkeypatch):
    """Parado + binário presente ⇒ sobe e confirma pela porta, não pelo código de saída."""
    calls = {"n": 0}

    def fake_get(url, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:  # primeira sondagem: ainda mudo
            raise RuntimeError("refused")
        return SimpleNamespace(status_code=200, json=lambda: {"data": []})

    monkeypatch.setattr("httpx.get", fake_get)
    monkeypatch.setattr(le, "find_binary", lambda: "/usr/local/bin/ollama")
    spawned = []
    monkeypatch.setattr(le.subprocess, "Popen", lambda *a, **k: spawned.append(a[0]))
    monkeypatch.setattr(le.time, "sleep", lambda _s: None)

    res = le.ensure_running()
    assert res["ok"] is True
    assert spawned and spawned[0][1] == "serve"


# -- install ---------------------------------------------------------------------
def test_install_noops_when_already_present(monkeypatch):
    """Nunca baixar centenas de MB por cima de uma instalação que já existe."""
    monkeypatch.setattr(le, "find_binary", lambda: "/usr/local/bin/ollama")
    assert le.install() == {"ok": True, "already": True}


def test_install_on_linux_instructs_instead_of_piping_curl_to_shell(monkeypatch):
    monkeypatch.setattr(le, "find_binary", lambda: None)
    monkeypatch.setattr(le.platform, "system", lambda: "Linux")
    res = le.install()
    # Rodar `curl | sh` sem o usuário ver o que executa é justamente o que não fazemos.
    assert res["ok"] is False and res["manual"] is True


# -- bootstrap (padrão de fábrica: Mangaba Local funcionando sem cliques) ----------
def test_bootstrap_pulls_starter_model_when_none_installed(monkeypatch):
    """Instalação zerada: motor presente e rodando mas sem nenhum modelo ⇒ o bootstrap
    baixa o STARTER_MODEL sozinho — sem isso o app abre 'funcionando' mas mudo."""
    monkeypatch.setattr(le, "find_binary", lambda: "/usr/local/bin/ollama")
    monkeypatch.setattr(le, "is_serving", lambda host=le.DEFAULT_HOST, timeout=1.5: True)
    pulled: list[str] = []
    # Antes do pull não há nada; depois, o starter aparece — como no mundo real.
    monkeypatch.setattr(
        le, "list_models",
        lambda host=le.DEFAULT_HOST, timeout=5.0: [le.STARTER_MODEL] if pulled else [],
    )
    monkeypatch.setattr(
        le, "pull_model",
        lambda tag, host=le.DEFAULT_HOST, progress=None: (pulled.append(tag), {"ok": True})[1],
    )

    res = le.bootstrap()
    assert res["ok"] is True
    assert pulled == [le.STARTER_MODEL]
    assert le.bootstrap_status()["phase"] == "ready"


def test_bootstrap_on_windows_never_autoinstalls(monkeypatch):
    """No Windows a instalação dispara UAC — um prompt de privilégio surgindo sozinho na
    primeira abertura é comportamento de malware. O bootstrap devolve needs_user e o card
    oferece o clique consciente."""
    monkeypatch.setattr(le, "find_binary", lambda: None)
    monkeypatch.setattr(le, "is_serving", lambda host=le.DEFAULT_HOST, timeout=1.5: False)
    monkeypatch.setattr(le.platform, "system", lambda: "Windows")
    monkeypatch.setattr(le, "install", lambda progress=None: (_ for _ in ()).throw(AssertionError("não pode instalar")))

    res = le.bootstrap()
    assert res == {"ok": False, "needs_user": True}
    assert le.bootstrap_status()["phase"] == "needs_user"


def test_bootstrap_skips_pull_when_models_already_exist(monkeypatch):
    """Usuário local que voltou: motor no ar e modelos presentes ⇒ nada de puxar 2 GB de novo."""
    monkeypatch.setattr(le, "find_binary", lambda: "/usr/local/bin/ollama")
    monkeypatch.setattr(le, "is_serving", lambda host=le.DEFAULT_HOST, timeout=1.5: True)
    monkeypatch.setattr(le, "list_models", lambda host=le.DEFAULT_HOST, timeout=5.0: ["gemma4:e4b"])
    monkeypatch.setattr(le, "pull_model", lambda *a, **k: (_ for _ in ()).throw(AssertionError("pull indevido")))

    res = le.bootstrap()
    assert res["ok"] is True and res["models"] == ["gemma4:e4b"]
