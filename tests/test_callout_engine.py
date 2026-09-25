from core.callout_engine import write_callouts_ass
from core.illustration_plan import IllustrationMoment


def test_callout_ass_tem_animacao_e_texto_revisado(tmp_path):
    path = write_callouts_ass(
        [
            IllustrationMoment(
                start=1.0,
                end=3.5,
                kind="callout",
                callout_text="casa na praia",
            )
        ],
        tmp_path / "callouts.ass",
        1080,
        1920,
    )

    content = path.read_text(encoding="utf-8")
    assert "Style: Callout,Archivo Black" in content
    assert r"\fad(80,220)" in content
    assert r"\fscx55\fscy55" in content
    assert r"\t(0,180,\fscx130\fscy130\frz5)" in content
    assert r"\t(180,360,\fscx110\fscy110\frz-2)" in content
    assert r"\t(360,520,\fscx100\fscy100\frz0)" in content
    assert "CASA NA PRAIA" in content


def test_callout_sem_texto_nao_gera_dialogo(tmp_path):
    path = write_callouts_ass(
        [IllustrationMoment(start=1.0, end=3.5, kind="callout")],
        tmp_path / "callouts.ass",
        1080,
        1920,
    )

    content = path.read_text(encoding="utf-8")
    assert "Dialogue:" not in content