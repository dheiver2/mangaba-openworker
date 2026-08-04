"""Motor local (llama.cpp): catálogo, recomendação por RAM, status e o gate dos modelos
`local:` no seletor. Nada aqui toca rede ou sobe processo — tudo monkeypatched."""

from __future__ import annotations

import time

import pytest

from mangaba.providers import local_engine


def test_catalogo_do_menor_para_o_maior():
    tamanhos = [m["download_gb"] for m in local_engine.CATALOG]
    assert tamanhos == sorted(tamanhos)
    assert [m["tag"] for m in local_engine.CATALOG] == [
        "qwen3-4b",
        "qwen3-8b",
        "qwen3-14b",
        "qwen3-32b",
    ]


def test_recomendacao_por_ram():
    """O maior modelo que a máquina roda bem — com folga de RAM além do arquivo."""
    assert local_engine.recommended(4)["tag"] == "qwen3-4b"
    assert local_engine.recommended(8)["tag"] == "qwen3-8b"
    assert local_engine.recommended(16)["tag"] == "qwen3-14b"
    assert local_engine.recommended(32)["tag"] == "qwen3-32b"


def test_pick_asset_por_plataforma(monkeypatch):
    assets = [
        {"name": "llama-b1-bin-macos-arm64.tar.gz"},
        {"name": "llama-b1-bin-win-cpu-x64.zip"},
        {"name": "llama-b1-bin-ubuntu-x64.tar.gz"},
        {"name": "llama-b1-src.tar.xz"},
    ]
    monkeypatch.setattr(local_engine.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(local_engine.platform, "machine", lambda: "arm64")
    assert "macos-arm64" in local_engine._pick_asset(assets)["name"]
    monkeypatch.setattr(local_engine.platform, "system", lambda: "Windows")
    assert "win-cpu-x64" in local_engine._pick_asset(assets)["name"]


def test_engine_status_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(local_engine, "is_serving", lambda *a, **k: False)
    st = local_engine.engine_status()
    assert st["state"] == "absent" and st["installed"] is False
    assert st["models"] == 0 and st["tags"] == []
    assert st["recommended"]["tag"] in {m["tag"] for m in local_engine.CATALOG}
    assert st["pull"]["phase"] == "idle"


def test_pull_recusa_tag_desconhecida(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path))
    res = local_engine.pull("nao-existe")
    assert res["ok"] is False and "desconhecido" in res["error"]


def test_modelos_locais_aparecem_so_com_arquivo_no_disco(tmp_path, monkeypatch):
    """`local:*` no seletor exige o GGUF baixado — sem chave não pode significar
    sempre-presente (um pref `local:<junk>` renderizaria para sempre)."""
    from mangaba.server.manager import SessionManager

    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(local_engine, "autostart_em_segundo_plano", lambda: False)
    manager = SessionManager(data_dir=tmp_path / "data")
    manager.add_model("local:qwen3-4b")

    assert "local:qwen3-4b" not in manager.get_settings()["models"]

    modelo = local_engine.model_path("qwen3-4b")
    modelo.parent.mkdir(parents=True, exist_ok=True)
    modelo.write_bytes(b"gguf")
    assert "local:qwen3-4b" in manager.get_settings()["models"]


def test_labels_dos_modelos_locais(tmp_path, monkeypatch):
    from mangaba.server.manager import SessionManager

    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(local_engine, "autostart_em_segundo_plano", lambda: False)
    manager = SessionManager(data_dir=tmp_path / "data")
    labels = manager.get_settings()["model_labels"]
    assert labels["local:qwen3-14b"] == "Qwen3 14B · Local"


def test_capabilities_local_e_agentico():
    """A razão de o motor existir: llama-server --jinja dá tool calling nativo ao Qwen3.
    Sem paralelismo — uma chamada por vez mantém o load previsível numa máquina só."""
    from mangaba.providers.capabilities import capabilities_for

    caps = capabilities_for("local:qwen3-14b")
    assert caps.tools is True
    assert caps.streaming is True
    assert caps.parallel_tool_calls is False


def test_descriptor_local_sem_chave():
    from mangaba.providers.registry import get_descriptor

    d = get_descriptor("local")
    assert d is not None and d.needs_key is False
    assert d.recommended_model == "qwen3-4b"
    assert "llama.cpp" in d.blurb


def test_build_local_aponta_para_o_llama_server():
    from mangaba.providers.registry import build_provider_client

    client = build_provider_client("local", {}, secrets=None)
    assert client._base_url == local_engine.DEFAULT_HOST + "/v1"


def test_kill_stale_process_mata_pid_orfao(tmp_path, monkeypatch):
    """Quit do desktop = SIGKILL, que pula o stop(); quem sobe depois lê o PID
    persistido e mata o llama-server órfão antes de tentar subir o seu."""
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path))
    local_engine._write_pidfile(4242)
    mortos = []
    monkeypatch.setattr(local_engine.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(local_engine.os, "kill", lambda pid, sig: mortos.append((pid, sig)))
    local_engine._kill_stale_process()
    assert mortos == [(4242, 9)]
    assert not local_engine._pidfile().exists()  # limpo depois de matar


def test_kill_stale_process_sem_pidfile_e_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path))
    local_engine._pidfile().unlink(missing_ok=True)
    local_engine._kill_stale_process()  # não levanta


