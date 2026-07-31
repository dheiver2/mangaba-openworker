"""Motor local (Mangaba Local / Ollama) — detecção, auto-start e instalação sob demanda.

Antes disso o app só *apontava* para uma instalação que o usuário tinha de providenciar e manter
no ar: se o Ollama estivesse instalado mas parado, "Detectar" apenas falhava. Estes testes fixam
os três estados que a UI precisa distinguir (rodando / parado / ausente) e as duas garantias que
custam caro se quebrarem: não iniciar processo em máquina alheia, e não executar instalador
silenciosamente. Sem rede e sem spawn real — httpx e Popen são monkeypatchados.
"""

from __future__ import annotations

import os
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
    monkeypatch.setattr(le, "total_ram_gb", lambda: 16.0)  # sem sondar a máquina real
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
    """Instalação zerada: motor presente e rodando mas sem nenhum modelo ⇒ o bootstrap baixa
    um modelo sozinho — sem isso o app abre 'funcionando' mas mudo. Qual modelo depende da
    memória da máquina (test_primeiro_uso_baixa_o_modelo_certo_para_cada_maquina); aqui só
    importa que ALGUM seja baixado, então fixamos a RAM para o teste não depender do host."""
    monkeypatch.setattr(le, "total_ram_gb", lambda: 4.0)  # máquina modesta ⇒ starter
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


# -- recomendação por RAM (o maior modelo que a máquina roda bem) ------------------
def test_recommended_model_scales_with_ram():
    """Cada tier de RAM ganha o maior modelo viável — recomendação fixa (qwen3-coder:30b)
    só servia para quem tem 32 GB; todo o resto via um download impossível."""
    assert le.recommended_model(ram_gb=4)["tag"] == le.STARTER_MODEL
    assert le.recommended_model(ram_gb=8)["tag"] == "qwen2.5:7b-instruct"
    assert le.recommended_model(ram_gb=16)["tag"] == "qwen3:14b"
    assert le.recommended_model(ram_gb=32)["tag"] == "qwen3:32b"
    assert le.recommended_model(ram_gb=64)["tag"] == "qwen3:32b"  # teto deliberado


def test_recommended_model_detects_real_ram():
    """total_ram_gb() precisa funcionar de verdade nesta plataforma (sysctl/meminfo/ctypes)."""
    ram = le.total_ram_gb()
    assert ram > 1.0  # qualquer máquina real tem mais de 1 GB
    assert le.recommended_model()["ram_gb"] == round(ram, 1)


def test_start_pull_refuses_concurrent_downloads(monkeypatch):
    """Dois downloads de GBs em paralelo saturam disco/banda e confundem o progresso da UI."""
    monkeypatch.setitem(le._pull_state, "phase", "pulling")
    monkeypatch.setitem(le._pull_state, "tag", "qwen3:14b")
    res = le.start_pull("qwen3:32b")
    assert res["ok"] is False and "qwen3:14b" in res["error"]


def test_ensure_running_gives_the_engine_room_to_breathe(monkeypatch):
    """O agente manda ~3.2k tokens fixos por turno; com o contexto padrão do Ollama (4096)
    o system prompt e as tools eram truncados em silêncio. O spawn precisa definir contexto
    e keep-alive — respeitando valores que o usuário já tenha no ambiente."""
    monkeypatch.setattr(le, "find_binary", lambda: "/usr/local/bin/ollama")
    monkeypatch.setattr(le, "total_ram_gb", lambda: 16.0)  # 16 GB ⇒ contexto de 16k
    calls = {"n": 0}

    def fake_serving(host=le.DEFAULT_HOST, timeout=1.5):
        calls["n"] += 1
        return calls["n"] > 1  # 1ª sondagem: parado; depois do spawn: no ar

    monkeypatch.setattr(le, "is_serving", fake_serving)
    captured = {}
    monkeypatch.setattr(
        le.subprocess, "Popen", lambda *a, **k: captured.update(env=k.get("env") or {})
    )
    monkeypatch.setattr(le.time, "sleep", lambda _s: None)

    assert le.ensure_running()["ok"] is True
    assert captured["env"]["OLLAMA_CONTEXT_LENGTH"] == "16384"
    assert captured["env"]["OLLAMA_KEEP_ALIVE"] == "30m"

    # o usuário manda: valor já presente no ambiente não é sobrescrito
    calls["n"] = 0
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "8192")
    assert le.ensure_running()["ok"] is True
    assert captured["env"]["OLLAMA_CONTEXT_LENGTH"] == "8192"


