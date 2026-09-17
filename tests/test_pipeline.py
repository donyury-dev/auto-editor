from pathlib import Path
import os
import time

import pytest

from config.settings import Settings
from core.pipeline import (
    Pipeline,
    PipelineContext,
    PipelineStep,
    cleanup_stale_sessions,
)


class FakeStep(PipelineStep):
    def __init__(self, name, weight, recorder, fail=False):
        self.name = name
        self.weight = weight
        self.recorder = recorder
        self.fail = fail

    def run(self, ctx, progress):
        self.recorder.append(self.name)
        progress(0.5, "metade")
        progress(1.0, "pronto")
        if self.fail:
            raise RuntimeError("boom")


def make_ctx(tmp_path) -> PipelineContext:
    return PipelineContext(input_path=tmp_path / "in.mp4", settings=Settings())


def test_etapas_executam_em_ordem_com_progresso_monotonico(tmp_path):
    recorder: list[str] = []
    pipeline = Pipeline([FakeStep("a", 1.0, recorder), FakeStep("b", 1.0, recorder)])
    ctx = make_ctx(tmp_path)

    reports: list[tuple[float, str, str]] = []
    pipeline.run(ctx, lambda o, s, m: reports.append((o, s, m)))

    assert recorder == ["a", "b"]
    overalls = [r[0] for r in reports]
    assert overalls == sorted(overalls)
    assert overalls[-1] == 1.0
    # diretório de trabalho é limpo após sucesso
    assert not ctx.work_dir.exists()


def test_falha_interrompe_e_preserva_diretorio_para_debug(tmp_path):
    recorder: list[str] = []
    pipeline = Pipeline(
        [FakeStep("a", 1.0, recorder, fail=True), FakeStep("b", 1.0, recorder)]
    )
    ctx = make_ctx(tmp_path)

    with pytest.raises(RuntimeError, match="boom"):
        pipeline.run(ctx)

    assert recorder == ["a"]
    assert ctx.work_dir.exists()


def test_contexto_carrega_dados_entre_etapas(tmp_path):
    class WriteStep(PipelineStep):
        name = "write"
        weight = 1.0

        def run(self, ctx, progress):
            ctx.transcript = "marker"
            progress(1.0, "ok")

    class ReadStep(PipelineStep):
        name = "read"
        weight = 1.0

        def run(self, ctx, progress):
            assert ctx.transcript == "marker"
            progress(1.0, "ok")

    pipeline = Pipeline([WriteStep(), ReadStep()])
    pipeline.run(make_ctx(tmp_path))


def test_cleanup_stale_sessions_remove_apenas_antigas(tmp_path):
    old_session = tmp_path / "20200101_000000"
    fresh_session = tmp_path / "29991231_235959"
    old_session.mkdir()
    fresh_session.mkdir()
    # marca a sessão "antiga" com mtime de 48h atrás
    stale_time = time.time() - 48 * 3600
    os.utime(old_session, (stale_time, stale_time))

    removed = cleanup_stale_sessions(max_age_hours=24.0, base_dir=tmp_path)

    assert removed == 1
    assert not old_session.exists()
    assert fresh_session.exists()


def test_cleanup_com_diretorio_inexistente_nao_erro(tmp_path):
    assert cleanup_stale_sessions(base_dir=tmp_path / "nao_existe") == 0
