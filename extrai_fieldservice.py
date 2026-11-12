import os
import sys
import re
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

URL = "https://aegeappp.fs.ocs.oraclecloud.com/"
AMBIENTE = "aegeappp"
USUARIO = os.environ["OFSC_USUARIO"]
SENHA = os.environ["OFSC_SENHA"]
EQUIPE = "MANUTENÇÃO - BAIXADA 2"
PASTA = os.environ.get("PASTA_SAIDA", "saida")
DATAS = os.environ.get("DATAS", "")
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


def datas_alvo():
    """Sem DATAS: dia anterior. Com DATAS: lista ou intervalo (AAAA-MM-DD, separados por vírgula ou ':')."""
    entrada = DATAS.strip()
    if not entrada:
        return [datetime.now(TZ).date() - timedelta(days=1)]

    datas = set()
    for item in entrada.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            ini_txt, fim_txt = item.split(":")
            ini = datetime.strptime(ini_txt.strip(), "%Y-%m-%d").date()
            fim = datetime.strptime(fim_txt.strip(), "%Y-%m-%d").date()
            d = ini
            while d <= fim:
                datas.add(d)
                d += timedelta(days=1)
        else:
            datas.add(datetime.strptime(item, "%Y-%m-%d").date())
    return sorted(datas)


def data_exibida(texto):
    """Converte 'Quinta-feira, Novembro 12º, 2026' em date."""
    m = re.search(r"([A-Za-zçÇãÃ]+)\s+(\d{1,2})º?,\s*(\d{4})", texto)
    if not m:
        return None
    mes = MESES.get(m.group(1).lower())
    return datetime(int(m.group(3)), mes, int(m.group(2))).date() if mes else None





def login(page):
    log.info("Acessando Oracle Field Service...")

    page.goto(URL, wait_until="domcontentloaded", timeout=60000)

    # Identificação opcional do ambiente
    ambiente = page.get_by_label(
        re.compile("Nome do ambiente", re.I)
    )

    if ambiente.count() and ambiente.first.is_visible():
        log.info("Informando ambiente Oracle...")
        ambiente.first.fill(AMBIENTE)

        page.get_by_role(
            "button",
            name=re.compile("continuar|avançar|próximo|next", re.I)
        ).first.click()

    # Aguarda a apresentação de algum campo de autenticação
    page.locator(
        "#username, input[type='password']"
    ).first.wait_for(state="visible", timeout=30000)

    campo_usuario = page.locator("#username")
    campo_senha = page.locator("input[type='password']:visible").first

    # Detecta o formato da tela
    if campo_usuario.count() and campo_usuario.first.is_visible():
        log.info("Tela identificada: usuário e senha.")
        campo_usuario.first.fill(USUARIO)

    else:
        log.info("Tela identificada: somente senha.")
        log.info("Mantendo o fluxo de identificação apresentado pelo Oracle.")

    # Preenche a senha
    campo_senha.fill(SENHA)

    # Localiza o botão de entrada
    botao = page.get_by_role(
        "button",
        name=re.compile(r"conectar|entrar|login|sign in", re.I)
    ).first

    botao.wait_for(state="visible", timeout=15000)
    botao.click()

    log.info("Credenciais enviadas. Monitorando autenticação...")

    autenticado = False

    for tentativa in range(45):
        page.wait_for_timeout(1000)

        texto = page.locator("body").inner_text().lower()

        # Identifica limite de sessões
        erros_sessao = [
            "número máximo de sessões excedido",
            "maximum number of sessions exceeded",
            "maximum number of sessions",
            "session limit exceeded"
        ]

        if any(erro in texto for erro in erros_sessao):
            raise RuntimeError(
                "LIMITE DE SESSÕES DO ORACLE. "
                "Verifique as sessões ativas com o administrador."
            )

        # Identifica credenciais recusadas
        erros_login = [
            "senha incorreta",
            "usuário ou senha inválidos",
            "invalid username or password",
            "incorrect password"
        ]

        if any(erro in texto for erro in erros_login):
            raise RuntimeError(
                "CREDENCIAIS RECUSADAS PELO ORACLE."
            )

        # Identifica MFA
        erros_mfa = [
            "código de verificação",
            "verification code",
            "two-factor authentication",
            "multi-factor authentication",
            "autenticação multifator"
        ]

        if any(erro in texto for erro in erros_mfa):
            raise RuntimeError(
                "ORACLE SOLICITOU AUTENTICAÇÃO ADICIONAL (MFA)."
            )

        # Confirmação positiva de entrada no sistema
        console = page.locator(
            "a[title='Console de Alocação']"
        )

        cabecalho = page.locator(
            "[data-ofsc-role='page-description-text']"
        )

        if (
            console.count() and console.first.is_visible()
        ) or (
            cabecalho.count() and cabecalho.first.is_visible()
        ):
            autenticado = True
            break

        # Registra a evolução do carregamento
        if tentativa in [9, 19, 29, 39]:
            log.info(
                "Aguardando autenticação... %d segundos.",
                tentativa + 1
            )

    if not autenticado:
        caminho = os.path.join(
            PASTA, "logs", "pos_login.png"
        )

        page.screenshot(path=caminho, full_page=True)

        texto = page.locator("body").inner_text()[:3000]

        log.error("Não foi possível confirmar a autenticação.")
        log.error("URL: %s", page.url)
        log.error("Conteúdo da página: %s", texto)

        raise RuntimeError(
            "Login não confirmado após 45 segundos. "
            "Verifique os arquivos de diagnóstico."
        )

    log.info("LOGIN CONFIRMADO COM SUCESSO.")
    log.info("Página atual: %s", page.url)



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
    for _ in range(60):
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
    datas = datas_alvo()
    log.info("Datas a extrair: %s", ", ".join(d.isoformat() for d in datas))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not MODO_EXPLORAR)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        try:
            login(page)
            abrir_equipe(page)
            if MODO_EXPLORAR:
                explorar(page)
                return
            for dia in datas:
                destino = os.path.join(PASTA, f"atividades_{dia.isoformat()}.csv")
                ir_para_dia(page, dia)
                exportar(page, destino)
                log.info("Exportado: %s", destino)
            log.info("Concluído: %d dia(s) exportado(s).", len(datas))
        except (PWTimeout, RuntimeError) as e:
            page.screenshot(path=os.path.join(PASTA, "logs", f"erro_{datetime.now():%Y%m%d_%H%M%S}.png"))
            log.error("Falha na extração: %s", e)
            sys.exit(1)
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