def test_starter_model_is_commercially_licensed():
    """qwen2.5:3b-instruct está sob 'Qwen RESEARCH LICENSE' (uso não comercial) — não pode
    voltar a ser o padrão de fábrica. O starter deve ser um tag da família qwen3 (Apache-2.0)."""
    assert le.STARTER_MODEL.startswith("qwen3")


# -- correções da auditoria de 2026-07-31 ------------------------------------------
def test_pull_recusa_registry_de_terceiros():
    """`/api/pull` do Ollama aceita registries arbitrários ("evil.example/x"): um POST
    autenticado bastaria para a máquina baixar dezenas de GB de origem hostil e deixar um
    modelo estranho selecionável no app. Só a biblioteca oficial e o HF passam."""
    assert le.tag_permitido("qwen3:4b")
    assert le.tag_permitido("hf.co/prism-ml/Bonsai-27B-gguf:Q1_0")
    assert not le.tag_permitido("evil.example/org/modelo")
    assert not le.tag_permitido("../../etc/passwd")
    assert not le.tag_permitido("registry.local:5000/x")
    assert not le.tag_permitido("")
    assert le.start_pull("evil.example/org/m")["ok"] is False


def test_install_recusa_zip_com_travessia(monkeypatch, tmp_path):
    """Zip Slip: `extractall` puro aceita membros com `../`, então um pacote adulterado
    escreveria em ~/Library/LaunchAgents (persistência). O pacote inteiro é recusado."""
    import zipfile

    origem = tmp_path / "origem"
    origem.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    malicioso = origem / "Ollama-darwin.zip"  # separado do cache: o download grava lá
    with zipfile.ZipFile(malicioso, "w") as zf:
        zf.writestr("../../../tmp/evil.plist", "payload")

    monkeypatch.setattr(le, "find_binary", lambda: None)
    monkeypatch.setattr(le.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(le, "_cache_dir", lambda: cache)
    monkeypatch.setattr(le, "_DOWNLOADS", {"Darwin": ("https://x/Ollama-darwin.zip", "Ollama-darwin.zip")})

    class FakeStream:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        headers = {"content-length": "1"}
        def raise_for_status(self): pass
        def iter_bytes(self, _n): yield malicioso.read_bytes()

    monkeypatch.setattr(le.httpx, "stream", lambda *a, **k: FakeStream())
    extraiu = []
    monkeypatch.setattr(
        zipfile.ZipFile, "extractall", lambda self, *a, **k: extraiu.append(True)
    )
    res = le.install()
    assert res["ok"] is False and "inválidos" in res["error"]
    assert not extraiu  # nada foi extraído


def test_motor_local_nao_herda_segredos_do_sidecar(monkeypatch):
    """`dict(os.environ)` levava MANGABA_API_TOKEN e chaves de provedor para um processo que
    sobrevive ao sidecar e cujo ambiente qualquer processo do usuário lê."""
    monkeypatch.setenv("MANGABA_API_TOKEN", "segredo-do-sidecar")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-nao-vaze-isso")
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11434")
    monkeypatch.setattr(le, "find_binary", lambda: "/usr/local/bin/ollama")
    n = {"i": 0}

    def alive(host=le.DEFAULT_HOST, timeout=1.5):
        n["i"] += 1
        return n["i"] > 1

    monkeypatch.setattr(le, "is_serving", alive)
    cap = {}
    monkeypatch.setattr(le.subprocess, "Popen", lambda *a, **k: cap.update(env=k["env"]))
    monkeypatch.setattr(le.time, "sleep", lambda _s: None)

    le.ensure_running()
    assert "MANGABA_API_TOKEN" not in cap["env"]
    assert "OPENAI_API_KEY" not in cap["env"]
    assert cap["env"]["OLLAMA_HOST"] == "127.0.0.1:11434"  # o que o motor precisa, fica
    assert "PATH" in cap["env"]


def test_install_concorrente_nao_corrompe_o_download(monkeypatch):
    """Bootstrap e clique em 'Instalar' baixavam ~180 MB para o MESMO arquivo ao mesmo
    tempo: os streams se intercalavam e o zip saía lixo."""
    monkeypatch.setattr(le, "find_binary", lambda: None)
    le._install_lock.acquire()
    try:
        res = le.install()
        assert res["ok"] is False and "andamento" in res["error"]
    finally:
        le._install_lock.release()


# -- caminhos que SÓ existem no Windows (bug relatado: "sem modelo" no chat) --------
def test_contexto_escala_com_a_memoria_da_maquina():
    """16k fixo custava ~2,4 GB de KV cache num modelo 4B e, com os pesos, passava de 4,9 GB:
    numa maquina de 8 GB com Windows a alocacao falha e o motor devolve algo que nao e JSON.
    Contexto menor degrada a memoria da conversa; contexto grande demais impede conversar."""
    from mangaba.providers.local_engine import contexto_para_a_maquina as ctx

    assert ctx(ram_gb=4) == 4096
    assert ctx(ram_gb=8) == 8192
    assert ctx(ram_gb=16) == 16384
    assert ctx(ram_gb=64) == 16384  # teto: acima disso o ganho nao paga o KV cache
    # o piso ainda precisa comportar os ~3.200 tokens fixos do agente
    assert ctx(ram_gb=4) > 3200


def test_env_do_motor_sobrevive_ao_caixa_alta_do_windows(monkeypatch):
    """No Windows o `os.environ` do Python MAIÚSCULA as chaves: SystemRoot vira SYSTEMROOT.
    A lista de essenciais tinha grafia mista, então o SYSTEMROOT era descartado — e sem ele
    os sockets do Windows não inicializam: o `ollama serve` que o app subisse morreria."""
    monkeypatch.setattr(le, "find_binary", lambda: "C:/ollama.exe")
    # exatamente como o Windows entrega (tudo em caixa alta), mais um segredo que NÃO pode passar
    for k in list(os.environ):
        monkeypatch.delenv(k, raising=False)
    for k, v in {
        "SYSTEMROOT": r"C:\Windows",
        "WINDIR": r"C:\Windows",
        "PATHEXT": ".COM;.EXE",
        "LOCALAPPDATA": r"C:\Users\u\AppData\Local",
        "PATH": r"C:\Windows\system32",
        "MANGABA_API_TOKEN": "segredo",
        "ANTHROPIC_API_KEY": "sk-nao-vaze",
    }.items():
        monkeypatch.setenv(k, v)

    n = {"i": 0}
    monkeypatch.setattr(le, "is_serving", lambda host=le.DEFAULT_HOST, timeout=1.5: n.__setitem__("i", n["i"] + 1) or n["i"] > 1)
    cap = {}
    monkeypatch.setattr(le.subprocess, "Popen", lambda *a, **k: cap.update(env=k["env"]))
    monkeypatch.setattr(le.time, "sleep", lambda _s: None)

    le.ensure_running()
    assert cap["env"]["SYSTEMROOT"] == r"C:\Windows"  # o que quebrava o spawn
    assert cap["env"]["WINDIR"] and cap["env"]["PATHEXT"]
    assert "MANGABA_API_TOKEN" not in cap["env"]  # e o filtro continua barrando segredo
    assert "ANTHROPIC_API_KEY" not in cap["env"]


def test_sonda_do_motor_usa_ipv4_literal():
    """`localhost` no Windows resolve ::1 antes do IPv4 e o Ollama escuta em IPv4: cada
    sonda pagava uma tentativa perdida, o bastante para estourar o timeout do gate que
    decide se os modelos aparecem no chat."""
    assert le.DEFAULT_HOST == "http://127.0.0.1:11434"


def test_windows_espera_o_usuario_terminar_o_instalador(monkeypatch):
    """Entregar o instalador e conferir na hora seguinte encontrava a máquina ainda sem
    binário (o usuário leva minutos no UAC + assistente) e voltava a `needs_user`: o motor
    subia depois e o modelo inicial NUNCA era baixado — chat "sem modelo" para sempre."""
    tentativas = {"n": 0}

    def binario_aparece_na_terceira():
        tentativas["n"] += 1
        return "C:/ollama.exe" if tentativas["n"] >= 3 else None

    monkeypatch.setattr(le, "find_binary", binario_aparece_na_terceira)
    monkeypatch.setattr(le, "is_serving", lambda host=le.DEFAULT_HOST, timeout=1.5: False)
    monkeypatch.setattr(le.time, "sleep", lambda _s: None)
    chamou = []
    monkeypatch.setattr(le, "bootstrap", lambda host=le.DEFAULT_HOST: chamou.append(host) or {"ok": True})

    res = le.aguardar_e_continuar(minutos=1)
    assert res["ok"] is True
    assert chamou, "o bootstrap tem de continuar assim que o motor aparece"
    assert tentativas["n"] >= 3  # esperou de verdade em vez de desistir na primeira


def test_app_sobe_o_motor_sozinho_quando_o_encontra_parado(monkeypatch):
    """O motor é responsabilidade do APP: quem fechou a bandeja do Ollama (ou está num
    Windows onde ela não subiu no login) ficava com o motor parado e o chat "sem modelo",
    sem nada explicando. Ver o motor parado com binário presente basta para subi-lo."""
    le._ULTIMO_AUTOSTART = 0.0
    monkeypatch.setattr(le, "find_binary", lambda: "/usr/local/bin/ollama")
    monkeypatch.setattr(le, "is_serving", lambda host=le.DEFAULT_HOST, timeout=1.5: False)
    subiu = []
    monkeypatch.setattr(
        le.threading, "Thread", lambda **k: SimpleNamespace(start=lambda: subiu.append(k["name"]))
    )

    st = le.engine_status()
    assert st["state"] == "stopped"
    assert subiu == ["motor-autostart"], "ver parado tem de disparar o autostart"

    # e não pode virar tempestade: get_settings sonda o tempo todo
    subiu.clear()
    le.engine_status()
    assert subiu == [], "tentativas seguidas dentro do intervalo são ignoradas"


def test_autostart_nao_tenta_sem_binario(monkeypatch):
    """Sem binário instalado não há o que subir — esse é caso de INSTALAÇÃO, e insistir só
    gastaria spawn a cada sonda."""
    le._ULTIMO_AUTOSTART = 0.0
    monkeypatch.setattr(le, "find_binary", lambda: None)
    monkeypatch.setattr(
        le.threading, "Thread", lambda **k: (_ for _ in ()).throw(AssertionError("spawn indevido"))
    )
    assert le.autostart_em_segundo_plano() is False


def test_primeiro_uso_baixa_o_modelo_certo_para_cada_maquina():
    """O primeiro uso baixava sempre o mesmo modelo pequeno em qualquer maquina: quem tinha
    32 GB ganhava um 4B por padrao e quem tinha 4 GB ganhava um download que talvez nem
    coubesse. Agora a escolha acompanha a memoria — limitada por um teto, porque puxar 20 GB
    sozinho na primeira abertura seria abusivo (o modelo maior fica a um clique no card)."""
    from mangaba.providers.local_engine import (
        _TETO_DOWNLOAD_AUTOMATICO_GB as TETO,
        modelo_inicial_para_a_maquina as inicial,
        recommended_model,
    )

    assert inicial(ram_gb=4)["tag"] == "qwen3:4b"
    assert inicial(ram_gb=8)["tag"] == "qwen2.5:7b-instruct"  # maquina melhor, modelo melhor

    # nenhuma maquina, por maior que seja, dispara um download automatico gigante...
    for ram in (16, 32, 64, 128):
        assert inicial(ram_gb=ram)["download_gb"] <= TETO
    # ...mas o card continua oferecendo o modelo grande de verdade para essa maquina
    assert recommended_model(ram_gb=32)["tag"] == "qwen3:32b"
    assert recommended_model(ram_gb=32)["download_gb"] > TETO
