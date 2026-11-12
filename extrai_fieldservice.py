import os
import sys
import re
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

URL = "https://aegeappp.fs.ocs.oraclecloud.com/"
USUARIO = os.environ["OFSC_USUARIO"]
SENHA = os.environ["OFSC_SENHA"]
EQUIPE = "MANUTENÇÃO - BAIXADA 2"
PASTA = os.environ.get("PASTA_SAIDA", "saida")
TZ = ZoneInfo("America/Sao_Paulo")
MODO_EXPLORAR = "--explorar" in sys.argv

os.makedirs(PASTA, exist_ok=True)
os.makedirs(os.path.join(PASTA, "logs"), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(PASTA, "logs", "execucao.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("fieldservice")

MESES = {"janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4, "maio": 5, "junho": 6,
         "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}


def data_exibida(texto):
    """Converte 'Quinta-feira, Novembro 12º, 2026' em date."""
    m = re.search(r"([A-Za-zçÇãÃ]+)\s+(\d{1,2})º?,\s*(\d{4})", texto)
    if not m:
        return None
    mes = MESES.get(m.group(1).lower())
    return datetime(int(m.group(3)), mes, int(m.group(2))).date() if mes else None


def login(page):
    page.goto(URL, wait_until="networkidle")

    # Etapa opcional: campo "Nome do ambiente", caso apareça antes do login
    ambiente = page.get_by_label(re.compile("Nome do ambiente", re.I))
    if ambiente.count() and ambiente.first.is_visible():
        ambiente.first.fill(AMBIENTE)
        page.get_by_role("button", name=re.compile("continuar|avançar|próximo|next", re.I)).first.click()
        page.wait_for_load_state("networkidle")

    # Usuário: campo id="username" (os outros com o mesmo rótulo são SSO ou checkbox)
    campo_usuario = page.locator("#username")
    campo_usuario.wait_for(state="visible", timeout=30_000)
    campo_usuario.fill(USUARIO)

    # Senha: primeiro campo de senha visível
    page.locator("input[type='password']:visible").first.fill(SENHA)

    # O botão só fica ativo depois de preencher os dois campos
    page.get_by_role("button", name="Conectar").click()
    page.wait_for_load_state("networkidle")

    if page.locator("text=/código|verificação|token|MFA/i").count() > 0:
        raise RuntimeError("Login pede verificação em duas etapas. Peça à TI uma conta de serviço sem MFA.")
        
def abrir_equipe(page):
    page.get_by_text("Console de Alocação").first.click()
    page.wait_for_load_state("networkidle")
    page.get_by_text(EQUIPE, exact=False).first.click()
    page.wait_for_load_state("networkidle")


def ir_para_dia(page, alvo):
    for _ in range(10):
        atual = data_exibida(page.locator("body").inner_text())
        if atual is None:
            raise RuntimeError("Não consegui ler a data exibida no console.")
        if atual == alvo:
            return
        if atual > alvo:
            page.get_by_role("button", name=re.compile("anterior|previous", re.I)).first.click()
        else:
            page.get_by_role("button", name=re.compile("próximo|next", re.I)).first.click()
        page.wait_for_load_state("networkidle")
    raise RuntimeError(f"Não consegui chegar em {alvo}.")


def exportar(page, destino):
    page.get_by_role("button", name="Ações").click()
    with page.expect_download(timeout=120_000) as info:
        page.get_by_text("Exportar", exact=True).click()
    info.value.save_as(destino)


def explorar(page):
    page.screenshot(path=os.path.join(PASTA, "logs", "tela_inicial.png"), full_page=True)
    botoes = page.locator("button, [role='button'], a").all_inner_texts()
    with open(os.path.join(PASTA, "logs", "botoes.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(t.strip() for t in botoes if t.strip()))
    log.info("Modo explorar: prints e lista de botões salvos em logs/.")


def main():
    ontem = datetime.now(TZ).date() - timedelta(days=1)
    destino = os.path.join(PASTA, f"atividades_{ontem.isoformat()}.csv")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not MODO_EXPLORAR)
        page = browser.new_page(accept_downloads=True)
        try:
            login(page)
            abrir_equipe(page)
            if MODO_EXPLORAR:
                explorar(page)
                return
            ir_para_dia(page, ontem)
            exportar(page, destino)
            log.info("Exportado com sucesso: %s", destino)
        except (PWTimeout, RuntimeError) as e:
            page.screenshot(path=os.path.join(PASTA, "logs", f"erro_{datetime.now():%Y%m%d_%H%M%S}.png"))
            log.error("Falha na extração: %s", e)
            sys.exit(1)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
