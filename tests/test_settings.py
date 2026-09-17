from config.settings import OutputFormat, Settings


def test_padroes():
    settings = Settings()
    assert settings.output_format == OutputFormat.VERTICAL
    assert settings.whisper_model == "small"
    assert settings.max_words_per_chunk == 4


def test_roundtrip_salva_e_carrega(tmp_path):
    settings = Settings(
        output_format=OutputFormat.HORIZONTAL,
        whisper_model="base",
        max_words_per_chunk=5,
        max_chunk_duration=3.0,
    )
    path = tmp_path / "settings.json"
    settings.save(path)

    loaded = Settings.load(path)
    assert loaded == settings


def test_load_com_arquivo_inexistente_retorna_padroes(tmp_path):
    settings = Settings.load(tmp_path / "nao_existe.json")
    assert settings == Settings()
