"""Ponto de entrada do app MedRemind.

Uso:
    python -m medremind.main            # janela desktop
    python -m medremind.main --web      # no navegador (http://localhost:8550)
    python -m medremind.main --demo     # carrega dados de exemplo (modo offline)
    python -m medremind.main --server https://api.exemplo.com.br   # servidor da conta
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import flet as ft

from .client.session import CloudSession
from .core.container import Container, default_data_dir
from .core.demo import seed_demo
from .ui.app import MedRemindApp

ASSETS = str(Path(__file__).resolve().parent.parent / "assets")


def build_main(demo: bool = False, db_path: str | None = None, server: str | None = None):
    device = Container.build(db_path)
    if demo:
        seed_demo(device)
        device.settings.set("onboarded", True)
        device.settings.set("mode", device.settings.get("mode") or "local")
        if not device.consent_given:
            device.give_consent()
    session = CloudSession(device.data_dir if db_path else default_data_dir(), server_url=server)

    def main(page: ft.Page) -> None:
        # Observação: no modo --web todas as abas do navegador compartilham a mesma sessão
        # (pensado para uso pessoal). Para hospedar para várias pessoas, crie uma sessão por página.
        MedRemindApp(page, device, session).start()

    return main


def run() -> None:
    parser = argparse.ArgumentParser(description="MedRemind — gestor de medicações")
    parser.add_argument("--web", action="store_true", help="abrir no navegador")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8550)))
    parser.add_argument("--demo", action="store_true", help="carregar dados de demonstração")
    parser.add_argument("--db", help="caminho do banco SQLite (padrão: ~/.medremind/medremind.db)")
    parser.add_argument("--server", help="endereço do servidor (padrão: MEDREMIND_SERVER_URL ou http://localhost:8000)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    main = build_main(args.demo, args.db, args.server)
    if args.web:
        ft.run(main, view=ft.AppView.WEB_BROWSER, port=args.port, assets_dir=ASSETS,
               web_renderer=ft.WebRenderer.CANVAS_KIT, no_cdn=True)
    else:
        ft.run(main, assets_dir=ASSETS)


if __name__ == "__main__":
    run()
