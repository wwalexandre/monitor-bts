# -*- coding: utf-8 -*-
"""
Monitor de ingressos Ticketmaster para rodar no GitHub Actions (nuvem, gratis).

Truque usado: o agendamento do GitHub so dispara de 5 em 5 min (e atrasa),
mas UM job pode rodar ate 6 horas. Entao cada execucao fica em loop por
~5h40, checando a pagina a cada 20-35 s. Quando termina, a proxima
execucao agendada ja esta na fila e assume.

Avisos no celular via ntfy (app gratis):
  - "Monitor ligado": no inicio de cada execucao, dizendo se a pagina carregou OK
  - "INGRESSO LIBEROU": urgente, quando ESGOTADO some
  - "Possivel bloqueio": se a pagina vier estranha varias vezes seguidas
"""

import os
import random
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

URL = os.environ.get(
    "TARGET_URL",
    "https://www.ticketmaster.com.br/event/venda-geral-bts-world-tour-arirang-31-10",
)
NTFY_TOPIC = os.environ["NTFY_TOPIC"]
PALAVRA_ESGOTADO = os.environ.get("PALAVRA_ESGOTADO", "ESGOTADO").upper()
PALAVRA_CONFIRMA = os.environ.get("PALAVRA_CONFIRMA", "BTS").upper()
MAX_MINUTOS = float(os.environ.get("MAX_MINUTOS", "340"))
INTERVALO_MIN = 20
INTERVALO_MAX = 35
FALHAS_PARA_AVISO = 5

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S', time.gmtime(time.time() - 3 * 3600))}] {msg}", flush=True)


def push(titulo, mensagem, prioridade="urgent", tags="rotating_light"):
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=mensagem.encode("utf-8"),
            headers={"Title": titulo, "Priority": prioridade, "Tags": tags, "Click": URL},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=15)
        log(f"push enviado: {titulo}")
    except Exception as e:
        log(f"falha no push: {e}")


def checar(page):
    """Retorna 'esgotado', 'liberou' ou 'estranha' + trecho do texto."""
    try:
        page.goto(URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4000)
        texto = page.inner_text("body", timeout=15000).upper()
    except Exception as e:
        return "estranha", f"erro: {e}"[:200]

    trecho = " ".join(texto.split())[:200]
    if PALAVRA_CONFIRMA not in texto:
        return "estranha", trecho
    if PALAVRA_ESGOTADO in texto:
        return "esgotado", trecho
    return "liberou", trecho


def main():
    inicio = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, locale="pt-BR", viewport={"width": 1366, "height": 768})
        page = ctx.new_page()

        # Primeira checagem: manda status pro celular pra voce saber se a nuvem consegue ler a pagina
        status, trecho = checar(page)
        log(f"checagem inicial: {status} | {trecho}")
        if status == "estranha":
            push("Monitor nuvem: pagina bloqueada?",
                 f"A Ticketmaster nao entregou a pagina normal pro GitHub. Trecho: {trecho}",
                 prioridade="high", tags="warning")
        elif status == "esgotado":
            push("Monitor nuvem ligado", "Pagina lida OK, ainda ESGOTADO. Vigiando.",
                 prioridade="low", tags="white_check_mark")

        falhas = 0 if status != "estranha" else 1
        aviso_bloqueio = status == "estranha"
        ciclo = 1

        while True:
            if status == "liberou":
                log("*** ESGOTADO SUMIU! ***")
                for i in range(3):   # 3 pushes seguidos pra nao passar batido
                    push("INGRESSO BTS LIBEROU!", "ESGOTADO saiu da pagina. Abre o app da Ticketmaster AGORA!")
                    time.sleep(20)
                break

            if (time.time() - inicio) / 60 > MAX_MINUTOS:
                log("tempo maximo da execucao atingido, a proxima assume")
                break

            time.sleep(random.uniform(INTERVALO_MIN, INTERVALO_MAX))
            ciclo += 1
            status, trecho = checar(page)
            log(f"#{ciclo} {status}")

            if status == "estranha":
                falhas += 1
                log(f"   trecho: {trecho}")
                if falhas >= FALHAS_PARA_AVISO and not aviso_bloqueio:
                    push("Monitor nuvem: possivel bloqueio",
                         f"{falhas} leituras estranhas seguidas. Trecho: {trecho}",
                         prioridade="high", tags="warning")
                    aviso_bloqueio = True
            else:
                if aviso_bloqueio and status == "esgotado":
                    push("Monitor nuvem voltou", "Pagina voltou a carregar normal.",
                         prioridade="low", tags="white_check_mark")
                falhas = 0
                aviso_bloqueio = False

        browser.close()


if __name__ == "__main__":
    sys.exit(main())
