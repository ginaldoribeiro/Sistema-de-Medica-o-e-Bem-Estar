"""Ponto de entrada do app MedRemind.

Uso:
    python -m medremind.main            # janela desktop
    python -m medremind.main --web      # no navegador (http://localhost:8550)
    python -m medremind.main --demo     # carrega dados de exemplo
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import flet as ft

from .core.container import Container
from .core.demo import seed_demo
from .ui.app import MedRemindApp

ASSETS = str(Path(__file__).resolve().parent.parent / "assets")


def build_main(demo: bool = False, db_path: str | None = None):
    container = Container.build(db_path)
    if demo:
        seed_demo(container)
        container.settings.set("onboarded", True)
        if not container.consent_given:
            container.give_consent()

    def main(page: ft.Page) -> None:
        MedRemindApp(page, container).start()

    return main


def run() -> None:
    parser = argparse.ArgumentParser(description="MedRemind — gestor de medicações")
    parser.add_argument("--web", action="store_true", help="abrir no navegador")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8550)))
    parser.add_argument("--demo", action="store_true", help="carregar dados de demonstração")
    parser.add_argument("--db", help="caminho do banco SQLite (padrão: ~/.medremind/medremind.db)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    main = build_main(args.demo, args.db)
    if args.web:
        ft.run(main, view=ft.AppView.WEB_BROWSER, port=args.port, assets_dir=ASSETS,
               web_renderer=ft.WebRenderer.CANVAS_KIT, no_cdn=True)
    else:
        ft.run(main, assets_dir=ASSETS)


if __name__ == "__main__":
    run()