def test_download_usa_os_replace_para_sobrescrever(tmp_path, monkeypatch):
    """No Windows Path.rename falha se o destino existe; os.replace sobrescreve.
    Garante que um .part re-baixado substitui um arquivo remanescente."""
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path))
    dest = tmp_path / "bin" / "engine.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"antigo")

    class FakeResp:
        headers = {"content-length": "3"}

        def raise_for_status(self):
            pass

        def iter_bytes(self, chunk_size=0):
            yield b"nov"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(local_engine.httpx, "stream", lambda *a, **k: FakeResp())
    local_engine._download("http://x/y.zip", dest, {"progress": 0.0})
    assert dest.read_bytes() == b"nov"  # sobrescreveu, não levantou FileExistsError


def test_orfao_e_morto_antes_de_stop_apagar_o_pidfile(tmp_path, monkeypatch):
    """Regressão: `stop()` apaga o pidfile no fim, então chamá-lo ANTES de
    `_kill_stale_process()` tornava a recuperação de órfão código morto — no Windows,
    onde o Quit pula o lifespan, o llama-server ficava segurando a porta e o app
    passava a servir o modelo anterior em silêncio."""
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path))
    (tmp_path / "local-engine" / "bin").mkdir(parents=True, exist_ok=True)
    (tmp_path / "local-engine" / "models").mkdir(parents=True, exist_ok=True)

    binario = tmp_path / "local-engine" / "bin" / local_engine._binary_name()
    binario.write_text("#!/bin/sh\n")
    modelo = local_engine.model_path("qwen3-4b")
    modelo.write_bytes(b"gguf")
    local_engine._write_pidfile(4242)

    mortos: list[int] = []
    monkeypatch.setattr(local_engine.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(local_engine.os, "kill", lambda pid, sig: mortos.append(pid))
    monkeypatch.setattr(local_engine, "is_serving", lambda *a, **k: False)
    monkeypatch.setattr(local_engine, "_proc", None)

    class FakeProc:
        pid = 999

        def poll(self):
            return None

    monkeypatch.setattr(local_engine.subprocess, "Popen", lambda *a, **k: FakeProc())
    local_engine.ensure_running("qwen3-4b", wait_s=0)

    assert mortos == [4242], "o órfão do pidfile precisa morrer antes de subirmos o nosso"


def test_primeiro_uso_baixa_sozinho_quando_nao_ha_nenhum_provedor(tmp_path, monkeypatch):
    """Instalação nova sem chave: o app precisa se preparar sozinho. Antes abria em
    'Sem modelo' e mandava a pessoa achar Configurações ▸ Modelos — o funil morria
    exatamente onde o produto deveria ganhar (não exigimos conta nem cartão)."""
    from mangaba.server.manager import SessionManager

    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    chamado: list[bool] = []
    monkeypatch.setattr(
        local_engine, "bootstrap_primeiro_uso", lambda on_ready=None: chamado.append(True) or True
    )
    manager = SessionManager(data_dir=tmp_path / "data")
    assert manager.preparar_primeiro_uso() is True
    assert chamado, "deveria ter disparado o download em segundo plano"


def test_primeiro_uso_nao_gasta_banda_de_quem_ja_tem_chave(tmp_path, monkeypatch):
    """2,5 GB não podem ser baixados nas costas de quem já configurou um provedor."""
    from mangaba.server.manager import SessionManager

    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(
        local_engine, "bootstrap_primeiro_uso", lambda on_ready=None: pytest.fail("não devia baixar")
    )
    manager = SessionManager(data_dir=tmp_path / "data")
    manager.set_provider("anthropic", {"api_key": "sk-ant-x"})
    assert manager.preparar_primeiro_uso() is False


def test_primeiro_uso_escolhe_o_menor_modelo_e_nao_o_recomendado(tmp_path, monkeypatch):
    """Numa máquina de 16 GB o `recommended()` é o 14B (9,3 GB) — minutos de espera.
    Primeiro uso otimiza por TEMPO ATÉ FUNCIONAR; o card oferece o maior depois."""
    monkeypatch.setenv("MANGABA_STATE_DIR", str(tmp_path))
    # `_bootstrap` é global do módulo: sem zerar, a fase deixada por outro teste faz o
    # guard de "já está em andamento" recusar este disparo.
    local_engine._bootstrap.update(phase="idle", progress=0.0, error=None)
    baixados: list[str] = []
    monkeypatch.setattr(local_engine, "find_binary", lambda: "/fake/llama-server")
    monkeypatch.setattr(local_engine, "downloaded_tags", lambda: [])
    monkeypatch.setattr(local_engine, "ensure_running", lambda tag=None, **k: True)
    monkeypatch.setattr(
        local_engine, "_download", lambda url, dest, st: baixados.append(url)
    )

    local_engine.bootstrap_primeiro_uso()
    for _ in range(100):
        if baixados:
            break
        time.sleep(0.05)
    assert baixados and "Qwen3-4B" in baixados[0], baixados
