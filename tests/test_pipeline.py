from pathlib import Path

import pytest

from config.settings import Settings
from core.pipeline import Pipeline, PipelineContext, PipelineStep


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
