import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import os
import tempfile
from datetime import datetime

from db import init_db, get_db
from data_import import (
    validate_dataframe, rename_columns, check_duplicates,
    import_data, load_reports, get_report_stats, get_distinct_values,
    COLUMN_DESCRIPTIONS,
)
from algorithms import run_signal_detection, save_signals, load_signals, get_signal_detail, build_contingency_table
from correction import apply_corrections, get_corrected_signal_strength
from time_analysis import compute_monthly_counts, compute_cusum, detect_trend, save_cusum_alerts, load_cusum_alerts
from subgroup import run_all_stratifications
from similar_devices import compare_similar_devices, find_similar_devices
from workflow import (
    init_workflow_for_signals, update_signal_status, set_action_measure,
    get_kanban_data, get_signal_with_workflow,
)
from report_export import generate_pdf_report
from config_manager import (
    get_active_config, get_all_configs, save_new_config,
    reset_to_default, DEFAULT_CONFIG, init_default_config,
)
from alert_manager import generate_alerts, get_recent_alerts, get_all_alerts
from signal_tracker import (
    create_detection_run, save_signal_history, detect_changes,
    get_changes_for_run, get_latest_changes, get_last_detection_run,
)
from review_module import (
    get_kanban_data as get_review_kanban,
    get_all_reviewers, add_reviewer, update_reviewer, delete_reviewer,
    get_report_version, get_all_report_versions, compare_report_versions,
    compare_report_versions_enhanced,
    submit_for_review, make_review_decision,
    get_annotations, add_annotation, add_annotation_reply, set_annotation_status,
    get_annotation_count_by_signal, get_review_statistics, get_review_history,
    get_report_assignments, get_reviewer_by_name,
    get_remaining_time, extend_deadline, force_close,
    get_my_todo_list,
    create_annotation_template, update_annotation_template, delete_annotation_template, get_annotation_templates,
    export_review_comments,
    REVIEWER_ROLES, ANNOTATION_TYPES, ANNOTATION_PRIORITIES, ANNOTATION_STATUSES,
)

st.set_page_config(page_title="医疗器械不良事件信号检测平台", layout="wide", page_icon="🔬")

init_db()
init_default_config()

if "signals_df" not in st.session_state:
    st.session_state.signals_df = load_signals()
if "correction_method" not in st.session_state:
    st.session_state.correction_method = "fdr"
if "detection_page_tab" not in st.session_state:
    st.session_state.detection_page_tab = "检测结果"
if "selected_signal_for_detail" not in st.session_state:
    st.session_state.selected_signal_for_detail = None
if "selected_report_for_detail" not in st.session_state:
    st.session_state.selected_report_for_detail = None
if "review_page_tab" not in st.session_state:
    st.session_state.review_page_tab = "报告审阅看板"
if "current_reviewer" not in st.session_state:
    st.session_state.current_reviewer = None

if st.session_state.selected_report_for_detail is not None:
    default_page = "📝 报告审阅"
elif st.session_state.selected_signal_for_detail is not None:
    default_page = "📊 信号检测"
else:
    default_page = "🏠 数据概览"

page_options = [
    "🏠 数据概览",
    "📥 数据导入",
    "🔍 数据浏览",
    "📊 信号检测",
    "🔥 关联矩阵",
    "📈 时间趋势",
    "👥 亚组分析",
    "🔄 同类对比",
    "📋 信号看板",
    "⚙️ 检测参数配置",
    "📄 报告导出",
    "📝 报告审阅",
    "👤 审阅人管理",
]
default_index = page_options.index(default_page)
page = st.sidebar.selectbox("导航", page_options, index=default_index)

if page != "📊 信号检测" and st.session_state.selected_signal_for_detail is not None:
    st.session_state.selected_signal_for_detail = None
if page != "📝 报告审阅" and st.session_state.selected_report_for_detail is not None:
    st.session_state.selected_report_for_detail = None


def page_overview():
    st.title("🏠 数据概览")
    stats = get_report_stats()
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("报告总数", stats["total_reports"])
    with col2:
        st.metric("涉及器械数", stats["total_devices"])
    with col3:
        st.metric("涉及事件类型数", stats["total_event_types"])
    with col4:
        st.metric("时间范围", f"{stats.get('date_min', 'N/A')} ~ {stats.get('date_max', 'N/A')}")

    if not st.session_state.signals_df.empty:
        sdf = st.session_state.signals_df
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("强信号", len(sdf[sdf["signal_strength"] == "强信号"]))
        with col2:
            st.metric("中等信号", len(sdf[sdf["signal_strength"] == "中等信号"]))
        with col3:
            st.metric("弱信号", len(sdf[sdf["signal_strength"] == "弱信号"]))
        with col4:
            st.metric("无信号", len(sdf[sdf["signal_strength"] == "无信号"]))

    st.divider()
    st.subheader("⚠️ 最新预警（最近7天）")
    recent_alerts = get_recent_alerts(days=7)
    if not recent_alerts:
        st.info("最近7天内没有新的预警记录")
    else:
        alert_df = pd.DataFrame(recent_alerts)
        alert_df_display = alert_df[["created_at", "device_name", "event_type", "signal_strength", "prr_value", "report_count", "signal_id"]].copy()
        alert_df_display.columns = ["预警时间", "器械名称", "事件类型", "信号强度", "PRR值", "报告数量", "信号ID"]
        alert_df_display["预警时间"] = pd.to_datetime(alert_df_display["预警时间"]).dt.strftime("%Y-%m-%d %H:%M")
        alert_df_display["PRR值"] = alert_df_display["PRR值"].apply(lambda x: f"{x:.3f}" if pd.notna(x) else "N/A")

        def format_signal_strength(s):
            if s == "强信号":
                return f"<span style='color:#d62728;font-weight:bold;background-color:#ffe6e6;padding:2px 8px;border-radius:4px;'>🔴 {s}</span>"
            else:
                return f"<span style='color:#ff7f0e;font-weight:bold;background-color:#fff3e6;padding:2px 8px;border-radius:4px;'>🟠 {s}</span>"

        alert_df_display["信号强度"] = alert_df_display["信号强度"].apply(format_signal_strength)

        for idx, row in alert_df_display.iterrows():
            with st.container(border=True):
                col_a, col_b, col_c, col_d = st.columns([3, 2, 1, 1])
                with col_a:
                    st.markdown(f"**{row['器械名称']}** - {row['事件类型']}")
                    st.caption(f"🕐 {row['预警时间']}")
                with col_b:
                    st.markdown(row["信号强度"], unsafe_allow_html=True)
                with col_c:
                    st.metric("PRR", row["PRR值"])
                with col_d:
                    st.metric("报告数", row["报告数量"])
                if pd.notna(row["信号ID"]):
                    if st.button(f"查看详细分析 →", key=f"alert_detail_{idx}", use_container_width=True):
                        st.session_state.selected_signal_for_detail = {
                            "device_name": row["器械名称"],
                            "event_type": row["事件类型"],
                            "signal_id": int(row["信号ID"]),
                        }
                        st.session_state.detection_page_tab = "检测结果"
                        st.rerun()

    st.divider()

    df = load_reports()
    if not df.empty:
        st.subheader("事件类型分布")
        event_dist = df["event_type"].value_counts().reset_index()
        event_dist.columns = ["事件类型", "数量"]
        fig = px.pie(event_dist, values="数量", names="事件类型", hole=0.4)
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("月度报告趋势")
        df["report_date"] = pd.to_datetime(df["report_date"])
        monthly = df.groupby(df["report_date"].dt.to_period("M")).size().reset_index(name="count")
        monthly["month"] = monthly["report_date"].astype(str)
        fig2 = px.line(monthly, x="month", y="count", markers=True)
        fig2.update_layout(xaxis_title="月份", yaxis_title="报告数")
        st.plotly_chart(fig2, use_container_width=True)


def page_import():
    st.title("📥 数据导入")

    with st.expander("📋 字段说明（点击展开）", expanded=False):
        col_desc = [{"字段名称": col, "说明": desc} for col, desc in COLUMN_DESCRIPTIONS.items()]
        st.table(pd.DataFrame(col_desc))
        st.info("💡 **提示**：'器械分类编码'是进行同类器械对比的必需字段。该编码应采用国家医疗器械分类编码标准，系统会自动取编码前4位识别同品类器械。")

    uploaded_file = st.file_uploader("上传不良事件报告数据", type=["csv", "xlsx", "xls"])

    if uploaded_file is not None:
        try:
            if uploaded_file.name.endswith(".csv"):
                df = pd.read_csv(uploaded_file, encoding="utf-8-sig")
            else:
                df = pd.read_excel(uploaded_file)
        except Exception as e:
            st.error(f"文件读取失败: {e}")
            return

        st.subheader("数据预览")
        st.dataframe(df.head(10), use_container_width=True)
        st.info(f"共 {len(df)} 行, {len(df.columns)} 列")

        errors, warnings, validated_df = validate_dataframe(df)

        if errors:
            st.subheader("❌ 校验错误")
            for e in errors:
                st.error(e)

        if warnings:
            st.subheader("⚠️ 校验警告")
            for w in warnings:
                st.warning(w)

        if not errors:
            renamed_df = rename_columns(validated_df)
            internal_dups, db_dups, processed_df, db_dup_mask = check_duplicates(renamed_df)

            if internal_dups > 0:
                st.warning(f"检测到 {internal_dups} 条文件内疑似重复（同注册证号+同报告日期+同事件描述）")
            if db_dups > 0:
                st.warning(f"检测到 {db_dups} 条与数据库已有记录疑似重复")

            skip_db = st.checkbox("跳过数据库中已存在的重复记录", value=True)
            confirm_import = st.button("确认导入", type="primary")

            if confirm_import:
                with st.spinner("正在导入数据..."):
                    dup_count, new_count = import_data(validated_df, skip_db_duplicates=skip_db)
                    st.success(f"导入完成！新增 {new_count} 条记录，跳过重复 {dup_count} 条")
                    st.cache_data.clear()


def page_browse():
    st.title("🔍 数据浏览")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        date_start = st.date_input("开始日期", value=None)
    with col2:
        date_end = st.date_input("结束日期", value=None)
    with col3:
        event_types = get_distinct_values("event_type")
        selected_event = st.selectbox("事件类型", ["全部"] + event_types)
    with col4:
        device_names = get_distinct_values("device_name")
        selected_device = st.selectbox("器械名称", ["全部"] + device_names)

    filters = {}
    if date_start:
        filters["date_start"] = str(date_start)
    if date_end:
        filters["date_end"] = str(date_end)
    if selected_event != "全部":
        filters["event_type"] = selected_event
    if selected_device != "全部":
        filters["device_name"] = selected_device

    df = load_reports(filters if filters else None)
    st.info(f"共 {len(df)} 条记录")
    if not df.empty:
        display_cols = ["device_name", "registration_number", "event_type", "severity",
                        "report_date", "patient_age_group", "patient_gender", "usage_scenario", "batch_number"]
        existing_cols = [c for c in display_cols if c in df.columns]
        st.dataframe(df[existing_cols], use_container_width=True)


