import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import os
import tempfile

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

st.set_page_config(page_title="医疗器械不良事件信号检测平台", layout="wide", page_icon="🔬")

init_db()

if "signals_df" not in st.session_state:
    st.session_state.signals_df = load_signals()
if "correction_method" not in st.session_state:
    st.session_state.correction_method = "fdr"

page = st.sidebar.selectbox("导航", [
    "🏠 数据概览",
    "📥 数据导入",
    "🔍 数据浏览",
    "📊 信号检测",
    "🔥 关联矩阵",
    "📈 时间趋势",
    "👥 亚组分析",
    "🔄 同类对比",
    "📋 信号看板",
    "📄 报告导出",
])


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
                result_df = run_signal_detection(df)
                if not result_df.empty:
                    result_df = apply_corrections(result_df)
                    save_signals(result_df)
                    st.session_state.signals_df = result_df
                    init_workflow_for_signals()
                st.success("信号检测完成！")
                st.rerun()

    with col1:
        sdf = st.session_state.signals_df
        if sdf.empty:
            st.info("尚未运行信号检测，请点击右侧按钮运行")
            return

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

    if st.button("生成PDF报告", type="primary"):
        with st.spinner("正在生成PDF报告..."):
            try:
                pdf_path = generate_pdf_report()
                with open(pdf_path, "rb") as f:
                    st.download_button(
                        label="📥 下载PDF报告",
                        data=f.read(),
                        file_name="adverse_event_signal_report.pdf",
                        mime="application/pdf",
                    )
                st.success("PDF报告生成成功！")
            except Exception as e:
                st.error(f"生成PDF失败: {e}")


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
elif page == "📄 报告导出":
    page_export()
