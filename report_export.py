import io
import os
import tempfile
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image as RLImage
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from db import get_db
from data_import import get_report_stats
from algorithms import load_signals
from workflow import get_kanban_data


def _register_chinese_font():
    font_paths = [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont("ChineseFont", fp))
                return "ChineseFont"
            except Exception:
                continue
    return "Helvetica"


def _make_time_trend_fig(df, device_name):
    df = df[df["device_name"] == device_name].copy()
    df["report_date"] = pd.to_datetime(df["report_date"])
    monthly = df.groupby(df["report_date"].dt.to_period("M")).size()
    monthly.index = monthly.index.astype(str)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(range(len(monthly)), monthly.values, marker="o", linewidth=2)
    ax.set_xticks(range(0, len(monthly), max(1, len(monthly) // 10)))
    ax.set_xticklabels([monthly.index[i] for i in range(0, len(monthly), max(1, len(monthly) // 10))], rotation=45, fontsize=8)
    ax.set_title(f"{device_name} - Time Trend", fontsize=12)
    ax.set_ylabel("Report Count")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    return fig


def generate_pdf_report(date_range=None):
    font_name = _register_chinese_font()
    stats = get_report_stats()
    signals_df = load_signals()
    kanban = get_kanban_data()

    tmp_dir = tempfile.mkdtemp()
    pdf_path = os.path.join(tmp_dir, "signal_report.pdf")

    doc = SimpleDocTemplate(pdf_path, pagesize=A4)
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle("Title_CN", parent=styles["Title"], fontName=font_name, fontSize=18, leading=24)
    heading_style = ParagraphStyle("Heading_CN", parent=styles["Heading2"], fontName=font_name, fontSize=14, leading=18)
    body_style = ParagraphStyle("Body_CN", parent=styles["Normal"], fontName=font_name, fontSize=10, leading=14)

    elements = []

    elements.append(Paragraph("Medical Device Adverse Event Signal Detection Report", title_style))
    elements.append(Spacer(1, 12))

    date_info = f"Date Range: {stats.get('date_min', 'N/A')} ~ {stats.get('date_max', 'N/A')}"
    elements.append(Paragraph(date_info, body_style))
    elements.append(Spacer(1, 6))

    overview_data = [
        ["Metric", "Value"],
        ["Total Reports", str(stats["total_reports"])],
        ["Device Count", str(stats["total_devices"])],
        ["Event Type Count", str(stats["total_event_types"])],
        ["Strong Signals", str(len(signals_df[signals_df["signal_strength"] == "强信号"])) if not signals_df.empty else "0"],
        ["Medium Signals", str(len(signals_df[signals_df["signal_strength"] == "中等信号"])) if not signals_df.empty else "0"],
        ["Weak Signals", str(len(signals_df[signals_df["signal_strength"] == "弱信号"])) if not signals_df.empty else "0"],
    ]

    tbl = Table(overview_data, colWidths=[80 * mm, 60 * mm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f77b4")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whiteness),
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    elements.append(tbl)
    elements.append(Spacer(1, 12))

    if not signals_df.empty:
        elements.append(Paragraph("Signal Summary (Sorted by Strength)", heading_style))
        elements.append(Spacer(1, 6))

        sig_sorted = signals_df.sort_values("signal_count", ascending=False)
        sig_data = [["Device", "Event Type", "Count", "PRR", "ROR", "IC", "EBGM", "Strength"]]
        for _, row in sig_sorted.head(30).iterrows():
            sig_data.append([
                str(row["device_name"])[:20],
                str(row["event_type"]),
                str(row["report_count"]),
                f"{row['prr_value']:.2f}" if pd.notna(row["prr_value"]) else "N/A",
                f"{row['ror_value']:.2f}" if pd.notna(row["ror_value"]) else "N/A",
                f"{row['ic_value']:.2f}" if pd.notna(row["ic_value"]) else "N/A",
                f"{row['ebgm_value']:.2f}" if pd.notna(row["ebgm_value"]) else "N/A",
                str(row["signal_strength"]),
            ])

        sig_tbl = Table(sig_data, colWidths=[35 * mm, 15 * mm, 12 * mm, 15 * mm, 15 * mm, 15 * mm, 15 * mm, 18 * mm])
        sig_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2ca02c")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whiteness),
            ("FONTNAME", (0, 0), (-1, -1), font_name),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ]))
        elements.append(sig_tbl)
        elements.append(Spacer(1, 12))

        key_signals = sig_sorted[sig_sorted["signal_strength"].isin(["强信号", "中等信号"])].head(5)
        if not key_signals.empty:
            elements.append(PageBreak())
            elements.append(Paragraph("Key Signal Detailed Analysis", heading_style))

            from data_import import load_reports
            all_reports = load_reports()

            for _, row in key_signals.iterrows():
                dev = row["device_name"]
                evt = row["event_type"]
                elements.append(Paragraph(f"Device: {dev} | Event: {evt}", body_style))

                detail_data = [
                    ["Metric", "Value", "CI Lower", "CI Upper", "Signal"],
                    ["PRR", f"{row['prr_value']:.3f}", f"{row['prr_ci_lower']:.3f}", f"{row['prr_ci_upper']:.3f}", str(row['prr_signal'])],
                    ["ROR", f"{row['ror_value']:.3f}", f"{row['ror_ci_lower']:.3f}", f"{row['ror_ci_upper']:.3f}", str(row['ror_signal'])],
                    ["IC/BCPNN", f"{row['ic_value']:.3f}", f"{row['ic025']:.3f}", "-", str(row['bcpnn_signal'])],
                    ["EBGM/MGPS", f"{row['ebgm_value']:.3f}", f"{row['eb05']:.3f}", "-", str(row['mgps_signal'])],
                ]
                d_tbl = Table(detail_data, colWidths=[25 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm])
                d_tbl.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ff7f0e")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whiteness),
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ]))
                elements.append(d_tbl)
                elements.append(Spacer(1, 8))

                try:
                    fig = _make_time_trend_fig(all_reports, dev)
                    img_path = os.path.join(tmp_dir, f"trend_{hash(dev)}.png")
                    fig.savefig(img_path, dpi=100, bbox_inches="tight")
                    plt.close(fig)
                    elements.append(RLImage(img_path, width=160 * mm, height=65 * mm))
                except Exception:
                    pass

                elements.append(Spacer(1, 12))

    confirmed = kanban.get("确认信号", [])
    if confirmed:
        elements.append(PageBreak())
        elements.append(Paragraph("Recommended Actions", heading_style))
        action_data = [["Device", "Event", "Strength", "Action"]]
        for item in confirmed:
            action_data.append([
                str(item.get("device_name", ""))[:20],
                str(item.get("event_type", "")),
                str(item.get("signal_strength", "")),
                str(item.get("action_measure", "待确定")),
            ])
        a_tbl = Table(action_data, colWidths=[40 * mm, 20 * mm, 25 * mm, 50 * mm])
        a_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d62728")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whiteness),
            ("FONTNAME", (0, 0), (-1, -1), font_name),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ]))
        elements.append(a_tbl)

    doc.build(elements)
    return pdf_path