def page_detection():
    st.title("📊 信号检测")

    col1, col2 = st.columns([3, 1])
    with col2:
        st.subheader("参数设置")
        correction_method = st.radio("多重比较校正方法", ["fdr", "bonferroni", "none"],
                                      format_func=lambda x: {"fdr": "Benjamini-Hochberg FDR", "bonferroni": "Bonferroni", "none": "不校正"}[x],
                                      index=0)
        st.session_state.correction_method = correction_method

        if st.button("🚀 运行信号检测", type="primary"):
            with st.spinner("正在运行信号检测算法..."):
                df = load_reports()
                if df.empty:
                    st.error("没有数据，请先导入报告数据")
                    return

                active_config = get_active_config()
                config_id = active_config.get("id")

                result_df = run_signal_detection(df, config=active_config)
                if not result_df.empty:
                    result_df = apply_corrections(result_df)
                    save_signals(result_df)
                    st.session_state.signals_df = result_df
                    init_workflow_for_signals()

                    total_reports = len(df)
                    detection_run_id = create_detection_run(total_reports, result_df, config_id)
                    save_signal_history(detection_run_id, result_df)
                    detect_changes(detection_run_id, result_df)
                    generate_alerts(result_df, detection_run_id)

                st.success("信号检测完成！")
                st.rerun()

    with col1:
        sdf = st.session_state.signals_df
        if sdf.empty:
            st.info("尚未运行信号检测，请点击右侧按钮运行")
            return

        tab1, tab2 = st.tabs(["📊 检测结果", "🔄 信号变化"])
        st.session_state.detection_page_tab = "检测结果" if tab1 else "信号变化"

        with tab1:
            if st.session_state.selected_signal_for_detail is not None:
                sel = st.session_state.selected_signal_for_detail
                st.subheader(f"📋 信号详细分析: {sel['device_name']} - {sel['event_type']}")
                detail = get_signal_detail(sel['device_name'], sel['event_type'])
                if detail:
                    metrics_col = st.columns(4)
                    with metrics_col[0]:
                        st.metric("PRR", f"{detail['prr_value']:.3f}" if detail.get('prr_value') else "N/A",
                                  delta=f"CI: [{detail.get('prr_ci_lower', 'N/A'):.3f}, {detail.get('prr_ci_upper', 'N/A'):.3f}]" if detail.get('prr_ci_lower') else None)
                    with metrics_col[1]:
                        st.metric("ROR", f"{detail['ror_value']:.3f}" if detail.get('ror_value') else "N/A",
                                  delta=f"CI: [{detail.get('ror_ci_lower', 'N/A'):.3f}, {detail.get('ror_ci_upper', 'N/A'):.3f}]" if detail.get('ror_ci_lower') else None)
                    with metrics_col[2]:
                        st.metric("IC (BCPNN)", f"{detail['ic_value']:.3f}" if detail.get('ic_value') else "N/A",
                                  delta=f"IC025: {detail.get('ic025', 'N/A'):.3f}" if detail.get('ic025') else None)
                    with metrics_col[3]:
                        st.metric("EBGM (MGPS)", f"{detail['ebgm_value']:.3f}" if detail.get('ebgm_value') else "N/A",
                                  delta=f"EB05: {detail.get('eb05', 'N/A'):.3f}" if detail.get('eb05') else None)

                    all_reports = load_reports()
                    dev_reports = all_reports[all_reports["device_name"] == sel['device_name']]
                    if not dev_reports.empty:
                        monthly = compute_monthly_counts(dev_reports, sel['device_name'])
                        fig_t = px.line(monthly, x="year_month", y="count", markers=True, title=f"{sel['device_name']} 时间分布")
                        st.plotly_chart(fig_t, use_container_width=True, key="detail_trend_tab1")

                    col_back, _ = st.columns([1, 4])
                    with col_back:
                        if st.button("← 返回列表", type="primary", use_container_width=True, key="back_btn_tab1"):
                            st.session_state.selected_signal_for_detail = None
                            st.rerun()

                    st.divider()

            correction_label = {"fdr": "FDR校正后", "bonferroni": "Bonferroni校正后", "none": "校正前"}
            show_corrected = correction_method != "none"

            if show_corrected:
                sdf_display = sdf.copy()
                sdf_display["校正后信号强度"] = sdf_display.apply(
                    lambda row: get_corrected_signal_strength(row, correction_method), axis=1
                )
            else:
                sdf_display = sdf.copy()
                sdf_display["校正后信号强度"] = sdf_display["signal_strength"]

            st.subheader(f"检测结果（{correction_label.get(correction_method, '')}）")
            strength_filter = st.multiselect("筛选信号强度", ["强信号", "中等信号", "弱信号", "无信号"],
                                              default=["强信号", "中等信号", "弱信号"])
            filtered = sdf_display[sdf_display["校正后信号强度"].isin(strength_filter)]
            filtered = filtered.sort_values("signal_count", ascending=False)

            display_cols = ["device_name", "event_type", "report_count", "prr_value", "ror_value",
                            "ic_value", "ebgm_value", "signal_strength", "校正后信号强度"]
            if "bonferroni_signal" in filtered.columns:
                display_cols += ["bonferroni_signal", "fdr_signal"]
            existing = [c for c in display_cols if c in filtered.columns]
            st.dataframe(filtered[existing], use_container_width=True)

            col_a, col_b, col_c = st.columns(3)
            with col_a:
                strength_counts = sdf_display["校正后信号强度"].value_counts()
                fig = px.pie(values=strength_counts.values, names=strength_counts.index, title="信号强度分布", hole=0.4)
                st.plotly_chart(fig, use_container_width=True)
            with col_b:
                top_signals = sdf_display[sdf_display["校正后信号强度"] != "无信号"].nlargest(10, "signal_count")
                if not top_signals.empty:
                    fig2 = px.bar(top_signals, x="device_name", y="report_count", color="event_type",
                                  title="Top10信号报告数")
                    fig2.update_layout(xaxis_tickangle=-45)
                    st.plotly_chart(fig2, use_container_width=True)
            with col_c:
                if "p_value" in sdf.columns:
                    fig3 = go.Figure()
                    fig3.add_trace(go.Histogram(x=sdf["p_value"].dropna(), nbinsx=30, name="p-value"))
                    fig3.update_layout(title="P值分布", xaxis_title="p-value", yaxis_title="Count")
                    st.plotly_chart(fig3, use_container_width=True)

        with tab2:
            st.session_state.detection_page_tab = "信号变化"

            if st.session_state.selected_signal_for_detail is not None:
                sel = st.session_state.selected_signal_for_detail
                st.subheader(f"📋 信号详细分析: {sel['device_name']} - {sel['event_type']}")
                detail = get_signal_detail(sel['device_name'], sel['event_type'])
                if detail:
                    metrics_col = st.columns(4)
                    with metrics_col[0]:
                        st.metric("PRR", f"{detail['prr_value']:.3f}" if detail.get('prr_value') else "N/A",
                                  delta=f"CI: [{detail.get('prr_ci_lower', 'N/A'):.3f}, {detail.get('prr_ci_upper', 'N/A'):.3f}]" if detail.get('prr_ci_lower') else None)
                    with metrics_col[1]:
                        st.metric("ROR", f"{detail['ror_value']:.3f}" if detail.get('ror_value') else "N/A",
                                  delta=f"CI: [{detail.get('ror_ci_lower', 'N/A'):.3f}, {detail.get('ror_ci_upper', 'N/A'):.3f}]" if detail.get('ror_ci_lower') else None)
                    with metrics_col[2]:
                        st.metric("IC (BCPNN)", f"{detail['ic_value']:.3f}" if detail.get('ic_value') else "N/A",
                                  delta=f"IC025: {detail.get('ic025', 'N/A'):.3f}" if detail.get('ic025') else None)
                    with metrics_col[3]:
                        st.metric("EBGM (MGPS)", f"{detail['ebgm_value']:.3f}" if detail.get('ebgm_value') else "N/A",
                                  delta=f"EB05: {detail.get('eb05', 'N/A'):.3f}" if detail.get('eb05') else None)

                    all_reports = load_reports()
                    dev_reports = all_reports[all_reports["device_name"] == sel['device_name']]
                    if not dev_reports.empty:
                        monthly = compute_monthly_counts(dev_reports, sel['device_name'])
                        fig_t = px.line(monthly, x="year_month", y="count", markers=True, title=f"{sel['device_name']} 时间分布")
                        st.plotly_chart(fig_t, use_container_width=True, key="detail_trend_tab2")

                    col_back, _ = st.columns([1, 4])
                    with col_back:
                        if st.button("← 返回列表", type="primary", use_container_width=True, key="back_btn_tab2"):
                            st.session_state.selected_signal_for_detail = None
                            st.rerun()

                    st.divider()

            st.subheader("🔄 信号变化对比")
            last_run = get_last_detection_run()
            if not last_run:
                st.info("尚未运行过信号检测，无法对比变化")
            else:
                changes = get_changes_for_run(last_run["id"])
                if not changes:
                    st.info("本次检测与上一次检测相比，没有信号强度变化")
                    st.caption(f"检测运行时间: {last_run['run_time']}")
                else:
                    st.caption(f"对比时间: {last_run['run_time']} | 共 {len(changes)} 个变化")
                    change_df = pd.DataFrame(changes)

                    def format_change_icon(change_type):
                        if change_type == "升级":
                            return f"<span style='color:#d62728;font-size:20px;'>⬆️</span> <span style='color:#d62728;font-weight:bold;'>升级</span>"
                        elif change_type == "降级":
                            return f"<span style='color:#2ca02c;font-size:20px;'>⬇️</span> <span style='color:#2ca02c;font-weight:bold;'>降级</span>"
                        elif change_type == "新增":
                            return f"<span style='color:#1f77b4;font-size:20px;'>➕</span> <span style='color:#1f77b4;font-weight:bold;'>新增</span>"
                        else:
                            return f"<span style='color:#7f7f7f;font-size:20px;'>➖</span> <span style='color:#7f7f7f;font-weight:bold;'>消失</span>"

                    def format_strength(s):
                        color = {"强信号": "#d62728", "中等信号": "#ff7f0e", "弱信号": "#2ca02c", "无信号": "#7f7f7f"}
                        c = color.get(s, "#7f7f7f")
                        return f"<span style='color:{c};font-weight:bold;'>{s}</span>"

                    for idx, row in change_df.iterrows():
                        with st.container(border=True):
                            col_a, col_b, col_c, col_d = st.columns([2, 1, 1, 2])
                            with col_a:
                                st.markdown(f"**{row['device_name']}** - {row['event_type']}")
                            with col_b:
                                st.markdown(format_change_icon(row['change_type']), unsafe_allow_html=True)
                            with col_c:
                                st.markdown(
                                    f"{format_strength(row['previous_strength'])} → {format_strength(row['current_strength'])}",
                                    unsafe_allow_html=True
                                )
                            with col_d:
                                st.caption(f"历史: {row['previous_strength']} | 本次: {row['current_strength']}")
                                if pd.notna(row.get("signal_id")):
                                    if st.button(f"查看详情", key=f"change_detail_{idx}", use_container_width=True):
                                        st.session_state.selected_signal_for_detail = {
                                            "device_name": row["device_name"],
                                            "event_type": row["event_type"],
                                            "signal_id": int(row["signal_id"]),
                                        }
                                        st.rerun()


