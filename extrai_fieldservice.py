import os
import sys
import re
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from tratar_exportacao import tratar_exportacao

URL = "https://aegeappp.fs.ocs.oraclecloud.com/"
AMBIENTE = "aegeappp"
USUARIO = os.environ["OFSC_USUARIO"]
SENHA = os.environ["OFSC_SENHA"]
EQUIPE = os.environ.get("EQUIPE") or "MANUTENÇÃO - BAIXADA 2"
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

    # Identificação do ambiente, quando solicitada
    ambiente = page.get_by_label(
        re.compile("Nome do ambiente", re.I)
    )

    if ambiente.count() and ambiente.first.is_visible():
        ambiente.first.fill(AMBIENTE)
        page.get_by_role(
            "button",
            name=re.compile("continuar|avançar|próximo|next", re.I)
        ).first.click()

    # Aguarda a tela de autenticação
    page.locator(
        "#username, input[type='password']"
    ).first.wait_for(state="visible", timeout=30000)

    usuario = page.locator("#username")
    senha = page.locator("input[type='password']:visible").first

    # Identifica os dois formatos de login
    if usuario.count() and usuario.first.is_visible():
        log.info("Tela de usuário e senha identificada.")
        usuario.first.fill(USUARIO)
    else:
        log.info("Tela somente de senha identificada.")

    senha.fill(SENHA)

    botao = page.get_by_role(
        "button",
        name=re.compile(r"conectar|entrar|login|sign in", re.I)
    ).first

    botao.wait_for(state="visible", timeout=15000)
    botao.click()

    log.info("Credenciais enviadas.")

    def aguardar_resposta(tempo=30):
        for _ in range(tempo):
            page.wait_for_timeout(1000)

            texto = page.locator("body").inner_text().lower()

            # Confirmação de entrada no sistema
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
                return "sucesso"

            # Mensagem específica de limite de sessões
            if (
                "número máximo de sessões excedido" in texto
                or "maximum number of sessions exceeded" in texto
            ):
                return "limite"

            # Credenciais inválidas
            if any(msg in texto for msg in [
                "senha incorreta",
                "usuário ou senha inválidos",
                "invalid username or password",
                "incorrect password"
            ]):
                return "senha"

            # Autenticação adicional
            if any(msg in texto for msg in [
                "código de verificação",
                "verification code",
                "two-factor authentication",
                "multi-factor authentication",
                "autenticação multifator"
            ]):
                return "mfa"

        return "timeout"

    resultado = aguardar_resposta()

    # Trata o limite de sessões com autorização do usuário
    if resultado == "limite":
        log.warning("Limite de sessões detectado.")
        log.warning("Autorização para encerrar a sessão mais antiga concedida.")

        texto_opcao = re.compile(
            r"Excluir a sessão de usuário e login mais antigos",
            re.I
        )

        # Localiza a opção específica, sem marcar outras caixas
        rotulo = page.locator("label").filter(
            has_text=texto_opcao
        ).first

        if rotulo.count() and rotulo.is_visible():
            rotulo.click()
        else:
            opcao = page.get_by_text(
                texto_opcao,
                exact=False
            ).first

            if not opcao.count() or not opcao.is_visible():
                page.screenshot(
                    path=os.path.join(PASTA, "logs", "limite_sessoes.png"),
                    full_page=True
                )
                raise RuntimeError(
                    "Limite de sessões detectado, mas não encontrei "
                    "a opção de exclusão da sessão mais antiga."
                )

            opcao.click()

        log.info("Opção de exclusão da sessão mais antiga selecionada.")

        # Preenche novamente a senha
        senha = page.locator(
            "input[type='password']:visible"
        ).first

        senha.wait_for(state="visible", timeout=10000)
        senha.fill(SENHA)

        botao = page.get_by_role(
            "button",
            name=re.compile(r"conectar|entrar|login|sign in", re.I)
        ).first

        botao.wait_for(state="visible", timeout=10000)

        # Aguarda o botão ficar habilitado
        page.wait_for_function(
            """() => {
                const buttons = [...document.querySelectorAll('button')];
                const button = buttons.find(b =>
                    /conectar|entrar|login|sign in/i.test(b.innerText)
                );
                return button && !button.disabled;
            }""",
            timeout=15000
        )

        log.info("Confirmando login com exclusão da sessão antiga.")
        botao.click()

        resultado = aguardar_resposta(45)

    # Resultado final
    if resultado == "sucesso":
        log.info("LOGIN CONFIRMADO COM SUCESSO.")
        log.info("Página atual: %s", page.url)
        return

    caminho = os.path.join(
        PASTA, "logs", "pos_login.png"
    )
    page.screenshot(path=caminho, full_page=True)

    texto = page.locator("body").inner_text()[:3000]

    log.error("Falha na autenticação: %s", resultado)
    log.error("URL: %s", page.url)
    log.error("Conteúdo da tela: %s", texto)

    mensagens = {
        "limite": "O limite de sessões continua ativo após a tentativa autorizada.",
        "senha": "O Oracle recusou as credenciais.",
        "mfa": "O Oracle solicitou autenticação adicional.",
        "timeout": "Tempo esgotado aguardando confirmação do login."
    }

    raise RuntimeError(mensagens.get(
        resultado,
        "Não foi possível concluir a autenticação."
    ))




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
    # Até 400 cliques: cobre intervalos de vários meses
    for _ in range(400):
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
