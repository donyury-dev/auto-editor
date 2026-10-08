"""Testes da sugestão automática de ícones do pack nos cartões."""

from pathlib import Path

from core.edit_plan import LayoutScene


class FakeItem:
    def __init__(self, path: str, name: str):
        self.path = Path(path)
        self.name = name


class FakePack:
    def __init__(self, items: dict[str, list[FakeItem]]):
        self._items = items

    def category_items(self, category: str):
        return self._items.get(category, [])


class Ctx:
    class _Plan:
        layouts: list

    def __init__(self, layouts):
        self.edit_plan = self._Plan()
        self.edit_plan.layouts = layouts


def test_sugestao_casa_palavra_com_nome_do_arquivo():
    from server.app import _suggest_step_images

    pack = FakePack(
        {
            "emojis": [FakeItem("/pack/tecnologia.png", "tecnologia")],
            "elementos": [FakeItem("/pack/grafo.png", "grafo")],
        }
    )
    sc = LayoutScene(start=0, end=6, steps=["Tecnologia que conecta", "Outro tema"])
    ctx = Ctx([sc])

    _suggest_step_images(pack, ctx)
    assert sc.step_images[0] == "/pack/tecnologia.png"
    assert sc.step_images[1] == ""  # sem casamento → sem ícone


def test_sugestao_nao_sobrescreve_escolha_manual():
    from server.app import _suggest_step_images

    pack = FakePack(
        {"emojis": [FakeItem("/pack/tecnologia.png", "tecnologia")]}
    )
    sc = LayoutScene(start=0, end=6, steps=["Tecnologia"])
    sc.step_images = ["/escolhido.png"]
    ctx = Ctx([sc])

    _suggest_step_images(pack, ctx)
    assert sc.step_images == ["/escolhido.png"]


def test_sugestao_sem_pack_ou_sem_cenas():
    from server.app import _suggest_step_images

    _suggest_step_images(None, Ctx([]))
    pack = FakePack({})
    sc = LayoutScene(start=0, end=6, steps=["Tema"])
    ctx = Ctx([sc])
    _suggest_step_images(pack, ctx)
    assert sc.step_images == []