def page_matrix():
    st.title("🔥 器械-事件关联矩阵")
    sdf = st.session_state.signals_df
    if sdf.empty:
        st.info("请先运行信号检测")
        return

    col1, col2 = st.columns(2)
    with col1:
        device_categories = sdf["device_name"].unique().tolist()
        selected_cat = st.selectbox("器械大类筛选", ["全部"] + device_categories)
    with col2:
        event_types = sdf["event_type"].unique().tolist()
        selected_evt = st.selectbox("事件类型筛选", ["全部"] + event_types)

    matrix_df = sdf.copy()
    if selected_cat != "全部":
        matrix_df = matrix_df[matrix_df["device_name"] == selected_cat]
    if selected_evt != "全部":
        matrix_df = matrix_df[matrix_df["event_type"] == selected_evt]

    corr_method = st.session_state.get("correction_method", "fdr")
    if corr_method != "none":
        matrix_df["display_strength"] = matrix_df.apply(lambda r: get_corrected_signal_strength(r, corr_method), axis=1)
    else:
        matrix_df["display_strength"] = matrix_df["signal_strength"]

    strength_map = {"强信号": 4, "中等信号": 3, "弱信号": 2, "无信号": 1}
    matrix_df["strength_num"] = matrix_df["display_strength"].map(strength_map)

    pivot = matrix_df.pivot_table(index="device_name", columns="event_type", values="strength_num", fill_value=0)
    pivot_order = pivot.loc[pivot.sum(axis=1).sort_values(ascending=False).index]
    pivot_order = pivot_order[pivot_order.sum(axis=0).sort_values(ascending=False).index]

    fig = go.Figure(data=go.Heatmap(
        z=pivot_order.values,
        x=pivot_order.columns.tolist(),
        y=pivot_order.index.tolist(),
        colorscale=[[0, "#f7fbff"], [0.25, "#6baed6"], [0.5, "#2171b5"], [0.75, "#fdae6b"], [1, "#d62728"]],
        showscale=True,
        text=[[["无信号", "弱信号", "中等信号", "强信号"][int(v) - 1] if v > 0 else "" for v in row] for row in pivot_order.values],
        texttemplate="%{text}",
        hovertemplate="器械: %{y}<br>事件: %{x}<br>强度: %{text}<extra></extra>",
    ))
    fig.update_layout(title="器械-事件信号强度矩阵", xaxis_title="事件类型", yaxis_title="器械名称", height=max(400, len(pivot_order) * 30))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("点击查看详细分析")
    col1, col2 = st.columns(2)
    with col1:
        sel_device = st.selectbox("选择器械", matrix_df["device_name"].unique().tolist())
    with col2:
        sel_event = st.selectbox("选择事件类型", matrix_df["event_type"].unique().tolist())

    if st.button("查看详细", key="detail_btn"):
        detail = get_signal_detail(sel_device, sel_event)
        if detail:
            st.subheader(f"{sel_device} - {sel_event} 详细指标")
            metrics_col = st.columns(4)
            with metrics_col[0]:
                st.metric("PRR", f"{detail['prr_value']:.3f}" if detail.get('prr_value') else "N/A",
                          delta=f"CI: [{detail.get('prr_ci_lower', 'N/A'):.3f}, {detail.get('prr_ci_upper', 'N/A'):.3f}]" if detail.get('prr_ci_lower') else None)
            with metrics_col[1]:
                st.metric("ROR", f"{detail['ror_value']:.3f}" if detail.get('ror_value') else "N/A",
                          delta=f"CI: [{detail.get('ror_ci_lower', 'N/A'):.3f}, {detail.get('ror_ci_upper', 'N/A'):.3f}]" if detail.get('ror_ci_lower') else None)
            with metrics_col[2]:
                st.metric("IC (BCPNN)", f"{detail['ic_value']:.3f}" if detail.get('ic_value') else "N/A",
                          delta=f"IC025: {detail.get('ic025', 'N/A'):.3f}" if detail.get('ic025') else None)
            with metrics_col[3]:
                st.metric("EBGM (MGPS)", f"{detail['ebgm_value']:.3f}" if detail.get('ebgm_value') else "N/A",
                          delta=f"EB05: {detail.get('eb05', 'N/A'):.3f}" if detail.get('eb05') else None)

            all_reports = load_reports()
            dev_reports = all_reports[all_reports["device_name"] == sel_device]
            if not dev_reports.empty:
                monthly = compute_monthly_counts(dev_reports, sel_device)
                fig_t = px.line(monthly, x="year_month", y="count", markers=True, title=f"{sel_device} 时间分布")
                st.plotly_chart(fig_t, use_container_width=True)
        else:
            st.warning("未找到该组合的信号数据")


def page_time_trend():
    st.title("📈 时间趋势与突变检测")
    df = load_reports()
    if df.empty:
        st.info("请先导入数据")
        return

    devices = df["device_name"].unique().tolist()
    selected_device = st.selectbox("选择器械", devices)

    dev_df = df[df["device_name"] == selected_device]
    monthly = compute_monthly_counts(dev_df, selected_device)

    if monthly.empty:
        st.warning("该器械无数据")
        return

    st.subheader("月度报告趋势")
    fig = px.line(monthly, x="year_month", y="count", markers=True, title=f"{selected_device} 月度报告数")
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("CUSUM 累积和控制图")
    monthly_cusum, alerts = compute_cusum(monthly)

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=monthly_cusum["year_month"], y=monthly_cusum["count"], mode="lines+markers", name="报告数"))
    if "cusum" in monthly_cusum.columns:
        fig2.add_trace(go.Scatter(x=monthly_cusum["year_month"], y=monthly_cusum["cusum"], mode="lines+markers", name="CUSUM", yaxis="y2"))
        fig2.add_trace(go.Scatter(x=monthly_cusum["year_month"], y=monthly_cusum["threshold"], mode="lines", name="阈值", line=dict(dash="dash", color="red"), yaxis="y2"))
    fig2.update_layout(yaxis2=dict(overlaying="y", side="right", title="CUSUM"), title="CUSUM控制图")
    st.plotly_chart(fig2, use_container_width=True)

    if alerts:
        st.subheader("⚠️ 突变告警")
        alert_df = pd.DataFrame(alerts)
        st.dataframe(alert_df, use_container_width=True)
        save_cusum_alerts(alerts, selected_device)
    else:
        st.success("未检测到突变")

    st.subheader("趋势分析（去季节性后）")
    trend_result, deseasonalized, x_vals, fitted = detect_trend(monthly)
    if trend_result:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("趋势斜率", f"{trend_result['slope']:.4f}")
        with col2:
            st.metric("斜率p值", f"{trend_result['p_value']:.4f}")
            if trend_result["is_increasing"]:
                st.error("🔴 检测到显著上升趋势！")
            else:
                st.success("未检测到显著上升趋势")

        if deseasonalized is not None:
            fig3 = go.Figure()
            fig3.add_trace(go.Scatter(x=list(range(len(deseasonalized))), y=deseasonalized, mode="lines+markers", name="去季节性"))
            if fitted is not None:
                fig3.add_trace(go.Scatter(x=list(range(len(fitted))), y=fitted, mode="lines", name="线性趋势", line=dict(dash="dash")))
            fig3.update_layout(title="去季节性趋势分析", xaxis_title="月序号", yaxis_title="报告数")
            st.plotly_chart(fig3, use_container_width=True)
    else:
        st.info("数据不足，无法进行趋势分析")


def page_subgroup():
    st.title("👥 亚组分层分析")
    sdf = st.session_state.signals_df
    if sdf.empty:
        st.info("请先运行信号检测")
        return

    signals_only = sdf[sdf["signal_strength"] != "无信号"]
    if signals_only.empty:
        st.info("没有检测到信号")
        return

    col1, col2 = st.columns(2)
    with col1:
        sel_device = st.selectbox("选择器械", signals_only["device_name"].unique().tolist(), key="sg_dev")
    with col2:
        sel_event = st.selectbox("选择事件类型", signals_only["event_type"].unique().tolist(), key="sg_evt")

    if st.button("运行亚组分析", type="primary"):
        df = load_reports()
        with st.spinner("正在计算亚组分析..."):
            results = run_all_stratifications(df, sel_device, sel_event)

        st.subheader("整体PRR")
        st.metric("PRR", f"{results['overall_prr']:.3f}" if results['overall_prr'] and not np.isnan(results['overall_prr']) else "N/A")

        for group_name, group_df in [("年龄段", results["age"]), ("性别", results["gender"]), ("使用场景", results["scenario"])]:
            st.subheader(f"按{group_name}分层")
            if group_df.empty:
                st.info(f"无{group_name}亚组数据")
                continue

            display_df = group_df[["subgroup", "report_count", "total_in_subgroup", "prr", "prr_ci_lower", "prr_ci_upper", "p_value", "prr_ratio_to_overall", "is_elevated"]].copy()
            display_df.columns = ["亚组", "报告数", "亚组总数", "PRR", "CI下限", "CI上限", "p值", "PRR比(亚组/整体)", "信号增强"]
            st.dataframe(display_df, use_container_width=True)

            fig = px.bar(group_df, x="subgroup", y="prr", error_y=group_df.get("prr_ci_upper"), error_y_minus=group_df.get("prr_ci_lower"),
                         title=f"{group_name}分层PRR", labels={"subgroup": group_name, "prr": "PRR"})
            if results["overall_prr"] and not np.isnan(results["overall_prr"]):
                fig.add_hline(y=results["overall_prr"], line_dash="dash", line_color="red", annotation_text="整体PRR")
            st.plotly_chart(fig, use_container_width=True)

            elevated = group_df[group_df["is_elevated"]]
            if not elevated.empty:
                for _, row in elevated.iterrows():
                    st.warning(f"⚠️ 亚组 '{row['subgroup']}' 的信号显著高于整体 (PRR比={row['prr_ratio_to_overall']:.2f} > 1.5)")


def page_similar():
    st.title("🔄 同类器械对比")
    df = load_reports()
    if df.empty:
        st.info("请先导入数据")
        return

    devices_with_code = df[df["device_class_code"].notna()]["device_name"].unique().tolist()

    if not devices_with_code:
        st.error("🔴 当前数据中缺少'器械分类编码'字段，无法进行同类对比")
        st.info("""
        **关于器械分类编码：**
        
        器械分类编码是国家医疗器械分类标准编码（如YY/T 0468或NMPA分类编码），用于：
        - 精确识别同品类器械
        - 编码前4位相同的器械视为同品类
        - 同类对比功能依赖此字段
        
        **解决方法：**
        1. 在导入的CSV/Excel文件中添加'器械分类编码'列
        2. 参考国家医疗器械分类数据库获取正确编码
        3. 重新导入数据后即可使用本功能
        
        💡 可在'数据导入'页面查看完整字段说明
        """)

        st.subheader("当前已导入器械列表")
        all_devices = df["device_name"].unique().tolist()
        device_df = pd.DataFrame({
            "器械名称": all_devices,
            "报告数": [len(df[df["device_name"] == d]) for d in all_devices],
            "是否有分类编码": ["❌ 缺失" for _ in all_devices],
        })
        st.dataframe(device_df, use_container_width=True)
        return

    selected = st.selectbox("选择器械", devices_with_code)

    if st.button("对比分析", type="primary"):
        with st.spinner("正在对比同类器械..."):
            result = compare_similar_devices(selected, df)

        if result.empty:
            st.warning("未找到同类器械")
            return

        st.subheader("同类器械对比结果")
        display_cols = ["device_name", "total_reports", "report_rate_per_year", "signal_count", "is_target", "is_outlier"]
        existing = [c for c in display_cols if c in result.columns]
        st.dataframe(result[existing], use_container_width=True)

        st.subheader("报告率对比")
        fig = px.bar(result, x="device_name", y="report_rate_per_year",
                     color="is_outlier", color_discrete_map={True: "red", False: "steelblue"},
                     title=f"同类器械报告率对比 (红色=超出平均+2σ)")
        fig.add_hline(y=result["report_rate_per_year"].mean(), line_dash="dash", line_color="green", annotation_text="平均")
        if "z_score" in result.columns and result["z_score"].std() > 0:
            fig.add_hline(y=result["report_rate_per_year"].mean() + 2 * result["report_rate_per_year"].std(),
                          line_dash="dash", line_color="red", annotation_text="平均+2σ")
        fig.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)

        fig2 = px.bar(result, x="device_name", y="signal_count",
                      color="is_target", color_discrete_map={True: "orange", False: "steelblue"},
                      title="同类器械信号数量对比")
        fig2.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig2, use_container_width=True)


