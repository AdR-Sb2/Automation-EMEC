#!/usr/bin/env python3
"""Gera um PDF diário com ordens de manutenção concluídas."""
import argparse
import os
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime

from openpyxl import load_workbook
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    KeepTogether, Flowable
)

AZUL = colors.HexColor("#073763")
AZUL_CLARO = colors.HexColor("#DCEAF7")
CINZA = colors.HexColor("#5B6573")
VERDE = colors.HexColor("#16835D")
FUNDO = colors.HexColor("#F3F6FA")


def normalizar(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    return "".join(c for c in texto if not unicodedata.combining(c)).strip().casefold()


def data_do_arquivo(caminho):
    nome = os.path.basename(caminho)
    m = re.search(r"(\\d{4}-\\d{2}-\\d{2})", nome)
    if m:
        return datetime.strptime(m.group(1), "%Y-%m-%d").strftime("%d/%m/%Y")
    return datetime.now().strftime("%d/%m/%Y")


def analisar(arquivo):
    wb = load_workbook(arquivo, read_only=True, data_only=True)
    ws = wb["Atividades"] if "Atividades" in wb.sheetnames else wb.active
    cabecalhos = [str(c or "").strip() for c in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
    obrigatorias = ["Ordem de Manutenção", "Status da Atividade", "Tipo de Atividade"]
    faltantes = [c for c in obrigatorias if c not in cabecalhos]
    if faltantes:
        raise ValueError("Colunas ausentes na planilha: " + ", ".join(faltantes))

    indices = {nome: cabecalhos.index(nome) for nome in obrigatorias}
    por_ordem = defaultdict(Counter)
    for linha in ws.iter_rows(min_row=2, values_only=True):
        ordem = str(linha[indices["Ordem de Manutenção"]] or "").strip()
        status = normalizar(linha[indices["Status da Atividade"]])
        tipo = str(linha[indices["Tipo de Atividade"]] or "Não informado").strip()
        if not ordem or not ordem.startswith(("000900", "000800")):
            continue
        if status != "concluido":
            continue
        por_ordem[ordem][tipo] += 1
    wb.close()

    # Cada ordem é contabilizada uma única vez; em caso de duplicidade,
    # fica associada ao tipo de atividade mais frequente entre os registros concluídos.
    tipos_por_ordem = {ordem: contagem.most_common(1)[0][0] for ordem, contagem in por_ordem.items()}
    resumo = Counter(tipos_por_ordem.values())
    return len(tipos_por_ordem), resumo


class GraficoBarras(Flowable):
    def __init__(self, dados, largura=170*mm, altura=None):
        self.dados = dados
        self.width = largura
        self.height = max(35*mm, len(dados) * 13*mm + 8*mm) if altura is None else altura

    def wrap(self, availWidth, availHeight):
        self.width = min(self.width, availWidth)
        return self.width, self.height

    def draw(self):
        c = self.canv
        if not self.dados:
            c.setFont("Helvetica", 9)
            c.setFillColor(CINZA)
            c.drawString(0, self.height - 12, "Nenhuma ordem concluída encontrada no período.")
            return
        max_valor = max(v for _, v in self.dados) or 1
        margem_rotulo = min(88*mm, self.width * 0.48)
        largura_barra = self.width - margem_rotulo - 18*mm
        y = self.height - 9*mm
        for nome, valor in self.dados:
            c.setFont("Helvetica", 7.5)
            c.setFillColor(AZUL)
            texto = nome if len(nome) <= 48 else nome[:45] + "..."
            c.drawString(0, y + 2, texto)
            c.setFillColor(AZUL_CLARO)
            c.roundRect(margem_rotulo, y - 1, largura_barra, 6*mm, 2, fill=1, stroke=0)
            c.setFillColor(AZUL)
            w = largura_barra * valor / max_valor
            c.roundRect(margem_rotulo, y - 1, max(w, 1), 6*mm, 2, fill=1, stroke=0)
            c.setFillColor(CINZA)
            c.setFont("Helvetica-Bold", 8)
            c.drawRightString(self.width, y + 1, str(valor))
            y -= 13*mm


def gerar(entrada, saida):
    total, resumo = analisar(entrada)
    data_ref = data_do_arquivo(entrada)
    ordenado = sorted(resumo.items(), key=lambda item: (-item[1], item[0].casefold()))

    doc = SimpleDocTemplate(
        saida, pagesize=A4,
        rightMargin=18*mm, leftMargin=18*mm,
        topMargin=17*mm, bottomMargin=17*mm,
        title="Relatório diário de manutenção",
        author="Automação Eletromecânica"
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TituloRel", parent=styles["Title"], fontName="Helvetica-Bold",
                              fontSize=19, leading=23, textColor=AZUL, alignment=TA_LEFT, spaceAfter=3*mm))
    styles.add(ParagraphStyle(name="SubRel", parent=styles["Normal"], fontSize=9, textColor=CINZA, spaceAfter=5*mm))
    styles.add(ParagraphStyle(name="SecaoRel", parent=styles["Heading2"], fontName="Helvetica-Bold",
                              fontSize=11, leading=14, textColor=AZUL, spaceBefore=5*mm, spaceAfter=3*mm))
    styles.add(ParagraphStyle(name="PequenoRel", parent=styles["Normal"], fontSize=8, leading=11, textColor=CINZA))
    story = [
        Paragraph("RELATÓRIO DIÁRIO", styles["TituloRel"]),
        Paragraph("Manutenção | Eletromecânica — Baixada 2", styles["SubRel"]),
        HRFlowable(width="100%", thickness=1.2, color=AZUL, spaceAfter=7*mm),
        Paragraph("Data de referência: <b>%s</b>" % data_ref, styles["Normal"]),
        Spacer(1, 5*mm),
    ]

    kpi = Table([[Paragraph("<font size='8' color='#5B6573'>ORDENS CONCLUÍDAS</font><br/><font size='27' color='#16835D'><b>%d</b></font>" % total, styles["Normal"]),
                  Paragraph("<font size='8' color='#5B6573'>TIPOS DE ATIVIDADE</font><br/><font size='27' color='#073763'><b>%d</b></font>" % len(resumo), styles["Normal"])]],
                colWidths=[82*mm, 82*mm], rowHeights=[25*mm])
    kpi.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), FUNDO), ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#D9E1EA")),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("LEFTPADDING", (0,0), (-1,-1), 6*mm),
        ("RIGHTPADDING", (0,0), (-1,-1), 4*mm), ("TOPPADDING", (0,0), (-1,-1), 2*mm),
    ]))
    story += [kpi, Paragraph("Ordens concluídas por tipo de atividade", styles["SecaoRel"]),
              GraficoBarras(ordenado), Paragraph("Detalhamento", styles["SecaoRel"])]

    tabela = [["Tipo de atividade", "Ordens", "Participação"]]
    for tipo, quantidade in ordenado:
        percentual = (quantidade / total * 100) if total else 0
        tabela.append([Paragraph(tipo.replace("&", "&amp;"), styles["PequenoRel"]), str(quantidade), f"{percentual:.1f}%".replace(".", ",")])
    if not ordenado:
        tabela.append(["Nenhuma ordem concluída", "0", "0,0%"])
    t = Table(tabela, colWidths=[112*mm, 25*mm, 27*mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), AZUL), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,0), 8),
        ("ALIGN", (1,0), (-1,-1), "CENTER"), ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, FUNDO]),
        ("GRID", (0,0), (-1,-1), 0.35, colors.HexColor("#D9E1EA")),
        ("LEFTPADDING", (0,0), (-1,-1), 7), ("RIGHTPADDING", (0,0), (-1,-1), 7),
        ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    story += [t, Spacer(1, 6*mm),
              Paragraph("Critério: este relatório apresenta exclusivamente ordens concluídas. Cada ordem é contabilizada uma única vez.", styles["PequenoRel"])]

    def rodape(canvas, documento):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D9E1EA"))
        canvas.line(18*mm, 13*mm, A4[0]-18*mm, 13*mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(CINZA)
        canvas.drawString(18*mm, 8*mm, "Relatório automático | Eletromecânica — Baixada 2")
        canvas.drawRightString(A4[0]-18*mm, 8*mm, f"Página {documento.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=rodape, onLaterPages=rodape)
    print(f"Relatório gerado: {saida} | {total} ordens concluídas")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--entrada", required=True, help="Planilha XLSX de atividades")
    parser.add_argument("--saida", help="Caminho do PDF de saída")
    args = parser.parse_args()
    saida = args.saida or os.path.splitext(args.entrada)[0] + "_relatorio.pdf"
    gerar(args.entrada, saida)
