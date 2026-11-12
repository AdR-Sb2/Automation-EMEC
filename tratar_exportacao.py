import os
import re
import csv
import io
import shutil
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

AMARELO = PatternFill("solid", fgColor="FFF4CC")
CABECALHO_FILL = PatternFill("solid", fgColor="0572CE")
CABECALHO_FONT = Font(bold=True, color="FFFFFF")
BORDA = Border(bottom=Side(style="thin", color="DFE5EE"))

RE_DATA_BR = re.compile(r"^(\d{2})/(\d{2})/(\d{2}|\d{4})(?: (\d{2}):(\d{2})(?::(\d{2}))?)?$")
RE_DATA_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$")


def ler_texto(caminho):
    raw = open(caminho, "rb").read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("Não foi possível decodificar o arquivo.")


def eh_xlsx(caminho):
    with open(caminho, "rb") as f:
        return f.read(4) == b"PK\x03\x04"


def eh_wrapper_oracle(texto):
    primeira = texto.lstrip("\ufeff").split("\n", 1)[0].strip()
    return primeira.startswith('"') and '""' in primeira


def campos_oracle(texto):
    """Export do Oracle: cada registro vem entre aspas e com aspas duplicadas dentro."""
    partes = re.split(r'"\r?\n"', texto.lstrip("\ufeff"))
    registros = []
    for p in partes:
        r = p.strip()
        if not r:
            continue
        if r.startswith('"'):
            r = r[1:]
        if r.endswith('"'):
            r = r[:-1]
        r = r.replace('""', '"')
        registros.append(next(csv.reader(io.StringIO(r))))
    return registros


def campos_csv_padrao(texto):
    amostra = texto[:2000]
    try:
        delim = csv.Sniffer().sniff(amostra, delimiters=",;\t").delimiter
    except csv.Error:
        delim = ","
    return list(csv.reader(io.StringIO(texto), delimiter=delim))


def converter_valor(valor):
    v = (valor or "").strip()
    if not v:
        return None
    m = RE_DATA_BR.match(v)
    if m:
        dia, mes, ano, h, mi, s = m.groups()
        ano = int(ano) + (2000 if len(ano) == 2 else 0)
        try:
            return datetime(ano, int(mes), int(dia), int(h or 0), int(mi or 0), int(s or 0))
        except ValueError:
            return v
    m = RE_DATA_ISO.match(v)
    if m:
        try:
            return datetime(*[int(x) for x in m.groups()])
        except ValueError:
            return v
    return v


def formato_data(valor):
    if isinstance(valor, datetime):
        return "dd/mm/yyyy hh:mm" if (valor.hour or valor.minute or valor.second) else "dd/mm/yyyy"
    return None


def tratar_exportacao(caminho):
    """Recebe o arquivo baixado e devolve o caminho do arquivo final (.xlsx).
    - Se já for XLSX: não mexe.
    - Se for CSV (inclusive o formato do Oracle): converte para XLSX formatado.
    """
    if eh_xlsx(caminho):
        return caminho

    texto = ler_texto(caminho)
    linhas = campos_oracle(texto) if eh_wrapper_oracle(texto) else campos_csv_padrao(texto)
    if not linhas:
        raise ValueError("Arquivo sem dados.")

    cabecalho = [c.strip() for c in linhas[0]]
    corpo = linhas[1:]
    n_cols = len(cabecalho)

    base, _ = os.path.splitext(caminho)
    destino = base + ".xlsx"
    pasta_bruto = os.path.join(os.path.dirname(caminho), "bruto")
    os.makedirs(pasta_bruto, exist_ok=True)
    shutil.move(caminho, os.path.join(pasta_bruto, os.path.basename(caminho)))

    wb = Workbook()
    ws = wb.active
    ws.title = "Atividades"

    titulos = cabecalho + ["Revisar"]
    ws.append(titulos)
    for c in range(1, len(titulos) + 1):
        cel = ws.cell(row=1, column=c)
        cel.font = CABECALHO_FONT
        cel.fill = CABECALHO_FILL
        cel.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 32

    alertas = 0
    for linha in corpo:
        if not any((x or "").strip() for x in linha):
            continue
        valores = [converter_valor(x) for x in linha[:n_cols]]
        valores += [None] * (n_cols - len(valores))
        incompleto = len(linha) != n_cols
        if incompleto:
            alertas += 1
        valores.append("Revisar: colunas faltando" if incompleto else None)
        ws.append(valores)

        r = ws.max_row
        for c in range(1, len(titulos) + 1):
            cel = ws.cell(row=r, column=c)
            cel.border = BORDA
            fmt = formato_data(cel.value)
            if fmt:
                cel.number_format = fmt
            if incompleto:
                cel.fill = AMARELO

    # Larguras de coluna pelo conteúdo (com limite)
    for c in range(1, len(titulos) + 1):
        letra = get_column_letter(c)
        maior = len(str(titulos[c - 1]))
        for r in range(2, min(ws.max_row, 200) + 1):
            v = ws.cell(row=r, column=c).value
            if v is not None:
                maior = max(maior, len(v.strftime("%d/%m/%Y %H:%M") if isinstance(v, datetime) else str(v)))
        ws.column_dimensions[letra].width = min(max(10, maior + 2), 40)

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    wb.save(destino)
    print(f"Convertido: {destino} ({len(corpo)} registros, {alertas} para revisar)")
    return destino