def page_kanban():
    st.title("📋 信号评估看板")

    sdf = st.session_state.signals_df
    if sdf.empty:
        st.info("请先运行信号检测")
        return

    kanban = get_kanban_data()

    col_op, col_note = st.columns([1, 3])
    with col_op:
        operator = st.text_input("当前操作人", value="分析员", key="kanban_operator")
    with col_note:
        batch_note = st.text_input("批量备注（可留空）", key="kanban_batch_note", placeholder="可填写批量操作的备注说明")

    st.divider()

    status_cols = st.columns(4)
    status_names = ["待评估", "评估中", "确认信号", "排除"]
    status_colors = ["#FFA500", "#1E90FF", "#32CD32", "#808080"]

    quick_actions = {
        "待评估": [("→ 评估中", "评估中", "#1E90FF"), ("→ 排除", "排除", "#808080")],
        "评估中": [("→ 确认信号", "确认信号", "#32CD32"), ("→ 排除", "排除", "#808080"), ("← 返回待评估", "待评估", "#FFA500")],
        "确认信号": [("← 返回评估中", "评估中", "#1E90FF"), ("→ 排除", "排除", "#808080")],
        "排除": [("← 恢复待评估", "待评估", "#FFA500")],
    }

    for i, (status, color) in enumerate(zip(status_names, status_colors)):
        with status_cols[i]:
            items = kanban.get(status, [])
            st.markdown(f"<h3 style='color:{color};text-align:center;'>{status} ({len(items)})</h3>", unsafe_allow_html=True)
            st.divider()

            for idx, item in enumerate(items):
                strength_color = {"强信号": "#d62728", "中等信号": "#ff7f0e", "弱信号": "#2ca02c", "无信号": "#999"}
                sc = strength_color.get(item.get("signal_strength", ""), "#999")
                item_id = item.get("id", f"{item['device_name']}_{item['event_type']}_{idx}")

                with st.container(border=True):
                    col_info, col_actions = st.columns([3, 2])
                    with col_info:
                        st.markdown(f"**{item.get('device_name', 'N/A')}**")
                        st.markdown(f"📌 {item.get('event_type', 'N/A')}")
                        st.markdown(f"<span style='color:{sc};font-weight:bold;'>{item.get('signal_strength', 'N/A')}</span>", unsafe_allow_html=True)
                        st.caption(f"📊 报告数: {item.get('report_count', 0)} | ID: {item.get('id', 'N/A')}")

                    with col_actions:
                        st.caption("**快捷操作**")
                        for label, target, btn_color in quick_actions.get(status, []):
                            btn_key = f"quick_{item_id}_{target}"
                            if st.button(label, key=btn_key, use_container_width=True, type="secondary"):
                                try:
                                    notes = batch_note if batch_note else f"从{status}变更为{target}"
                                    update_signal_status(item["id"], target, operator, notes)
                                    st.rerun()
                                except Exception as e:
                                    st.error(str(e))

                    if status == "确认信号":
                        st.divider()
                        col_act, col_btn = st.columns([2, 1])
                        with col_act:
                            action = st.selectbox(
                                "行动措施",
                                ["继续监测", "发布安全警示", "召回", "修改说明书"],
                                key=f"action_select_{item_id}",
                            )
                        with col_btn:
                            st.write("")
                            if st.button("设置", key=f"act_btn_{item_id}", type="primary"):
                                try:
                                    notes = f"设置行动措施: {action}"
                                    set_action_measure(item["id"], action, operator, notes)
                                    st.success(f"✅ 已设置: {action}")
                                    st.rerun()
                                except Exception as e:
                                    st.error(str(e))

                    if item.get("action_measure"):
                        st.caption(f"🛠️ 行动措施: **{item.get('action_measure', '')}**")

                st.write("")

    st.divider()
    st.subheader("📋 信号详情查询")
    signal_id = st.number_input("输入信号ID", min_value=1, step=1)
    if st.button("查询详情"):
        detail = get_signal_with_workflow(signal_id)
        if detail:
            st.markdown("### 信号基本信息")
            st.json(detail["signal"])
            st.markdown("### 操作历史")
            history_df = pd.DataFrame(detail["workflow_history"])
            if not history_df.empty:
                history_df = history_df[["created_at", "operator", "status", "notes", "action_measure"]]
                history_df.columns = ["操作时间", "操作人", "状态", "备注", "行动措施"]
                st.dataframe(history_df, use_container_width=True)
        else:
            st.warning("未找到该信号")

    st.divider()
    st.caption("💡 使用提示：点击卡片右侧的快捷按钮可快速变更状态，无需额外确认。看板已自动过滤'无信号'的条目。")


