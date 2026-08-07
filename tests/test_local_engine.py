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

    Paralelismo LIGADO desde 2026-08-06: o template do Qwen3 emite vários <tool_call> num
    turno só, e cada hop economizado poupa uma geração inteira a ~30 tok/s. A justificativa
    antiga ("uma chamada por vez mantém o load previsível") confundia PEDIR com EXECUTAR —
    o engine já executa as chamadas em sequência de qualquer jeito."""
    from mangaba.providers.capabilities import capabilities_for

    caps = capabilities_for("local:qwen3-14b")
    assert caps.tools is True
    assert caps.streaming is True
    assert caps.parallel_tool_calls is True


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


# -- Windows: GPU (Vulkan) com fallback seguro para CPU (plano de paridade Win/macOS) -------


_ASSETS_WIN_COM_VULKAN = [
    {"name": "llama-b1-bin-macos-arm64.tar.gz"},
    {"name": "llama-b1-bin-win-cpu-x64.zip"},
    {"name": "llama-b1-bin-win-vulkan-x64.zip"},
]


def test_pick_asset_prefere_vulkan_no_windows_com_gpu(monkeypatch):
    monkeypatch.setattr(local_engine.platform, "system", lambda: "Windows")
    escolhido = local_engine._pick_asset(_ASSETS_WIN_COM_VULKAN, preferir_gpu=True)
    assert "vulkan" in escolhido["name"]


def test_pick_asset_fica_em_cpu_no_windows_sem_gpu(monkeypatch):
    monkeypatch.setattr(local_engine.platform, "system", lambda: "Windows")
    escolhido = local_engine._pick_asset(_ASSETS_WIN_COM_VULKAN, preferir_gpu=False)
    assert "vulkan" not in escolhido["name"] and "win-cpu-x64" in escolhido["name"]


def test_pick_asset_cai_pra_cpu_se_a_release_nao_tiver_vulkan(monkeypatch):
    """A busca por Vulkan e a de CPU vivem na MESMA lista de tokens: se uma release futura
    renomear ou remover o asset Vulkan, a escolha cai para CPU sozinha — nunca para
    'nenhum asset', que derrubaria o download inteiro por causa de uma preferência."""
    monkeypatch.setattr(local_engine.platform, "system", lambda: "Windows")
    sem_vulkan = [a for a in _ASSETS_WIN_COM_VULKAN if "vulkan" not in a["name"]]
    escolhido = local_engine._pick_asset(sem_vulkan, preferir_gpu=True)
    assert escolhido is not None and "win-cpu-x64" in escolhido["name"]


def test_pick_asset_no_windows_sem_gpu_explicita_nao_chama_powershell(monkeypatch):
    """`preferir_gpu=False` explícito não pode disparar a sondagem de hardware — só o modo
    'decidir sozinho' (None) precisa perguntar ao Windows o que existe."""
    monkeypatch.setattr(local_engine.platform, "system", lambda: "Windows")

    def _explode(*a, **k):
        raise AssertionError("não deveria sondar GPU quando preferir_gpu já foi decidido")

    monkeypatch.setattr(local_engine.subprocess, "run", _explode)
    local_engine._pick_asset(_ASSETS_WIN_COM_VULKAN, preferir_gpu=False)


def test_deteccao_de_gpu_ignora_adaptador_de_software(monkeypatch):
    """Toda VM sem passthrough de GPU tem um 'Microsoft Basic Render/Display Driver' — se a
    detecção contasse isso como GPU, toda VM Windows tentaria (e falharia) rodar Vulkan."""
    import subprocess as _subprocess

    class _Saida:
        stdout = "Microsoft Basic Render Driver"

    monkeypatch.delenv("MANGABA_LOCAL_ENGINE_GPU", raising=False)
    monkeypatch.setattr(local_engine.platform, "system", lambda: "Windows")
    monkeypatch.setattr(local_engine.subprocess, "run", lambda *a, **k: _Saida())
    assert local_engine._gpu_disponivel_windows() is False


def test_deteccao_de_gpu_reconhece_gpu_de_verdade(monkeypatch):
    class _Saida:
        stdout = "NVIDIA GeForce RTX 4060"

    monkeypatch.delenv("MANGABA_LOCAL_ENGINE_GPU", raising=False)
    monkeypatch.setattr(local_engine.platform, "system", lambda: "Windows")
    monkeypatch.setattr(local_engine.subprocess, "run", lambda *a, **k: _Saida())
    assert local_engine._gpu_disponivel_windows() is True


def test_deteccao_de_gpu_nunca_levanta(monkeypatch):
    """Best-effort de verdade: PowerShell ausente, timeout, WMI bloqueado por política —
    nada disso pode derrubar a instalação do motor. Degrada para 'sem GPU', o lado seguro."""

    def _explode(*a, **k):
        raise TimeoutError("powershell não respondeu")

    monkeypatch.delenv("MANGABA_LOCAL_ENGINE_GPU", raising=False)
    monkeypatch.setattr(local_engine.platform, "system", lambda: "Windows")
    monkeypatch.setattr(local_engine.subprocess, "run", _explode)
    assert local_engine._gpu_disponivel_windows() is False


def test_variavel_de_ambiente_forca_a_decisao_sem_tocar_hardware():
    """Escape hatch para testar o caminho Vulkan (ou negá-lo) numa máquina de
    desenvolvimento sem GPU real — inclusive fora do Windows, já que o CI roda em Mac/Linux."""
    import os as _os

    _os.environ["MANGABA_LOCAL_ENGINE_GPU"] = "1"
    try:
        assert local_engine._gpu_disponivel_windows() is True
    finally:
        _os.environ.pop("MANGABA_LOCAL_ENGINE_GPU", None)
    _os.environ["MANGABA_LOCAL_ENGINE_GPU"] = "0"
    try:
        assert local_engine._gpu_disponivel_windows() is False
    finally:
        _os.environ.pop("MANGABA_LOCAL_ENGINE_GPU", None)


def test_marcador_de_flavor_reflete_o_asset_instalado(tmp_path, monkeypatch):
    """`install()` grava qual build entrou (vulkan/cpu) — é o que permite ao fallback em
    tempo de execução saber, sem adivinhar, se vale a pena tentar reinstalar em CPU."""
    monkeypatch.setattr(local_engine, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(local_engine.platform, "system", lambda: "Windows")

    class _Resposta:
        def json(self):
            return {
                "assets": [
                    {
                        "name": "llama-b1-bin-win-vulkan-x64.zip",
                        "browser_download_url": "https://exemplo/vulkan.zip",
                    }
                ]
            }

    monkeypatch.setattr(local_engine.httpx, "get", lambda *a, **k: _Resposta())

    def _baixar_falso(url, dest, state):
        import zipfile as _zipfile

        dest.parent.mkdir(parents=True, exist_ok=True)
        with _zipfile.ZipFile(dest, "w") as zf:
            zf.writestr(local_engine._binary_name(), "binario falso")

    monkeypatch.setattr(local_engine, "_download", _baixar_falso)

    assert local_engine.instalado_com_gpu() is False  # sem instalação ainda: CPU por padrão
    resultado = local_engine.install(preferir_gpu=True)
    assert resultado["ok"] is True
    assert local_engine.instalado_com_gpu() is True


def test_ausencia_do_marcador_conta_como_cpu(tmp_path, monkeypatch):
    """Instalação de antes desta mudança não tem o arquivo .flavor — tem de degradar para
    'CPU', o lado que nunca dispara o fallback (que reinstalaria à toa)."""
    monkeypatch.setattr(local_engine, "_state_dir", lambda: tmp_path)
    (tmp_path / "bin").mkdir()
    assert local_engine.instalado_com_gpu() is False


def test_ensure_running_cai_para_cpu_quando_vulkan_nao_sobe(tmp_path, monkeypatch):
    """A prova de ponta a ponta do fallback: build Vulkan instalada, processo morre no
    arranque (sem driver compatível) — em vez de o provedor Local ficar morto para sempre
    (o que já aconteceu de verdade com o `-fa` sem valor), reinstala em CPU e tenta de novo."""
    monkeypatch.setattr(local_engine, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(local_engine.platform, "system", lambda: "Windows")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / local_engine._binary_name()).write_text("binario falso")
    local_engine._flavor_path().write_text("vulkan")
    monkeypatch.setattr(local_engine, "downloaded_tags", lambda: ["qwen3-4b"])
    monkeypatch.setattr(local_engine, "model_path", lambda tag: tmp_path / "modelo.gguf")
    monkeypatch.setattr(local_engine, "is_serving", lambda *a, **k: False)
    monkeypatch.setattr(local_engine, "_kill_stale_process", lambda: None)
    monkeypatch.setattr(local_engine, "_esperar_porta_livre", lambda *a, **k: True)
    monkeypatch.setattr(local_engine, "_write_pidfile", lambda pid: None)

    chamadas_de_reinstalacao = []

    def _reinstalar_falso():
        chamadas_de_reinstalacao.append(True)
        # simula a reinstalação bem-sucedida em CPU: apaga o marcador de GPU
        local_engine._flavor_path().write_text("cpu")
        return {"ok": True}

    monkeypatch.setattr(local_engine, "reinstalar_forcando_cpu", _reinstalar_falso)

    class _ProcessoMorto:
        def poll(self):
            return 1  # já morreu — simula o crash no arranque

        pid = 4242

    monkeypatch.setattr(
        local_engine.subprocess, "Popen", lambda *a, **k: _ProcessoMorto()
    )

    assert local_engine.ensure_running("qwen3-4b", wait_s=1.0) is False
    # reinstalou em CPU exatamente uma vez — não entrou num laço de tentativas
    assert chamadas_de_reinstalacao == [True]


def test_ensure_running_nao_reinstala_quando_ja_esta_em_cpu(tmp_path, monkeypatch):
    """Sem o marcador Vulkan, uma falha de arranque é outra coisa (binário corrompido,
    porta ocupada por outro processo) — reinstalar não ajudaria, só perderia tempo."""
    monkeypatch.setattr(local_engine, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(local_engine.platform, "system", lambda: "Windows")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / local_engine._binary_name()).write_text("binario falso")
    local_engine._flavor_path().write_text("cpu")
    monkeypatch.setattr(local_engine, "downloaded_tags", lambda: ["qwen3-4b"])
    monkeypatch.setattr(local_engine, "model_path", lambda tag: tmp_path / "modelo.gguf")
    monkeypatch.setattr(local_engine, "is_serving", lambda *a, **k: False)
    monkeypatch.setattr(local_engine, "_kill_stale_process", lambda: None)
    monkeypatch.setattr(local_engine, "_esperar_porta_livre", lambda *a, **k: True)
    monkeypatch.setattr(local_engine, "_write_pidfile", lambda pid: None)

    def _nao_deveria_chamar():
        raise AssertionError("não deveria reinstalar quando já está em CPU")

    monkeypatch.setattr(local_engine, "reinstalar_forcando_cpu", _nao_deveria_chamar)

    class _ProcessoMorto:
        def poll(self):
            return 1

        pid = 4242

    monkeypatch.setattr(
        local_engine.subprocess, "Popen", lambda *a, **k: _ProcessoMorto()
    )

    assert local_engine.ensure_running("qwen3-4b", wait_s=1.0) is False


def test_reinstalar_forcando_cpu_pede_asset_sem_gpu(tmp_path, monkeypatch):
    monkeypatch.setattr(local_engine, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(local_engine.platform, "system", lambda: "Windows")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / local_engine._binary_name()).write_text("build vulkan antiga")
    local_engine._flavor_path().write_text("vulkan")

    pedido = {}

    def _install_falso(*, preferir_gpu=None):
        pedido["preferir_gpu"] = preferir_gpu
        return {"ok": True}

    monkeypatch.setattr(local_engine, "install", _install_falso)
    resultado = local_engine.reinstalar_forcando_cpu()
    assert resultado["ok"] is True
    assert pedido["preferir_gpu"] is False
    # o binário antigo foi removido antes de pedir a reinstalação
    assert not (tmp_path / "bin" / local_engine._binary_name()).exists()
