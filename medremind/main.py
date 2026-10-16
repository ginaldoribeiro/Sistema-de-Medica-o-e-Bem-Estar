"""Ponto de entrada do app MedRemind.

Uso:
    python -m medremind.main            # janela desktop
    python -m medremind.main --web      # no navegador (http://localhost:8550)
    python -m medremind.main --demo     # carrega dados de exemplo (modo offline)
    python -m medremind.main --server https://api.exemplo.com.br   # servidor da conta
    python -m medremind.main --web --multiuser   # hospedar para várias pessoas (uma sessão por aba)
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import tempfile
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
        # Uso pessoal: todas as janelas compartilham a sessão. Para hospedar, use --multiuser.
        MedRemindApp(page, device, session).start()

    return main


def build_multiuser_main(server: str | None = None, base_dir: str | None = None):
    """Hospedagem web para várias pessoas: cada aba tem a própria sessão, sempre com conta.

    * Nada é compartilhado entre abas/pessoas: cada página ganha uma pasta temporária
      própria (cache do paciente e tokens), apagada quando a aba fecha.
    * Não existe modo "sem conta" — dados de saúde não ficam no disco do servidor web.
    * Ao recarregar a página é preciso entrar de novo (sessão curta, mais segura em PC compartilhado).
    """
    root = Path(base_dir or tempfile.gettempdir()) / "medremind-web"
    root.mkdir(parents=True, exist_ok=True)

    def main(page: ft.Page) -> None:
        folder = Path(tempfile.mkdtemp(prefix="sessao-", dir=root))
        device = Container.build(folder / "aparelho.db")
        device.settings.set("onboarded", True)
        device.settings.set("multiuser", True)
        if not device.consent_given:
            device.give_consent()  # o aceite (LGPD) acontece no cadastro da conta
        session = CloudSession(folder, server_url=server)
        app = MedRemindApp(page, device, session, multiuser=True)

        def cleanup(*_):
            app.shutdown()
            session.logout(wipe_cache=True) if session.logged_in else None
            device.db.close()
            shutil.rmtree(folder, ignore_errors=True)

        page.on_disconnect = cleanup
        page.on_close = cleanup
        app.start()

    return main


def run() -> None:
    parser = argparse.ArgumentParser(description="MedRemind — gestor de medicações")
    parser.add_argument("--web", action="store_true", help="abrir no navegador")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8550)))
    parser.add_argument("--demo", action="store_true", help="carregar dados de demonstração")
    parser.add_argument("--db", help="caminho do banco SQLite (padrão: ~/.medremind/medremind.db)")
    parser.add_argument("--server", help="endereço do servidor (padrão: MEDREMIND_SERVER_URL ou http://localhost:8000)")
    parser.add_argument("--multiuser", action="store_true",
                        help="modo web para várias pessoas: uma sessão isolada por aba, sempre com conta")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.multiuser:
        if not args.web:
            parser.error("--multiuser só faz sentido com --web")
        main = build_multiuser_main(args.server)
    else:
        main = build_main(args.demo, args.db, args.server)
    if args.web:
        ft.run(main, view=ft.AppView.WEB_BROWSER, port=args.port, assets_dir=ASSETS,
               web_renderer=ft.WebRenderer.CANVAS_KIT, no_cdn=True)
    else:
        ft.run(main, assets_dir=ASSETS)


if __name__ == "__main__":
    run()