def page_config():
    st.title("⚙️ 检测参数配置")

    active_config = get_active_config()

    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader("自定义检测阈值")
        st.info("修改以下参数后点击'保存配置'按钮，新配置将在下次信号检测时生效。")

        with st.form("config_form"):
            st.markdown("#### PRR算法参数")
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                prr_threshold = st.number_input(
                    "PRR阈值",
                    min_value=1.0,
                    max_value=10.0,
                    value=float(active_config.get("prr_threshold", 2.0)),
                    step=0.1,
                    help="PRR >= 该值则判定为信号"
                )
            with col_b:
                min_report_count = st.number_input(
                    "最小报告数",
                    min_value=1,
                    max_value=50,
                    value=int(active_config.get("min_report_count", 3)),
                    step=1,
                    help="报告数 >= 该值才考虑为信号"
                )
            with col_c:
                p_value_threshold = st.number_input(
                    "卡方检验p值阈值",
                    min_value=0.001,
                    max_value=0.1,
                    value=float(active_config.get("p_value_threshold", 0.05)),
                    step=0.001,
                    format="%.3f",
                    help="p值 < 该值则判定为显著"
                )

            st.divider()
            st.markdown("#### 其他算法参数")
            col_d, col_e, col_f = st.columns(3)
            with col_d:
                ror_lower_threshold = st.number_input(
                    "ROR下限阈值",
                    min_value=0.5,
                    max_value=5.0,
                    value=float(active_config.get("ror_lower_threshold", 1.0)),
                    step=0.1,
                    help="ROR置信区间下限 > 该值则判定为信号"
                )
            with col_e:
                ic025_threshold = st.number_input(
                    "IC025阈值",
                    min_value=-2.0,
                    max_value=5.0,
                    value=float(active_config.get("ic025_threshold", 0.0)),
                    step=0.1,
                    help="IC025 > 该值则判定为信号"
                )
            with col_f:
                eb05_threshold = st.number_input(
                    "EB05阈值",
                    min_value=0.5,
                    max_value=10.0,
                    value=float(active_config.get("eb05_threshold", 2.0)),
                    step=0.1,
                    help="EB05 >= 该值则判定为信号"
                )

            st.divider()
            st.markdown("#### 加权投票参数")
            strong_signal_min_methods = st.number_input(
                "强信号所需最少阳性方法数",
                min_value=2,
                max_value=4,
                value=int(active_config.get("strong_signal_min_methods", 3)),
                step=1,
                help="4种方法中至少有多少种判定为阳性才算强信号"
            )

            st.divider()
            col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1])
            with col_btn1:
                submitted = st.form_submit_button("💾 保存配置", type="primary", use_container_width=True)
            with col_btn2:
                reset = st.form_submit_button("🔄 恢复默认值", use_container_width=True)
            with col_btn3:
                operator = st.text_input("操作人", value="分析员")

            if submitted:
                new_config = {
                    "prr_threshold": prr_threshold,
                    "min_report_count": min_report_count,
                    "p_value_threshold": p_value_threshold,
                    "ror_lower_threshold": ror_lower_threshold,
                    "ic025_threshold": ic025_threshold,
                    "eb05_threshold": eb05_threshold,
                    "strong_signal_min_methods": strong_signal_min_methods,
                }
                save_new_config(new_config, created_by=operator)
                st.success("配置已保存！下次信号检测将使用新参数。")
                st.rerun()

            if reset:
                reset_to_default()
                st.success("已恢复为默认配置！")
                st.rerun()

    with col2:
        st.subheader("当前配置对比")
        current = get_active_config()
        comparison_data = []
        param_labels = {
            "prr_threshold": "PRR阈值",
            "min_report_count": "最小报告数",
            "p_value_threshold": "p值阈值",
            "ror_lower_threshold": "ROR下限阈值",
            "ic025_threshold": "IC025阈值",
            "eb05_threshold": "EB05阈值",
            "strong_signal_min_methods": "强信号最少方法数",
        }

        for key, label in param_labels.items():
            default_val = DEFAULT_CONFIG.get(key, "-")
            current_val = current.get(key, "-")
            is_changed = default_val != current_val
            comparison_data.append({
                "参数": label,
                "默认值": default_val,
                "当前值": current_val,
                "状态": "✅ 已修改" if is_changed else "⚪ 默认值"
            })

        comparison_df = pd.DataFrame(comparison_data)
        st.dataframe(comparison_df, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("历史配置记录")
        all_configs = get_all_configs()
        if all_configs:
            history_data = []
            for cfg in all_configs[:10]:
                history_data.append({
                    "ID": cfg["id"],
                    "创建时间": cfg["created_at"],
                    "创建人": cfg.get("created_by", "系统"),
                    "PRR阈值": cfg["prr_threshold"],
                    "最小报告数": cfg["min_report_count"],
                    "状态": "✅ 生效中" if cfg["is_active"] == 1 else "⚪ 已过期"
                })
            history_df = pd.DataFrame(history_data)
            st.dataframe(history_df, use_container_width=True, hide_index=True)
        else:
            st.info("暂无历史配置记录")


def page_export():
    st.title("📄 报告导出")

    sdf = st.session_state.signals_df
    if sdf.empty:
        st.info("请先运行信号检测")
        return

    st.subheader("报告内容预览")
    stats = get_report_stats()
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("报告总数", stats["total_reports"])
    with col2:
        st.metric("涉及器械数", stats["total_devices"])
    with col3:
        st.metric("涉及事件类型数", stats["total_event_types"])

    strength_counts = sdf["signal_strength"].value_counts()
    st.write("信号强度分布:", dict(strength_counts))

    col_a, col_b = st.columns([1, 1])
    with col_a:
        submitter = st.text_input("报告生成人", value="分析员")
    with col_b:
        st.write("")
        st.write("")
        generate_btn = st.button("生成PDF报告", type="primary", use_container_width=True)

    if generate_btn:
        with st.spinner("正在生成PDF报告..."):
            try:
                pdf_path, report_version_id, version_number = generate_pdf_report(submitter=submitter)
                with open(pdf_path, "rb") as f:
                    st.download_button(
                        label="📥 下载PDF报告",
                        data=f.read(),
                        file_name=f"adverse_event_signal_report_v{version_number}.pdf",
                        mime="application/pdf",
                    )
                if report_version_id:
                    st.success(f"✅ PDF报告生成成功！版本号: v{version_number}，已自动创建报告版本记录")
                    st.info(f"💡 可在'📝 报告审阅'页面查看和管理该报告版本")
                    col1, col2 = st.columns([1, 1])
                    with col1:
                        if st.button("📝 前往审阅页面", use_container_width=True):
                            st.session_state.selected_report_for_detail = report_version_id
                            st.session_state.review_page_tab = "报告审阅看板"
                            st.rerun()
                else:
                    st.success("PDF报告生成成功！")
            except Exception as e:
                st.error(f"生成PDF失败: {e}")

    st.divider()
    st.subheader("📚 历史报告版本")
    versions = get_all_report_versions()
    if not versions:
        st.info("暂无历史报告版本")
    else:
        vdf = pd.DataFrame(versions)
        display_cols = ["version_number", "generation_time", "status", "submitter", "id"]
        existing_cols = [c for c in display_cols if c in vdf.columns]
        vdf_display = vdf[existing_cols].copy()
        vdf_display.columns = ["版本号", "生成时间", "状态", "提交人", "版本ID"]
        st.dataframe(vdf_display, use_container_width=True)

        with st.expander("📊 版本对比", expanded=False):
            col_c1, col_c2 = st.columns(2)
            version_options = [f"v{v['version_number']} (ID: {v['id']})" for v in versions]
            version_map = {f"v{v['version_number']} (ID: {v['id']})": v["id"] for v in versions}
            with col_c1:
                v1_sel = st.selectbox("选择版本1", version_options, key="v1_compare")
            with col_c2:
                v2_sel = st.selectbox("选择版本2", version_options, key="v2_compare")
            if st.button("对比版本", key="compare_btn", type="primary"):
                v1_id = version_map[v1_sel]
                v2_id = version_map[v2_sel]
                changes = compare_report_versions(v1_id, v2_id)
                if not changes:
                    st.info("两个版本之间没有信号强度变化")
                else:
                    st.success(f"发现 {len(changes)} 个信号变化")
                    change_type_icons = {
                        "新增": "➕", "消失": "➖", "升级": "⬆️", "降级": "⬇️"
                    }
                    change_type_colors = {
                        "新增": "#1f77b4", "消失": "#7f7f7f", "升级": "#d62728", "降级": "#2ca02c"
                    }
                    for c in changes:
                        with st.container(border=True):
                            col1, col2, col3, col4 = st.columns([2, 1, 2, 2])
                            with col1:
                                st.markdown(f"**{c['device_name']}** - {c['event_type']}")
                            with col2:
                                icon = change_type_icons.get(c['change_type'], "")
                                color = change_type_colors.get(c['change_type'], "#333")
                                st.markdown(f"<span style='color:{color};font-weight:bold;font-size:18px;'>{icon} {c['change_type']}</span>", unsafe_allow_html=True)
                            with col3:
                                old_s = c['old_strength'] or "无"
                                new_s = c['new_strength'] or "无"
                                strength_color = {"强信号": "#d62728", "中等信号": "#ff7f0e", "弱信号": "#2ca02c", "无信号": "#7f7f7f", "无": "#999"}
                                oc = strength_color.get(old_s, "#999")
                                nc = strength_color.get(new_s, "#999")
                                st.markdown(f"<span style='color:{oc};'>{old_s}</span> → <span style='color:{nc};'>{new_s}</span>", unsafe_allow_html=True)
                            with col4:
                                if c.get('old_signal'):
                                    old_prr = f"{c['old_signal']['prr_value']:.3f}" if c['old_signal'].get('prr_value') else "N/A"
                                else:
                                    old_prr = "N/A"
                                if c.get('new_signal'):
                                    new_prr = f"{c['new_signal']['prr_value']:.3f}" if c['new_signal'].get('prr_value') else "N/A"
                                else:
                                    new_prr = "N/A"
                                st.caption(f"PRR: {old_prr} → {new_prr}")


def page_review_kanban():
    st.title("📝 报告审阅")

    col_cr, col_cur = st.columns([3, 1])
    with col_cr:
        current_reviewer_name = st.selectbox(
            "选择当前审阅人身份",
            ["请选择..."] + [r["name"] for r in get_all_reviewers()],
            key="current_reviewer_selector"
        )
        if current_reviewer_name != "请选择...":
            st.session_state.current_reviewer = get_reviewer_by_name(current_reviewer_name)
        else:
            st.session_state.current_reviewer = None
    with col_cur:
        st.write("")
        st.caption("💡 选择身份后可进行审批操作")

    if st.session_state.current_reviewer:
        r = st.session_state.current_reviewer
        role_color = {"初审员": "#2ca02c", "高级审阅员": "#ff7f0e", "主管": "#d62728"}
        rc = role_color.get(r["role"], "#333")
        st.success(f"✅ 当前身份: <span style='color:{rc};font-weight:bold;'>{r['name']}</span> ({r['role']})", unsafe_allow_html=True)

    st.divider()

    tab1, tab2, tab3 = st.tabs(["📋 审阅看板", "📊 审阅统计", "📚 版本对比"])

    with tab1:
        st.session_state.review_page_tab = "报告审阅看板"
        kanban = get_review_kanban()

        status_cols = st.columns(5)
        status_names = ["草稿", "审阅中", "已批准", "已退回", "已超时"]
        status_colors = ["#95a5a6", "#3498db", "#27ae60", "#e74c3c", "#8e44ad"]

        for i, (status, color) in enumerate(zip(status_names, status_colors)):
            with status_cols[i]:
                items = kanban.get(status, [])
                st.markdown(f"<h3 style='color:{color};text-align:center;'>{status} ({len(items)})</h3>", unsafe_allow_html=True)
                st.divider()

                for idx, item in enumerate(items):
                    card_style = "border: 2px solid #e74c3c;" if item.get("is_urgent") else ""
                    with st.container(border=True):
                        col_info, col_actions = st.columns([3, 2])
                        with col_info:
                            st.markdown(f"**📄 版本 v{item['version_number']}**")
                            st.caption(f"🕐 {item['generation_time']}")
                            
                            if item.get("remaining_time"):
                                if item.get("is_urgent"):
                                    st.markdown(f"<span style='color:#e74c3c;font-weight:bold;'>⏰ 即将超时</span>", unsafe_allow_html=True)
                                elif item["status"] != "已超时":
                                    st.markdown(f"⏰ {item['remaining_time']}")
                                if item.get("deadline"):
                                    st.caption(f"截止时间: {item['deadline'][:19]}")
                            
                            st.markdown(f"📊 信号数: **{item['signal_count']}** 条")
                            annot_badge = f" <span style='background-color:#e74c3c;color:white;padding:2px 8px;border-radius:10px;font-size:12px;'>💬 {item['annotation_count']}</span>" if item['annotation_count'] > 0 else ""
                            st.markdown(f"📝 批注数: {item['annotation_count']}{annot_badge}", unsafe_allow_html=True)

                            if item.get("reviewers"):
                                reviewer_text = ", ".join([f"{r['name']}({r['role']})" for r in item["reviewers"]])
                                st.caption(f"👥 审阅人: {reviewer_text}")

                            if item["status"] == "已退回" and item.get("reject_reason"):
                                st.error(f"❌ 退回理由: {item['reject_reason']}")
                            
                            if item["status"] == "已超时":
                                st.warning("⚠️ 报告已超时，审阅人无法操作")

                        with col_actions:
                            if st.button("查看详情", key=f"view_report_{item['id']}_{idx}", use_container_width=True, type="primary"):
                                st.session_state.selected_report_for_detail = item["id"]
                                st.rerun()

                            if item["status"] == "草稿":
                                if st.button("提交审阅", key=f"submit_{item['id']}_{idx}", use_container_width=True):
                                    st.session_state[f"submit_dialog_{item['id']}"] = True
                                    st.rerun()

                            if item["status"] == "审阅中" and st.session_state.current_reviewer:
                                assignments = item.get("reviewers", [])
                                reviewer_ids = [a for a in assignments if a.get("name") == st.session_state.current_reviewer["name"]]
                                if reviewer_ids and not reviewer_ids[0].get("decision"):
                                    decision = st.selectbox(
                                        "审批决策",
                                        ["选择...", "批准", "退回", "请求修改"],
                                        key=f"decision_{item['id']}_{idx}"
                                    )
                                    comments = st.text_area("意见", key=f"comments_{item['id']}_{idx}", height=60)
                                    if st.button("提交决策", key=f"submit_decision_{item['id']}_{idx}", use_container_width=True):
                                        if decision != "选择...":
                                            if decision == "退回" and not comments:
                                                st.error("退回必须填写理由")
                                            else:
                                                try:
                                                    make_review_decision(
                                                        item["id"],
                                                        st.session_state.current_reviewer["id"],
                                                        decision,
                                                        comments
                                                    )
                                                    st.success(f"✅ 已{decision}")
                                                    st.rerun()
                                                except Exception as e:
                                                    st.error(str(e))
                            
                            if item["status"] == "已超时" and st.session_state.current_reviewer:
                                is_submitter = item.get("submitter") == st.session_state.current_reviewer["name"]
                                if is_submitter:
                                    st.caption("发起人操作:")
                                    if st.button("延期", key=f"extend_{item['id']}_{idx}", use_container_width=True):
                                        st.session_state[f"extend_dialog_{item['id']}"] = True
                                        st.rerun()
                                    if st.button("强制关闭", key=f"close_{item['id']}_{idx}", use_container_width=True):
                                        try:
                                            force_close(item["id"], st.session_state.current_reviewer["id"])
                                            st.success("✅ 已强制关闭")
                                            st.rerun()
                                        except Exception as e:
                                            st.error(str(e))

                    if st.session_state.get(f"submit_dialog_{item['id']}"):
                        with st.expander(f"选择审阅人 - 版本 v{item['version_number']}", expanded=True):
                            reviewers = get_all_reviewers()
                            selected = st.multiselect(
                                "请选择审阅人（至少1位）",
                                [f"{r['name']} ({r['role']})" for r in reviewers],
                                key=f"reviewer_select_{item['id']}"
                            )
                            from datetime import datetime, timedelta
                            col_d1, col_d2 = st.columns(2)
                            with col_d1:
                                deadline_date = st.date_input(
                                    "截止日期",
                                    value=datetime.now() + timedelta(days=7),
                                    key=f"deadline_date_{item['id']}"
                                )
                            with col_d2:
                                deadline_time = st.time_input(
                                    "截止时间",
                                    value=datetime.now().time().replace(hour=17, minute=0),
                                    key=f"deadline_time_{item['id']}"
                                )
                            col_s, col_c = st.columns(2)
                            with col_s:
                                if st.button("确认提交", key=f"confirm_submit_{item['id']}", type="primary", use_container_width=True):
                                    if selected:
                                        deadline = datetime.combine(deadline_date, deadline_time).strftime("%Y-%m-%d %H:%M:%S")
                                        reviewer_ids = []
                                        for s in selected:
                                            name = s.split(" (")[0]
                                            rv = get_reviewer_by_name(name)
                                            if rv:
                                                reviewer_ids.append(rv["id"])
                                        try:
                                            submit_for_review(
                                                item["id"],
                                                reviewer_ids,
                                                deadline,
                                                submitter_name=st.session_state.current_reviewer["name"] if st.session_state.current_reviewer else "系统"
                                            )
                                            st.success("✅ 已提交审阅")
                                            st.session_state[f"submit_dialog_{item['id']}"] = False
                                            st.rerun()
                                        except Exception as e:
                                            st.error(str(e))
                                    else:
                                        st.error("请至少选择一位审阅人")
                            with col_c:
                                if st.button("取消", key=f"cancel_submit_{item['id']}", use_container_width=True):
                                    st.session_state[f"submit_dialog_{item['id']}"] = False
                                    st.rerun()
                    
                    if st.session_state.get(f"extend_dialog_{item['id']}"):
                        with st.expander(f"延期处理 - 版本 v{item['version_number']}", expanded=True):
                            from datetime import datetime, timedelta
                            col_d1, col_d2 = st.columns(2)
                            with col_d1:
                                new_deadline_date = st.date_input(
                                    "新截止日期",
                                    value=datetime.now() + timedelta(days=3),
                                    key=f"new_deadline_date_{item['id']}"
                                )
                            with col_d2:
                                new_deadline_time = st.time_input(
                                    "新截止时间",
                                    value=datetime.now().time().replace(hour=17, minute=0),
                                    key=f"new_deadline_time_{item['id']}"
                                )
                            col_s, col_c = st.columns(2)
                            with col_s:
                                if st.button("确认延期", key=f"confirm_extend_{item['id']}", type="primary", use_container_width=True):
                                    new_deadline = datetime.combine(new_deadline_date, new_deadline_time).strftime("%Y-%m-%d %H:%M:%S")
                                    try:
                                        extend_deadline(
                                            item["id"],
                                            new_deadline,
                                            st.session_state.current_reviewer["id"]
                                        )
                                        st.success("✅ 已延期")
                                        st.session_state[f"extend_dialog_{item['id']}"] = False
                                        st.rerun()
                                    except Exception as e:
                                        st.error(str(e))
                            with col_c:
                                if st.button("取消", key=f"cancel_extend_{item['id']}", use_container_width=True):
                                    st.session_state[f"extend_dialog_{item['id']}"] = False
                                    st.rerun()

    with tab2:
        st.session_state.review_page_tab = "审阅统计"
        stats = get_review_statistics()

        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("平均审阅耗时", f"{stats['avg_review_days']} 天")
        with col2:
            st.metric("退回率", f"{stats['reject_rate']} %")
        with col3:
            st.metric("超时率", f"{stats['timeout_rate']} %", help="超时报告数 / 提交审阅数")
        with col4:
            total = sum(stats.get("status_distribution", {}).values())
            st.metric("报告总数", total)
        with col5:
            approved = stats.get("status_distribution", {}).get("已批准", 0)
            st.metric("已批准报告", approved)

        st.divider()

        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("📊 各审阅人审阅量排行")
            if stats["reviewer_ranking"]:
                rdf = pd.DataFrame(stats["reviewer_ranking"])
                fig = px.bar(rdf, x="name", y="review_count",
                             color="review_count",
                             title="审阅量统计",
                             labels={"name": "审阅人", "review_count": "审阅数量"})
                fig.update_layout(xaxis_tickangle=-45)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("暂无审阅数据")

        with col_b:
            st.subheader("🔥 批注热度Top5信号")
            if stats["top_annotated_signals"]:
                tdf = pd.DataFrame(stats["top_annotated_signals"])
                tdf["signal_label"] = tdf["device_name"] + " - " + tdf["event_type"]
                fig2 = px.bar(tdf, x="signal_label", y="annotation_count",
                              color="annotation_count",
                              title="批注最多的信号",
                              labels={"signal_label": "信号", "annotation_count": "批注数量"})
                fig2.update_layout(xaxis_tickangle=-45)
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("暂无批注数据")

        st.divider()

        st.subheader("📈 报告状态分布")
        if stats.get("status_distribution"):
            sdf = pd.DataFrame([
                {"状态": k, "数量": v} for k, v in stats["status_distribution"].items()
            ])
            fig3 = px.pie(sdf, values="数量", names="状态", hole=0.4,
                          color_discrete_map={"草稿": "#95a5a6", "审阅中": "#3498db", "已批准": "#27ae60", "已退回": "#e74c3c", "已超时": "#8e44ad"})
            st.plotly_chart(fig3, use_container_width=True)

    with tab3:
        st.session_state.review_page_tab = "版本对比"
        versions = get_all_report_versions()
        if len(versions) < 2:
            st.info("至少需要2个版本才能进行对比")
        else:
            col_c1, col_c2 = st.columns(2)
            version_options = [f"v{v['version_number']} (ID: {v['id']}) - {v['status']}" for v in versions]
            version_map = {f"v{v['version_number']} (ID: {v['id']}) - {v['status']}": v["id"] for v in versions}
            with col_c1:
                v1_sel = st.selectbox("选择版本1", version_options, key="v1_compare_review")
            with col_c2:
                v2_sel = st.selectbox("选择版本2", version_options, key="v2_compare_review")
            if st.button("开始对比", key="compare_btn_review", type="primary"):
                v1_id = version_map[v1_sel]
                v2_id = version_map[v2_sel]
                changes = compare_report_versions_enhanced(v1_id, v2_id)
                if not changes:
                    st.info("两个版本之间没有信号强度变化")
                else:
                    st.success(f"发现 {len(changes)} 个信号变化")
                    change_type_icons = {
                        "新增": "➕", "消失": "➖", "升级": "⬆️", "降级": "⬇️"
                    }
                    change_type_colors = {
                        "新增": "#1f77b4", "消失": "#7f7f7f", "升级": "#d62728", "降级": "#2ca02c"
                    }
                    
                    metric_cols = st.columns(4)
                    metric_cols[0].markdown("**🔴 PRR变化**")
                    metric_cols[1].markdown("**🔴 ROR变化**")
                    metric_cols[2].markdown("**🔴 IC变化**")
                    metric_cols[3].markdown("**🔴 EBGM变化**")
                    
                    for c in changes:
                        with st.container(border=True):
                            col1, col2, col3 = st.columns([2, 1, 2])
                            with col1:
                                st.markdown(f"**{c['device_name']}** - {c['event_type']}")
                            with col2:
                                icon = change_type_icons.get(c['change_type'], "")
                                color = change_type_colors.get(c['change_type'], "#333")
                                st.markdown(f"<span style='color:{color};font-weight:bold;font-size:18px;'>{icon} {c['change_type']}</span>", unsafe_allow_html=True)
                            with col3:
                                old_s = c['old_strength'] or "无"
                                new_s = c['new_strength'] or "无"
                                strength_color = {"强信号": "#d62728", "中等信号": "#ff7f0e", "弱信号": "#2ca02c", "无信号": "#7f7f7f", "无": "#999"}
                                oc = strength_color.get(old_s, "#999")
                                nc = strength_color.get(new_s, "#999")
                                st.markdown(f"<span style='color:{oc};'>{old_s}</span> → <span style='color:{nc};'>{new_s}</span>", unsafe_allow_html=True)
                            
                            metric_row = st.columns(4)
                            for i, metric in enumerate(["prr_change", "ror_change", "ic_change", "ebgm_change"]):
                                change = c.get(metric)
                                metric_name = {"prr_change": "PRR", "ror_change": "ROR", "ic_change": "IC", "ebgm_change": "EBGM"}[metric]
                                if change:
                                    arrow = "🔴 ↑" if change["direction"] == "up" else "🟢 ↓" if change["direction"] == "down" else "➡️"
                                    diff_text = f"+{change['diff']:.3f}" if change["diff"] > 0 else f"{change['diff']:.3f}"
                                    metric_row[i].markdown(f"{arrow} **{metric_name}**: {change['old']:.3f} → {change['new']:.3f} ({diff_text})")
                                else:
                                    metric_row[i].markdown(f"➡️ **{metric_name}**: N/A")
                            
                            if c.get("trend_data") and len(c["trend_data"]) >= 2:
                                with st.expander("📈 变化趋势迷你图", expanded=False):
                                    trend_df = pd.DataFrame(c["trend_data"])
                                    fig = go.Figure()
                                    fig.add_trace(go.Scatter(
                                        x=trend_df["version_number"].astype(str),
                                        y=trend_df["strength_value"],
                                        mode="lines+markers",
                                        name="信号强度",
                                        line=dict(color="#1f77b4", width=2),
                                        marker=dict(size=8)
                                    ))
                                    fig.update_layout(
                                        title=f"{c['device_name']} - {c['event_type']} 信号强度趋势",
                                        xaxis_title="版本号",
                                        yaxis_title="信号强度",
                                        yaxis=dict(
                                            tickvals=[0, 1, 2, 3],
                                            ticktext=["无信号", "弱信号", "中等信号", "强信号"]
                                        ),
                                        height=250,
                                        margin=dict(l=0, r=0, t=40, b=0)
                                    )
                                    st.plotly_chart(fig, use_container_width=True)
                                    
                                    if "prr_value" in trend_df.columns:
                                        prr_vals = trend_df.dropna(subset=["prr_value"])
                                        if len(prr_vals) >= 2:
                                            fig2 = go.Figure()
                                            fig2.add_trace(go.Scatter(
                                                x=prr_vals["version_number"].astype(str),
                                                y=prr_vals["prr_value"],
                                                mode="lines+markers",
                                                name="PRR值",
                                                line=dict(color="#d62728", width=2),
                                                marker=dict(size=8)
                                            ))
                                            fig2.update_layout(
                                                title="PRR值趋势",
                                                xaxis_title="版本号",
                                                yaxis_title="PRR值",
                                                height=200,
                                                margin=dict(l=0, r=0, t=40, b=0)
                                            )
                                            st.plotly_chart(fig2, use_container_width=True)


def page_report_detail():
    report_id = st.session_state.selected_report_for_detail
    report = get_report_version(report_id)
    if not report:
        st.error("报告不存在")
        return

    st.title(f"📄 报告详情 - 版本 v{report['version_number']}")

    col_back, col_info, col_export = st.columns([1, 3, 1])
    with col_back:
        if st.button("← 返回看板", type="primary", use_container_width=True):
            st.session_state.selected_report_for_detail = None
            st.rerun()
    with col_export:
        if st.button("📥 导出审阅意见", type="secondary", use_container_width=True):
            from datetime import datetime
            csv_content = export_review_comments(report_id)
            today = datetime.now().strftime("%Y%m%d")
            filename = f"审阅意见_v{report['version_number']}_{today}.csv"
            st.download_button(
                label="💾 下载CSV文件",
                data=csv_content,
                file_name=filename,
                mime="text/csv",
                use_container_width=True,
                key="download_review_comments"
            )

    status_colors = {"草稿": "#95a5a6", "审阅中": "#3498db", "已批准": "#27ae60", "已退回": "#e74c3c", "已超时": "#8e44ad"}
    sc = status_colors.get(report["status"], "#333")

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("版本号", f"v{report['version_number']}")
    with col2:
        st.metric("状态", f"<span style='color:{sc};'>{report['status']}</span>", help=None)
    with col3:
        st.metric("生成时间", str(report.get("generation_time", "N/A"))[:19])
    with col4:
        st.metric("信号数量", report.get("signal_count", len(report.get("signals", []))))
    with col5:
        if report.get("deadline"):
            remaining, seconds = get_remaining_time(report_id)
            if seconds and seconds < 24 * 3600 and seconds > 0:
                st.metric("截止时间", f"<span style='color:#e74c3c;'>{report['deadline'][:19]}</span>", help="即将超时")
            else:
                st.metric("截止时间", report['deadline'][:19])

    if report.get("submitter"):
        st.caption(f"👤 提交人: {report['submitter']} | 📅 提交时间: {report.get('submitted_at', 'N/A')}")

    if report.get("reject_reason"):
        st.error(f"❌ 退回理由: {report['reject_reason']}")

    st.divider()

    col_sig, col_annot = st.columns([3, 2])

    with col_sig:
        st.subheader(f"📊 信号列表（共 {len(report.get('signals', []))} 条）")

        annot_counts = get_annotation_count_by_signal(report_id)

        signals = report.get("signals", [])
        if signals:
            strength_filter = st.multiselect(
                "筛选信号强度",
                ["强信号", "中等信号", "弱信号", "无信号"],
                default=["强信号", "中等信号", "弱信号"]
            )
            filtered = [s for s in signals if s.get("signal_strength") in strength_filter]

            for s in filtered:
                signal_id = s["id"]
                annot_count = annot_counts.get(signal_id, 0)
                strength_color = {"强信号": "#d62728", "中等信号": "#ff7f0e", "弱信号": "#2ca02c", "无信号": "#7f7f7f"}
                sc = strength_color.get(s.get("signal_strength", ""), "#7f7f7f")

                with st.container(border=True):
                    col_info, col_metrics = st.columns([3, 2])
                    with col_info:
                        annot_badge = f" <span style='background-color:#e74c3c;color:white;padding:2px 8px;border-radius:10px;font-size:11px;margin-left:8px;'>💬 {annot_count}</span>" if annot_count > 0 else ""
                        st.markdown(f"**{s['device_name']}** - {s['event_type']}{annot_badge}", unsafe_allow_html=True)
                        st.markdown(f"<span style='color:{sc};font-weight:bold;'>{s.get('signal_strength', 'N/A')}</span>", unsafe_allow_html=True)
                        st.caption(f"📊 报告数: {s.get('report_count', 0)} | 信号ID: {signal_id}")
                    with col_metrics:
                        col_m1, col_m2 = st.columns(2)
                        with col_m1:
                            st.metric("PRR", f"{s['prr_value']:.3f}" if s.get('prr_value') else "N/A")
                        with col_m2:
                            st.metric("ROR", f"{s['ror_value']:.3f}" if s.get('ror_value') else "N/A")

                    if st.button("查看批注", key=f"view_annot_{signal_id}", use_container_width=True):
                        st.session_state[f"active_signal_{report_id}"] = signal_id
                        st.rerun()

                    if st.session_state.current_reviewer and st.session_state.get(f"show_add_annot_{signal_id}"):
                        st.divider()
                        st.markdown("**✏️ 添加批注**")
                        
                        templates = get_annotation_templates(st.session_state.current_reviewer["id"])
                        if templates:
                            template_options = ["手动输入"] + [f"{t['name']} ({'公共' if t['is_public'] else '个人'})" for t in templates]
                            selected_template = st.selectbox(
                                "选择批注模板",
                                template_options,
                                key=f"template_select_{signal_id}"
                            )
                            
                            if selected_template != "手动输入":
                                template_idx = template_options.index(selected_template) - 1
                                selected_t = templates[template_idx]
                                st.info(f"💡 模板内容: {selected_t['content']}")
                                if st.button("使用此模板", key=f"use_template_{signal_id}", use_container_width=True):
                                    st.session_state[f"template_content_{signal_id}"] = selected_t["content"]
                                    st.session_state[f"template_type_{signal_id}"] = selected_t["annotation_type"]
                                    st.session_state[f"template_priority_{signal_id}"] = selected_t["priority"]
                                    st.rerun()
                        
                        col_t1, col_t2 = st.columns(2)
                        with col_t1:
                            annot_type = st.selectbox(
                                "批注类型",
                                ANNOTATION_TYPES,
                                index=ANNOTATION_TYPES.index(st.session_state.get(f"template_type_{signal_id}", "疑问")),
                                key=f"annot_type_{signal_id}"
                            )
                        with col_t2:
                            annot_priority = st.selectbox(
                                "优先级",
                                ANNOTATION_PRIORITIES,
                                index=ANNOTATION_PRIORITIES.index(st.session_state.get(f"template_priority_{signal_id}", "普通")),
                                key=f"annot_priority_{signal_id}"
                            )
                        
                        annot_content = st.text_area(
                            "批注内容",
                            value=st.session_state.get(f"template_content_{signal_id}", ""),
                            key=f"annot_content_{signal_id}",
                            height=80,
                            placeholder="请输入批注内容..."
                        )
                        col_sb, col_cb = st.columns(2)
                        with col_sb:
                            if st.button("提交批注", key=f"submit_annot_{signal_id}", type="primary", use_container_width=True):
                                if annot_content.strip():
                                    add_annotation(
                                        report_id,
                                        signal_id,
                                        annot_content.strip(),
                                        annot_type,
                                        st.session_state.current_reviewer["id"],
                                        annot_priority
                                    )
                                    st.success("✅ 批注已添加")
                                    st.session_state[f"show_add_annot_{signal_id}"] = False
                                    st.session_state[f"template_content_{signal_id}"] = ""
                                    st.session_state[f"template_type_{signal_id}"] = "疑问"
                                    st.session_state[f"template_priority_{signal_id}"] = "普通"
                                    st.rerun()
                                else:
                                    st.error("批注内容不能为空")
                        with col_cb:
                            if st.button("取消", key=f"cancel_annot_{signal_id}", use_container_width=True):
                                st.session_state[f"show_add_annot_{signal_id}"] = False
                                st.session_state[f"template_content_{signal_id}"] = ""
                                st.rerun()
                    elif st.session_state.current_reviewer:
                        if st.button("➕ 添加批注", key=f"add_annot_btn_{signal_id}", use_container_width=True):
                            st.session_state[f"show_add_annot_{signal_id}"] = True
                            st.rerun()

    with col_annot:
        st.subheader("💬 批注面板")

        if not st.session_state.current_reviewer:
            st.warning("请先在看板页面选择审阅人身份，才能添加批注")

        active_signal = st.session_state.get(f"active_signal_{report_id}")

        all_annotations = get_annotations(report_id)
        if not all_annotations:
            st.info("暂无批注")
        else:
            if active_signal:
                st.markdown(f"**📌 当前信号: {active_signal}**")
                signal_annotations = [a for a in all_annotations if a["signal_id"] == active_signal]
                if signal_annotations:
                    _display_annotations(signal_annotations, report_id, active_signal)
                else:
                    st.info("该信号暂无批注")
            else:
                signal_groups = {}
                for a in all_annotations:
                    sid = a["signal_id"]
                    if sid not in signal_groups:
                        signal_groups[sid] = []
                    signal_groups[sid].append(a)

                for sid, anns in signal_groups.items():
                    signal_info = next((s for s in signals if s["id"] == sid), None)
                    signal_label = f"{signal_info['device_name']} - {signal_info['event_type']}" if signal_info else f"信号 {sid}"

                    with st.expander(f"📌 {signal_label} ({len(anns)}条批注)", expanded=False):
                        _display_annotations(anns, report_id, sid)

    st.divider()
    st.subheader("📋 审阅历史")
    history = get_review_history(report_id)
    if history:
        hdf = pd.DataFrame(history)
        display_cols = ["created_at", "reviewer_name", "action", "comments"]
        existing = [c for c in display_cols if c in hdf.columns]
        hdf_display = hdf[existing].copy()
        hdf_display.columns = ["操作时间", "操作人", "操作", "备注"]
        st.dataframe(hdf_display, use_container_width=True)
    else:
        st.info("暂无审阅历史")

    st.divider()
    st.subheader("👥 审阅任务分配")
    assignments = get_report_assignments(report_id)
    if assignments:
        adf = pd.DataFrame(assignments)
        display_cols = ["name", "role", "email", "decision", "comments", "assigned_at", "completed_at"]
        existing = [c for c in display_cols if c in adf.columns]
        adf_display = adf[existing].copy()
        adf_display.columns = ["姓名", "角色", "邮箱", "决策", "意见", "分配时间", "完成时间"]
        st.dataframe(adf_display, use_container_width=True)
    else:
        st.info("暂无审阅分配")


def _display_annotations(annotations, report_id, signal_id):
    type_icons = {"疑问": "❓", "建议": "💡", "反对": "🚫", "确认": "✅"}
    type_colors = {"疑问": "#3498db", "建议": "#27ae60", "反对": "#e74c3c", "确认": "#9b59b6"}
    priority_colors = {"紧急": "#e74c3c", "普通": "#95a5a6", "低": "#7f8c8d"}
    priority_labels = {"紧急": "🔴 紧急", "普通": "⚪ 普通", "低": "🔵 低"}

    for ann in annotations:
        is_resolved = ann["status"] == "已解决"
        priority = ann.get("priority", "普通")
        is_urgent = priority == "紧急" and not is_resolved
        
        border_style = "border: 2px solid #e74c3c;" if is_urgent else ""
        
        with st.container(border=True):
            if is_urgent:
                st.markdown(
                    f"<div style='background-color:#fff5f5;padding:8px;border-radius:4px;margin-bottom:8px;'>"
                    f"<span style='color:#e74c3c;font-weight:bold;'>🔴 紧急批注</span></div>",
                    unsafe_allow_html=True
                )
            if is_resolved:
                st.caption("✅ 已解决")

            col_h, col_s = st.columns([4, 1])
            with col_h:
                icon = type_icons.get(ann["annotation_type"], "")
                tc = type_colors.get(ann["annotation_type"], "#333")
                pc = priority_colors.get(priority, "#333")
                pl = priority_labels.get(priority, "普通")
                st.markdown(
                    f"<span style='color:{tc};font-weight:bold;'>{icon} {ann['annotation_type']}</span> "
                    f"<span style='color:{pc};font-size:12px;margin-left:8px;'>{pl}</span> "
                    f"<br>by **{ann['author_name']}** ({ann['author_role']}) at {ann['created_at'][:19]}",
                    unsafe_allow_html=True
                )
            with col_s:
                if not is_resolved and st.session_state.current_reviewer:
                    if st.button("标记已解决", key=f"resolve_{ann['id']}", use_container_width=True):
                        set_annotation_status(ann["id"], "已解决")
                        st.rerun()
                elif is_resolved and st.session_state.current_reviewer:
                    if st.button("重新开放", key=f"reopen_{ann['id']}", use_container_width=True):
                        set_annotation_status(ann["id"], "开放")
                        st.rerun()

            st.markdown(ann["content"])

            if ann.get("replies"):
                with st.container():
                    for reply in ann["replies"]:
                        st.markdown(
                            f"<div style='margin-left:20px;padding:8px;background-color:#f8f9fa;border-radius:4px;margin-bottom:4px;'>"
                            f"<b>{reply['author_name']}</b> ({reply['author_role']}) "
                            f"<span style='color:#999;font-size:12px;'>{reply['created_at'][:19]}</span><br>"
                            f"{reply['content']}</div>",
                            unsafe_allow_html=True
                        )

            if st.session_state.current_reviewer and not is_resolved:
                reply_key = f"reply_input_{ann['id']}"
                show_reply = st.session_state.get(f"show_reply_{ann['id']}", False)
                if not show_reply:
                    if st.button("↩️ 回复", key=f"reply_btn_{ann['id']}"):
                        st.session_state[f"show_reply_{ann['id']}"] = True
                        st.rerun()
                else:
                    reply_content = st.text_area(
                        "回复内容",
                        key=reply_key,
                        height=60,
                        placeholder="输入回复..."
                    )
                    col_sr, col_cr = st.columns(2)
                    with col_sr:
                        if st.button("发送回复", key=f"send_reply_{ann['id']}", type="primary", use_container_width=True):
                            if reply_content.strip():
                                add_annotation_reply(ann["id"], reply_content.strip(), st.session_state.current_reviewer["id"])
                                st.session_state[f"show_reply_{ann['id']}"] = False
                                st.rerun()
                    with col_cr:
                        if st.button("取消", key=f"cancel_reply_{ann['id']}", use_container_width=True):
                            st.session_state[f"show_reply_{ann['id']}"] = False
                            st.rerun()


def page_reviewer_management():
    st.title("👤 审阅人管理")

    col_cr, _ = st.columns([3, 1])
    with col_cr:
        current_reviewer_name = st.selectbox(
            "选择当前审阅人身份",
            ["请选择..."] + [r["name"] for r in get_all_reviewers()],
            key="mgmt_reviewer_selector"
        )
        if current_reviewer_name != "请选择...":
            st.session_state.current_reviewer = get_reviewer_by_name(current_reviewer_name)
        else:
            st.session_state.current_reviewer = None

    if st.session_state.current_reviewer:
        r = st.session_state.current_reviewer
        role_color = {"初审员": "#2ca02c", "高级审阅员": "#ff7f0e", "主管": "#d62728"}
        rc = role_color.get(r["role"], "#333")
        st.success(f"✅ 当前身份: <span style='color:{rc};font-weight:bold;'>{r['name']}</span> ({r['role']})", unsafe_allow_html=True)

    st.divider()

    tab1, tab2, tab3, tab4 = st.tabs(["📋 审阅人列表", "➕ 添加审阅人", "📝 我的待办", "📑 批注模板管理"])

    with tab1:
        reviewers = get_all_reviewers()
        if not reviewers:
            st.info("暂无审阅人，请先添加")
        else:
            rdf = pd.DataFrame(reviewers)
            display_cols = ["id", "name", "role", "email", "created_at"]
            existing = [c for c in display_cols if c in rdf.columns]
            rdf_display = rdf[existing].copy()
            rdf_display.columns = ["ID", "姓名", "角色", "邮箱", "创建时间"]
            st.dataframe(rdf_display, use_container_width=True, hide_index=True)

            st.divider()
            st.subheader("✏️ 编辑/删除")
            selected_id = st.selectbox(
                "选择审阅人",
                ["请选择..."] + [f"{r['id']} - {r['name']} ({r['role']})" for r in reviewers]
            )
            if selected_id != "请选择...":
                rid = int(selected_id.split(" - ")[0])
                reviewer = next((r for r in reviewers if r["id"] == rid), None)
                if reviewer:
                    col_e1, col_e2 = st.columns(2)
                    with col_e1:
                        edit_name = st.text_input("姓名", value=reviewer["name"], key="edit_name")
                        edit_role = st.selectbox(
                            "角色",
                            REVIEWER_ROLES,
                            index=REVIEWER_ROLES.index(reviewer["role"]) if reviewer["role"] in REVIEWER_ROLES else 0,
                            key="edit_role"
                        )
                    with col_e2:
                        edit_email = st.text_input("邮箱", value=reviewer["email"] or "", key="edit_email")

                    col_sv, col_dl = st.columns(2)
                    with col_sv:
                        if st.button("保存修改", type="primary", use_container_width=True, key="save_edit"):
                            try:
                                update_reviewer(rid, name=edit_name, role=edit_role, email=edit_email)
                                st.success("✅ 修改成功")
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))
                    with col_dl:
                        if st.button("删除", use_container_width=True, key="delete_reviewer"):
                            try:
                                delete_reviewer(rid)
                                st.success("✅ 删除成功")
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))

    with tab2:
        st.subheader("添加新审阅人")
        with st.form("add_reviewer_form"):
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                new_name = st.text_input("姓名*", key="new_name")
                new_role = st.selectbox("角色*", REVIEWER_ROLES, key="new_role")
            with col_f2:
                new_email = st.text_input("邮箱", key="new_email")

            submitted = st.form_submit_button("添加", type="primary", use_container_width=True)
            if submitted:
                if not new_name.strip():
                    st.error("姓名不能为空")
                else:
                    try:
                        add_reviewer(new_name.strip(), new_role, new_email.strip() or None)
                        st.success("✅ 添加成功")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

    with tab3:
        st.session_state.review_page_tab = "我的待办"
        if not st.session_state.current_reviewer:
            st.warning("请先选择当前审阅人身份")
        else:
            st.subheader(f"📝 {st.session_state.current_reviewer['name']} 的待办事项")
            todo_list = get_my_todo_list(st.session_state.current_reviewer["id"])
            
            if not todo_list:
                st.info("暂无待办事项")
            else:
                priority_colors = {"紧急": "#e74c3c", "普通": "#95a5a6", "低": "#7f8c8d"}
                
                for idx, item in enumerate(todo_list):
                    pc = priority_colors.get(item["priority"], "#333")
                    with st.container(border=True):
                        col_type, col_info, col_action = st.columns([1, 4, 2])
                        with col_type:
                            if item["type"] == "review":
                                st.markdown(f"<div style='text-align:center;padding:8px;background-color:#e8f4fd;border-radius:4px;'>📋<br><b>审阅任务</b></div>", unsafe_allow_html=True)
                            else:
                                st.markdown(f"<div style='text-align:center;padding:8px;background-color:#fdecea;border-radius:4px;'>💬<br><b>紧急批注</b></div>", unsafe_allow_html=True)
                        
                        with col_info:
                            if item["priority"] == "紧急":
                                st.markdown(f"<span style='color:{pc};font-weight:bold;'>🔴 {item['priority']}</span>", unsafe_allow_html=True)
                            else:
                                st.markdown(f"<span style='color:{pc};'>⚪ {item['priority']}</span>", unsafe_allow_html=True)
                            
                            st.markdown(f"**版本 v{item['version_number']}**")
                            if item.get("device_name") and item.get("event_type"):
                                st.caption(f"📌 {item['device_name']} - {item['event_type']}")
                            
                            if item["type"] == "review":
                                if item.get("remaining_time"):
                                    st.caption(f"⏰ {item['remaining_time']}")
                                st.caption(f"📊 状态: {item['report_status']}")
                            else:
                                st.caption(f"💬 {item['annotation_type']} by {item['author_name']}")
                                if len(item.get("content", "")) > 50:
                                    st.caption(f"📝 {item['content'][:50]}...")
                                else:
                                    st.caption(f"📝 {item.get('content', '')}")
                        
                        with col_action:
                            if item["type"] == "review":
                                if st.button("前往审阅", key=f"goto_review_{idx}", use_container_width=True, type="primary"):
                                    st.session_state.selected_report_for_detail = item["report_version_id"]
                                    st.rerun()
                            else:
                                if st.button("查看批注", key=f"goto_annot_{idx}", use_container_width=True, type="primary"):
                                    st.session_state.selected_report_for_detail = item["report_version_id"]
                                    st.session_state[f"active_signal_{item['report_version_id']}"] = item["signal_id"]
                                    st.rerun()

    with tab4:
        st.session_state.review_page_tab = "批注模板管理"
        if not st.session_state.current_reviewer:
            st.warning("请先选择当前审阅人身份")
        else:
            col_add, _ = st.columns([1, 3])
            with col_add:
                if st.button("➕ 新建模板", type="primary", use_container_width=True):
                    st.session_state["show_template_form"] = True
                    st.rerun()
            
            if st.session_state.get("show_template_form"):
                with st.expander("📝 新建批注模板", expanded=True):
                    with st.form("template_form"):
                        col_t1, col_t2 = st.columns(2)
                        with col_t1:
                            template_name = st.text_input("模板名称*", key="template_name")
                            template_type = st.selectbox("批注类型", ANNOTATION_TYPES, key="template_type")
                        with col_t2:
                            template_priority = st.selectbox("优先级", ANNOTATION_PRIORITIES, key="template_priority")
                            is_public = st.checkbox("设为公共模板", value=False, key="template_is_public")
                        
                        template_content = st.text_area("批注内容*", height=80, key="template_content")
                        
                        col_sub, col_can = st.columns(2)
                        with col_sub:
                            submit_template = st.form_submit_button("保存模板", type="primary", use_container_width=True)
                        with col_can:
                            cancel_template = st.form_submit_button("取消", use_container_width=True)
                        
                        if submit_template:
                            if not template_name.strip() or not template_content.strip():
                                st.error("模板名称和内容不能为空")
                            else:
                                try:
                                    create_annotation_template(
                                        template_name.strip(),
                                        template_content.strip(),
                                        template_type,
                                        template_priority,
                                        is_public,
                                        st.session_state.current_reviewer["id"]
                                    )
                                    st.success("✅ 模板创建成功")
                                    st.session_state["show_template_form"] = False
                                    st.rerun()
                                except Exception as e:
                                    st.error(str(e))
                        if cancel_template:
                            st.session_state["show_template_form"] = False
                            st.rerun()
            
            st.divider()
            templates = get_annotation_templates(st.session_state.current_reviewer["id"])
            if not templates:
                st.info("暂无批注模板")
            else:
                public_templates = [t for t in templates if t["is_public"]]
                personal_templates = [t for t in templates if not t["is_public"] and t["creator_id"] == st.session_state.current_reviewer["id"]]
                
                if public_templates:
                    st.subheader("🌐 公共模板")
                    for t in public_templates:
                        with st.container(border=True):
                            col_info, col_actions = st.columns([4, 1])
                            with col_info:
                                st.markdown(f"**{t['name']}**")
                                st.caption(f"类型: {t['annotation_type']} | 优先级: {t['priority']} | 创建者: {t['creator_name']}")
                                st.markdown(f"📝 {t['content']}")
                            with col_actions:
                                st.caption("公共模板")
                
                if personal_templates:
                    st.subheader("👤 个人模板")
                    for t in personal_templates:
                        with st.container(border=True):
                            col_info, col_actions = st.columns([4, 1])
                            with col_info:
                                st.markdown(f"**{t['name']}**")
                                st.caption(f"类型: {t['annotation_type']} | 优先级: {t['priority']}")
                                st.markdown(f"📝 {t['content']}")
                            with col_actions:
                                if st.button("编辑", key=f"edit_template_{t['id']}", use_container_width=True):
                                    st.session_state[f"editing_template_{t['id']}"] = True
                                    st.rerun()
                                if st.button("删除", key=f"delete_template_{t['id']}", use_container_width=True):
                                    try:
                                        delete_annotation_template(t["id"])
                                        st.success("✅ 模板已删除")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(str(e))
                            
                            if st.session_state.get(f"editing_template_{t['id']}"):
                                with st.expander("编辑模板", expanded=True):
                                    with st.form(f"edit_form_{t['id']}"):
                                        col_e1, col_e2 = st.columns(2)
                                        with col_e1:
                                            edit_tname = st.text_input("模板名称", value=t["name"], key=f"edit_tname_{t['id']}")
                                            edit_ttype = st.selectbox("批注类型", ANNOTATION_TYPES, 
                                                                       index=ANNOTATION_TYPES.index(t["annotation_type"]), 
                                                                       key=f"edit_ttype_{t['id']}")
                                        with col_e2:
                                            edit_tprio = st.selectbox("优先级", ANNOTATION_PRIORITIES,
                                                                       index=ANNOTATION_PRIORITIES.index(t["priority"]),
                                                                       key=f"edit_tprio_{t['id']}")
                                            edit_tpublic = st.checkbox("设为公共模板", value=bool(t["is_public"]),
                                                                        key=f"edit_tpublic_{t['id']}")
                                        
                                        edit_tcontent = st.text_area("批注内容", value=t["content"], height=80,
                                                                      key=f"edit_tcontent_{t['id']}")
                                        
                                        col_se, col_ce = st.columns(2)
                                        with col_se:
                                            save_edit = st.form_submit_button("保存修改", type="primary", use_container_width=True)
                                        with col_ce:
                                            cancel_edit = st.form_submit_button("取消", use_container_width=True)
                                        
                                        if save_edit:
                                            if not edit_tname.strip() or not edit_tcontent.strip():
                                                st.error("模板名称和内容不能为空")
                                            else:
                                                try:
                                                    update_annotation_template(
                                                        t["id"],
                                                        name=edit_tname.strip(),
                                                        content=edit_tcontent.strip(),
                                                        annotation_type=edit_ttype,
                                                        priority=edit_tprio,
                                                        is_public=edit_tpublic
                                                    )
                                                    st.success("✅ 模板已更新")
                                                    st.session_state[f"editing_template_{t['id']}"] = False
                                                    st.rerun()
                                                except Exception as e:
                                                    st.error(str(e))
                                        if cancel_edit:
                                            st.session_state[f"editing_template_{t['id']}"] = False
                                            st.rerun()

    st.divider()
    st.info("💡 **角色说明**：\n\n- **初审员**：批准权重为1\n- **高级审阅员**：批准权重为2（相当于2个初审员）\n- **主管**：直接通过，无需其他人批准\n\n**审批规则**：\n- 任一审阅人退回 → 报告立即退回\n- 主管批准 → 报告立即通过\n- 批准权重总和 >= max(审阅人数, 2) → 报告通过")


if page == "🏠 数据概览":
    page_overview()
elif page == "📥 数据导入":
    page_import()
elif page == "🔍 数据浏览":
    page_browse()
elif page == "📊 信号检测":
    page_detection()
elif page == "🔥 关联矩阵":
    page_matrix()
elif page == "📈 时间趋势":
    page_time_trend()
elif page == "👥 亚组分析":
    page_subgroup()
elif page == "🔄 同类对比":
    page_similar()
elif page == "📋 信号看板":
    page_kanban()
elif page == "⚙️ 检测参数配置":
    page_config()
elif page == "📄 报告导出":
    page_export()
elif page == "📝 报告审阅":
    if st.session_state.selected_report_for_detail is not None:
        page_report_detail()
    else:
        page_review_kanban()
elif page == "👤 审阅人管理":
    page_reviewer_management()
