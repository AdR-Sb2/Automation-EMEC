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

    # Espera a navegação pós-login
    page.wait_for_timeout(5000)

    # Se o campo de senha ainda estiver visível, o login não foi concluído
    if page.locator("input[type='password']:visible").count() > 0:
        page.screenshot(path=os.path.join(PASTA, "logs", "pos_login.png"), full_page=True)
        raise RuntimeError("Continuou na tela de login: verifique usuário/senha ou se a Oracle pediu código (MFA).")

    log.info("Login concluído. Página atual: %s", page.url)
        
def selecionar_equipe(page):
    cabecalho = page.locator("[data-ofsc-role='page-description-text']").first
    cabecalho.wait_for(state="visible", timeout=30_000)

    if EQUIPE in cabecalho.inner_text():
        return  # já está na equipe certa

    # Abre o seletor de equipe clicando no nome do cabeçalho
    cabecalho.click()
    busca = page.locator("input[placeholder='Nome ou ID']:visible").first
    busca.wait_for(state="visible", timeout=15_000)
    busca.fill(EQUIPE)
    page.wait_for_timeout(1000)

    # Clica na equipe na lista
    page.locator("button.edt-label:visible", has_text=EQUIPE).first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    if EQUIPE not in page.locator("[data-ofsc-role='page-description-text']").first.inner_text():
        raise RuntimeError("Não consegui selecionar a equipe " + EQUIPE)


def abrir_equipe(page):
    link = page.locator("a[title='Console de Alocação']").first
    if not link.is_visible():
        page.get_by_role("button", name="Menu", exact=True).click()
        page.wait_for_timeout(1000)
    link.wait_for(state="visible", timeout=30_000)
    link.click()
    page.wait_for_load_state("networkidle")
    selecionar_equipe(page)


def ir_para_dia(page, alvo):
    for _ in range(10):
        atual = data_exibida(page.locator("body").inner_text())
        if atual is None:
            raise RuntimeError("Não consegui ler a data exibida no console.")
        if atual == alvo:
            return
        nome = "Anterior" if atual > alvo else "Próximo"
        page.get_by_role("button", name=nome, exact=True).click()
        page.wait_for_load_state("networkidle")
    raise RuntimeError(f"Não consegui chegar em {alvo}.")


def exportar(page, destino):
    page.get_by_role("button", name="Ações", exact=True).click()
    page.wait_for_timeout(500)
    with page.expect_download(timeout=120_000) as info:
        page.locator("[data-bar-id='dc__top_panel__configured_action_action_link__export_queue']").click()
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
