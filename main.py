# main.py
import io
import re
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st


# ───────────────────────── 초기화 ─────────────────────────
st.set_page_config(page_title="극지식물 생육 차이 분석", layout="wide")

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR&display=swap');
html, body, [class*="css"] {
    font-family: 'Noto Sans KR', 'Malgun Gothic', sans-serif;
}
</style>
""",
    unsafe_allow_html=True,
)


# ───────────────────────── CSV 읽기 ─────────────────────────
@st.cache_data
def read_csv_safely(file):
    """utf-8-sig → cp949 순으로 시도, 실패 시 None 반환"""
    data = file.getvalue()
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(io.BytesIO(data), encoding=enc)
        except (UnicodeDecodeError, Exception):
            continue
    return None


def extract_school_name(filename: str) -> str:
    """파일명에서 학교명만 추출: '송도고등학교_환경데이터.csv' → '송도고등학교'"""
    base = filename.split(".")[0] if "." in filename else filename
    for sep in ("_", "-"):
        if sep in base:
            return base.split(sep)[0].strip()
    return base.strip()


def detect_numeric_cols(df: pd.DataFrame, id_col: str | None = None) -> list[str]:
    """개체번호류를 제외한 숫자형 열만 반환"""
    nums = df.select_dtypes(include="number").columns.tolist()
    if id_col and id_col in nums:
        nums.remove(id_col)
    return nums


def parse_time_column(time_series: pd.Series) -> pd.Series:
    """문자열 time 열을 datetime으로 변환, 실패 시 원본 유지"""
    if pd.api.types.is_datetime64_any_dtype(time_series):
        return time_series
    try:
        parsed = pd.to_datetime(time_series, errors="coerce")
        if parsed.notna().sum() > len(time_series) * 0.5:
            return parsed
    except Exception:
        pass
    return time_series


# ───────────────────────── 사이드바 ─────────────────────────
st.sidebar.title("📂 데이터 업로드")

env_file = st.sidebar.file_uploader(
    "환경 데이터 CSV", type="csv", help="예: 송도고등학교_환경데이터.csv"
)
growth_file = st.sidebar.file_uploader(
    "생육 결과 CSV", type="csv", help="예: 송도고등학교_생육결과데이터.csv"
)


if env_file is None and growth_file is None:
    st.info("왼쪽 사이드바에서 우리 학교 CSV 2개를 올려 주세요.")
    st.stop()

env_df = read_csv_safely(env_file) if env_file else None
growth_df = read_csv_safely(growth_file) if growth_file else None

if env_df is None and env_file is not None:
    st.error("환경 데이터 CSV를 읽지 못했습니다. 인코딩(utf-8-sig / cp949)을 확인하거나 다른 파일로 다시 시도해 주세요.")
    env_df = None
if growth_df is None and growth_file is not None:
    st.error("생육 결과 CSV를 읽지 못했습니다. 인코딩을 확인하거나 다른 파일로 다시 시도해 주세요.")
    growth_df = None

# ── 학교명 ──
school_name = "이 학교"
if env_file:
    school_name = extract_school_name(env_file.name)
elif growth_file:
    school_name = extract_school_name(growth_file.name)

st.sidebar.divider()
st.sidebar.subheader(f"🏫 {school_name}")

# 생육 측정 항목 선택 (생육 결과 CSV의 숫자 열 자동 인식)
id_col_guess = None
growth_numeric_cols = []
if growth_df is not None:
    first_col = growth_df.columns[0]
    if growth_df[first_col].dtype in ("int64", "float64", "Int64"):
        if re.search(r"개체|번호|id|plant", first_col, re.IGNORECASE):
            id_col_guess = first_col
    growth_numeric_cols = detect_numeric_cols(growth_df, id_col_guess)

if growth_numeric_cols:
    selected_growth_col = st.sidebar.selectbox(
        "📊 생육 측정 항목 (그래프·통계 대상)",
        options=growth_numeric_cols,
        index=0,
        help="생육 결과 CSV에서 자동 탐지한 숫자 열입니다. 기본값은 첫 번째 측정 항목입니다.",
    )
else:
    selected_growth_col = None
    st.sidebar.warning("생육 결과 CSV에서 숫자 열을 찾지 못했습니다.")

# 날짜 범위 선택 (환경 데이터에 time 열이 있을 때)
env_date_min, env_date_max = None, None
if env_df is not None and "time" in env_df.columns:
    time_parsed = parse_time_column(env_df["time"])
    if pd.api.types.is_datetime64_any_dtype(time_parsed) and time_parsed.notna().any():
        env_date_min = time_parsed.min().date()
        env_date_max = time_parsed.max().date()

date_range = None
if env_date_min is not None and env_date_max is not None:
    date_range = st.sidebar.date_input(
        "📅 환경 데이터 날짜 범위",
        value=(env_date_min, env_date_max),
        min_value=env_date_min,
        max_value=env_date_max,
        help="센서 측정 기간 중 분석할 기간을 선택합니다.",
    )

st.sidebar.divider()
st.sidebar.caption("CSV 파일은 utf-8-sig / cp949 인코딩을 자동 감지해 읽습니다.")
st.sidebar.caption("센서가 측정하지 못한 빈 기간은 분석에서 자동으로 제외됩니다.")


# ───────────────────────── 탭 구조 ─────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(
    ["실험 개요", "환경 변화", "생육 결과", "데이터 다운로드"]
)


# ════════════════════════════════════════════════════
#  탭1 ─ 실험 개요
# ════════════════════════════════════════════════════
with tab1:
    st.header(f"🔬 {school_name} 극지식물 개체별 생육 차이 분석")

    # 가설 카드
    col_h1, col_h2 = st.columns(2)
    with col_h1:
        st.markdown(
            """
<div style="background:#f1f8e9; border-left:4px solid #4CAF50;
            padding:12px 16px; border-radius:0 8px 8px 0;
            font-size:0.92rem; line-height:1.6;">
<strong>가설 1.</strong><br>
같은 스마트팜에서 재배해도 개체별 <strong>생중량 차이</strong>는 클 것이다.
</div>
""",
            unsafe_allow_html=True,
        )
        st.caption(
            "같은 환경이라도 유전적 차이, 미세 위치별 환경 차이로 수확 시 생중량 분포가 넓게 나타날 것으로 예상합니다."
        )
    with col_h2:
        st.markdown(
            """
<div style="background:#fff3e0; border-left:4px solid #FF9800;
            padding:12px 16px; border-radius:0 8px 8px 0;
            font-size:0.92rem; line-height:1.6;">
<strong>가설 2.</strong><br>
잎 수가 많은 개체의 생중량이 더 클 것이다.
</div>
""",
            unsafe_allow_html=True,
        )
        st.caption(
            "잎은 광합성의 주요 기관입니다. 잎 수가 많을수록 총 광합성량이 늘어 생장이 촉진될 것으로 예상합니다."
        )

    st.divider()

    # 요약 카드
    cards = st.columns(4)
    n_growth = len(growth_df) if growth_df is not None else 0
    cards[0].metric("🧪 개체 수", f"{n_growth} 개체", help="생육 결과 CSV 행 수 (1회차 실습 개체 수)")

    if growth_df is not None and selected_growth_col and selected_growth_col in growth_df.columns:
        biomean = growth_df[selected_growth_col].mean()
        cards[1].metric(
            "📊 평균 생중량",
            f"{biomean:.2f} g",
            help=f"선택한 생육 항목 '{selected_growth_col}'의 전체 개체 평균값입니다.",
        )
    else:
        cards[1].metric("📊 평균 생중량", "—", help="생육 결과 CSV 업로드 후 확인 가능")

    if env_df is not None and "temperature" in env_df.columns:
        tmean = env_df["temperature"].mean()
        cards[2].metric("🌡️ 평균 온도", f"{tmean:.1f} °C", help="센서 측정 전체 기간 평균 온도")
    else:
        cards[2].metric("🌡️ 평균 온도", "—", help="환경 데이터 CSV 업로드 후 확인 가능")

    if env_df is not None and "humidity" in env_df.columns:
        hmean = env_df["humidity"].mean()
        cards[3].metric("💧 평균 습도", f"{hmean:.1f} %", help="센서 측정 전체 기간 평균 습도")
    else:
        cards[3].metric("💧 평균 습도", "—", help="환경 데이터 CSV 업로드 후 확인 가능")

    st.divider()

    # 환경 데이터 요약 표 (있는 경우)
    if env_df is not None:
        env_num_cols = detect_numeric_cols(env_df)
        if env_num_cols:
            st.subheader("🌡️ 환경 데이터 요약 통계")
            env_stats = env_df[env_num_cols].agg(["mean", "std", "min", "max"]).T
            env_stats = env_stats.round(2)
            env_stats.columns = ["평균", "표준편차", "최소", "최대"]
            env_stats = env_stats.reset_index().rename(columns={"index": "측정 항목"})
            st.dataframe(env_stats, width="stretch", hide_index=False)
            st.caption(
                "표준편차: 데이터가 평균에서 얼마나 퍼져 있는지 나타내는 값. "
                "표준편차가 작을수록 센서 측정값이 안정적으로 유지되었다는 뜻입니다."
            )

            absent = []
            if "ec" not in env_df.columns and "EC" not in env_df.columns:
                absent.append("EC")
            if "ph" not in env_df.columns and "pH" not in env_df.columns:
                absent.append("pH")
            if absent:
                st.info(f"이 학교 데이터에는 {', '.join(absent)} 측정값이 없습니다.")

    # 생육 결과 요약 표 (있는 경우)
    if growth_df is not None and selected_growth_col and selected_growth_col in growth_df.columns:
        st.subheader(f"🌱 생육 결과 요약 — {selected_growth_col}")
        gnum = detect_numeric_cols(growth_df, id_col_guess)
        if gnum:
            g_stats = growth_df[gnum].agg(["mean", "std", "min", "max"]).T
            g_stats = g_stats.round(2)
            g_stats["CV(%)"] = (g_stats["std"] / g_stats["mean"] * 100).round(1)
            g_stats.columns = ["평균", "표준편차", "최소", "최대", "CV(%)"]
            g_stats = g_stats.reset_index().rename(columns={"index": "측정 항목"})
            st.dataframe(g_stats, width="stretch", hide_index=False)
            st.caption(
                "CV(변동계수): (표준편차 ÷ 평균) × 100. "
                "단위가 다른 측정 항목끼리 상대적 변동 폭을 비교할 때 사용합니다. "
                "CV(%)가 클수록 개체 간 차이가 큽니다."
            )


# ════════════════════════════════════════════════════
#  탭2 ─ 환경 변화
# ════════════════════════════════════════════════════
with tab2:
    st.header(f"🌡️ 환경 변화 — {school_name} 센서 측정 기록")

    if env_df is None:
        st.info("환경 데이터 CSV를 업로드하면 날짜별 온도·습도 그래프와 요약 표가 표시됩니다.")
    else:
        if "time" not in env_df.columns:
            st.warning("환경 데이터 CSV에 'time' 열이 없습니다. 날짜별 그래프 대신 전체 요약 통계만 표시합니다.")
            if detect_numeric_cols(env_df):
                env_num = detect_numeric_cols(env_df)
                env_sum = env_df[env_num].agg(["mean", "std", "min", "max"]).T.round(2)
                env_sum.columns = ["평균", "표준편차", "최소", "최대"]
                env_sum = env_sum.reset_index().rename(columns={"index": "측정 항목"})
                st.dataframe(env_sum, width="stretch", hide_index=False)
            st.stop()

        time_col = parse_time_column(env_df["time"])
        df_env = env_df.copy()

        if pd.api.types.is_datetime64_any_dtype(time_col):
            df_env["_time"] = time_col
            if date_range is not None:
                start, end = date_range
                df_env = df_env[(df_env["_time"].dt.date >= start) & (df_env["_time"].dt.date <= end)]
            available_daily = [c for c in ["temperature", "humidity"] if c in df_env.columns]
        else:
            df_env["_time"] = pd.to_datetime(df_env.index.astype(str), errors="coerce")
            available_daily = [c for c in ["temperature", "humidity"] if c in df_env.columns]

        if available_daily and pd.api.types.is_datetime64_any_dtype(df_env["_time"]):
            df_env["_date"] = df_env["_time"].dt.date
            daily = df_env.groupby("_date")[available_daily].mean().reset_index()
            daily.columns = ["날짜"] + available_daily

            n_env_rows = len(df_env)
            if isinstance(date_range, tuple):
                date_label = f"{date_range[0]} ~ {date_range[1]}"
            else:
                date_label = "전체 기간"
            st.caption(f"표시 기간: {date_label}  |  원본 측정 횟수: {n_env_rows}회")

            n_traces = len(available_daily)
            fig = make_subplots(
                rows=n_traces,
                cols=1,
                shared_xaxes=True,
                vertical_spacing=0.12,
                subplot_titles=[f"{col} 일별 평균" for col in available_daily],
                row_heights=[1 / n_traces] * n_traces,
            )

            colors = ["#1565c0", "#ef6c00", "#2e7d32", "#7b1fa2", "#c62828"]
            for i, col in enumerate(available_daily):
                fig.add_trace(
                    go.Scatter(
                        x=daily["날짜"],
                        y=daily[col],
                        mode="lines+markers",
                        name=col,
                        line=dict(color=colors[i % len(colors)], width=2),
                        marker=dict(size=5, color=colors[i % len(colors)]),
                        hovertemplate=f"<b>{col}</b><br>날짜: %{{x|%Y-%m-%d}}<br>값: %{{y:.2f}}<extra></extra>",
                    ),
                    row=i + 1,
                    col=1,
                )

            fig.update_layout(
                height=360 + 80 * (n_traces - 1),
                showlegend=False,
                font=dict(family="Malgun Gothic, Apple SD Gothic Neo, sans-serif"),
                margin=dict(l=50, r=20, t=40, b=40),
            )

            for r in range(1, n_traces + 1):
                fig.update_xaxes(
                    title_text="날짜",
                    tickformat="%m/%d",
                    gridcolor="rgba(0,0,0,0.06)",
                    tickfont=dict(family="Malgun Gothic, sans-serif"),
                    title_font=dict(family="Malgun Gothic, sans-serif"),
                    row=r,
                    col=1,
                )
                fig.update_yaxes(
                    title_text=available_daily[r - 1],
                    gridcolor="rgba(0,0,0,0.06)",
                    tickfont=dict(family="Malgun Gothic, sans-serif"),
                    title_font=dict(family="Malgun Gothic, sans-serif"),
                    row=r,
                    col=1,
                )

            st.plotly_chart(fig, use_container_width=False, width="stretch")
            st.caption(
                "날짜별 평균 온도와 습도의 변화 추이입니다. "
                "선이 대체로 평탄하면 재배 기간 환경이 안정적이었음을 뜻하고, "
                "진폭이 크면 온도·습도 변동이 컸다는 의미입니다."
            )
        else:
            st.warning("time 열을 날짜로 인식할 수 없어 일별 그래프를 그리지 못했습니다.")

        # 환경 요약 표
        if detect_numeric_cols(env_df):
            st.subheader("📋 환경 데이터 요약 표")
            env_num_all = detect_numeric_cols(env_df)
            env_sum = env_df[env_num_all].agg(["mean", "std", "min", "max", "count"]).T.round(2)
            env_sum.columns = ["평균", "표준편차", "최소", "최대", "측정 횟수"]
            env_sum = env_sum.reset_index().rename(columns={"index": "측정 항목"})
            st.dataframe(env_sum, width="stretch", hide_index=False)
            st.caption(
                "표준편차: 데이터가 평균에서 얼마나 퍼져 있는지를 나타내는 값. "
                "측정 횟수가 적거나 결측 구간이 많으면 표준편차가 실제보다 작게 계산된 것처럼 보일 수 있습니다."
            )

            absent_ecph = []
            if "ec" not in env_df.columns and "EC" not in env_df.columns:
                absent_ecph.append("EC")
            if "ph" not in env_df.columns and "pH" not in env_df.columns:
                absent_ecph.append("pH")
            if absent_ecph:
                st.info(f"이 학교 데이터에는 {', '.join(absent_ecph)} 측정값이 없습니다.")


# ════════════════════════════════════════════════════
#  탭3 ─ 생육 결과
# ════════════════════════════════════════════════════
with tab3:
    st.header(f"🌱 생육 결과 — {school_name} 개체별 생육 차이 분석")

    if growth_df is None:
        st.info("생육 결과 CSV를 업로드하면 생중량 히스토그램·상자그림·산점도·비교 막대그래프가 표시됩니다.")
    else:
        if selected_growth_col is None or selected_growth_col not in growth_df.columns:
            st.warning("생육 측정 항목을 선택하거나 생육 결과 CSV를 다시 업로드해 주세요.")
            st.stop()

        # 개체번호 열 탐지 (통계·그래프에서 제외할 이름표 열)
        id_col = None
        for c in growth_df.columns:
            if re.search(r"개체|번호|id|plant|serial", c, re.IGNORECASE):
                id_col = c
                break
        stat_cols = detect_numeric_cols(growth_df, id_col)
        if not stat_cols:
            st.warning("생육 결과 CSV에서 통계 대상 숫자 열을 찾지 못했습니다.")
            st.stop()

        bio_col = selected_growth_col
        bio_data = growth_df[bio_col].dropna()

        # ── 생중량 히스토그램 + 상자그림 (서브플롯) ──
        fig_hb = make_subplots(
            rows=1,
            cols=2,
            subplot_titles=("생중량 분포 — 히스토그램", "생중량 — 상자그림"),
            horizontal_spacing=0.12,
        )

        fig_hb.add_trace(
            go.Histogram(
                x=bio_data.values,
                nbinsx=max(10, min(30, len(bio_data) // 3)),
                marker_color="rgba(76,175,80,0.7)",
                marker_line_color="#2e7d32",
                marker_line_width=0.8,
                name="개체 수",
                hovertemplate="구간: %{x:.1f} g<br>개체 수: %{y}<extra></extra>",
            ),
            row=1,
            col=1,
        )
        fig_hb.add_trace(
            go.Box(
                y=bio_data.values,
                name="생중량 분포",
                boxmean=True,
                marker_color="rgba(33,150,243,0.6)",
                line_color="#1976d2",
                whiskerwidth=0.8,
                hovertemplate="통계치: %{y:.2f}<extra></extra>",
            ),
            row=1,
            col=2,
        )

        fig_hb.update_layout(
            height=320,
            showlegend=False,
            font=dict(family="Malgun Gothic, Apple SD Gothic Neo, sans-serif"),
            margin=dict(l=50, r=20, t=40, b=40),
        )
        fig_hb.update_xaxes(
            title_text="생중량 (g)",
            gridcolor="rgba(0,0,0,0.06)",
            tickfont=dict(family="Malgun Gothic, sans-serif"),
            title_font=dict(family="Malgun Gothic, sans-serif"),
            row=1,
            col=1,
        )
        fig_hb.update_yaxes(
            title_text="개체 수",
            gridcolor="rgba(0,0,0,0.06)",
            tickfont=dict(family="Malgun Gothic, sans-serif"),
            title_font=dict(family="Malgun Gothic, sans-serif"),
            row=1,
            col=1,
        )
        fig_hb.update_xaxes(
            title_text="생중량 (g)",
            gridcolor="rgba(0,0,0,0.06)",
            tickfont=dict(family="Malgun Gothic, sans-serif"),
            title_font=dict(family="Malgun Gothic, sans-serif"),
            row=1,
            col=2,
        )
        fig_hb.update_yaxes(
            title_text="",
            gridcolor="rgba(0,0,0,0.06)",
            tickfont=dict(family="Malgun Gothic, sans-serif"),
            row=1,
            col=2,
        )

        st.plotly_chart(fig_hb, use_container_width=False, width="stretch")
        st.caption(
            "왼쪽 히스토그램: 개체를 생중량 구간별로 나누어 각 구간에 몇 개체가 있는지 막대로 표시합니다. "
            "오른쪽 상자그림: 중앙값(박스 안쪽 굵은 선), 사분위수(Q1·Q3, 박스 상하단), "
            "수염(최소·최대, 상자 밖 선)의 분포를 보여줍니다. "
            "상자가 넓고 수염이 길수록 개체 간 차이가 크다는 뜻입니다."
        )

        # ── 항목별 평균·표준편차·CV 표 ──
        st.subheader("📊 생육 측정 항목별 기술 통계")
        gs = growth_df[stat_cols].agg(["mean", "std", "min", "max"]).T.round(2)
        gs["CV(%)"] = (gs["std"] / gs["mean"] * 100).round(1)
        gs.columns = ["평균", "표준편차", "최소", "최대", "CV(%)"]
        gs = gs.reset_index().rename(columns={"index": "측정 항목"})
        st.dataframe(gs, width="stretch", hide_index=False)
        n_stat = len(growth_df)
        st.caption(
            f"표본 크기: {n_stat}개체. "
            "표준편차: 데이터가 평균에서 얼마나 퍼져 있는지를 나타내는 값. "
            "CV(변동계수): (표준편차 ÷ 평균) × 100 — 단위가 다른 항목끼리 상대적 변동 폭을 비교할 때 사용합니다. "
            "CV(%)가 클수록 개체 간 차이가 큽니다."
        )

        # ── 잎 수 vs 생중량 산점도 + 상관계수 + np.polyfit 추세선 ──
        leaf_col = None
        for c in growth_df.columns:
            if re.search(r"잎|leaf", c, re.IGNORECASE):
                leaf_col = c
                break

        if leaf_col and leaf_col != bio_col and leaf_col in growth_df.columns:
            leaf_vals = growth_df[leaf_col].dropna()
            bio_vals = growth_df[bio_col].dropna()
            common_idx = leaf_vals.index.intersection(bio_vals.index)
            lx = leaf_vals.loc[common_idx].values.astype(float)
            ly = bio_vals.loc[common_idx].values.astype(float)
            n_scatter = len(lx)

            r_val = float(np.corrcoef(lx, ly)[0, 1])

            slope, intercept = np.polyfit(lx, ly, 1)
            x_line = np.array([lx.min(), lx.max()])
            y_line = slope * x_line + intercept

            fig_sc = go.Figure()
            fig_sc.add_trace(
                go.Scatter(
                    x=lx,
                    y=ly,
                    mode="markers",
                    marker=dict(
                        size=9,
                        color="rgba(255,152,0,0.75)",
                        line=dict(width=0.8, color="#e65100"),
                    ),
                    name=f"개체별 (n={n_scatter})",
                    hovertemplate="잎 수: %{x} 장<br>생중량: %{y:.2f} g<extra></extra>",
                )
            )
            fig_sc.add_trace(
                go.Scatter(
                    x=x_line,
                    y=y_line,
                    mode="lines",
                    line=dict(color="#d32f2f", width=2.5, dash="dash"),
                    name=f"추세선 (기울기={slope:.3f})",
                    hoverinfo="skip",
                )
            )

            fig_sc.update_layout(
                height=380,
                font=dict(family="Malgun Gothic, Apple SD Gothic Neo, sans-serif"),
                margin=dict(l=50, r=20, t=40, b=40),
                legend=dict(
                    font=dict(family="Malgun Gothic, sans-serif"),
                    x=0.02,
                    y=0.98,
                ),
            )
            fig_sc.update_xaxes(
                title_text="잎 수 (장)",
                gridcolor="rgba(0,0,0,0.06)",
                tickfont=dict(family="Malgun Gothic, sans-serif"),
                title_font=dict(family="Malgun Gothic, sans-serif"),
            )
            fig_sc.update_yaxes(
                title_text=f"생중량 ({bio_col})",
                gridcolor="rgba(0,0,0,0.06)",
                tickfont=dict(family="Malgun Gothic, sans-serif"),
                title_font=dict(family="Malgun Gothic, sans-serif"),
            )

            st.plotly_chart(fig_sc, use_container_width=False, width="stretch")

            if abs(r_val) > 0.7:
                sig = "강한 상관관계 (|r| > 0.7)"
            elif abs(r_val) > 0.4:
                sig = "중간 정도 상관관계 (0.4 < |r| ≤ 0.7)"
            else:
                sig = "약한 상관관계 (|r| ≤ 0.4)"

            st.caption(
                f"피어슨 상관계수 r = {r_val:.3f}  ({sig}). "
                "r은 -1에서 1 사이 값으로, 1에 가까울수록 두 값이 함께 증가하는 경향이 강합니다. "
                f"추세선은 np.polyfit으로 계산한 1차 직선(기울기 = {slope:.3f})이며, "
                "최소제곱법으로 데이터 점에 가장 잘 맞는 직선을 찾았습니다. "
                f"산점도 표본 수: {n_scatter}개체."
            )

            # ── Top 25% vs Bottom 25% 비교 막대그래프 ──
            q75 = bio_data.quantile(0.75)
            q25 = bio_data.quantile(0.25)
            top_mask = growth_df[bio_col] >= q75
            bot_mask = growth_df[bio_col] <= q25
            n_top = int(top_mask.sum())
            n_bot = int(bot_mask.sum())

            compare_cols = [c for c in stat_cols if c != bio_col]
            top_means = growth_df.loc[top_mask, compare_cols].mean().round(2)
            bot_means = growth_df.loc[bot_mask, compare_cols].mean().round(2)

            fig_tb = go.Figure()
            fig_tb.add_trace(
                go.Bar(
                    x=compare_cols,
                    y=top_means.values,
                    name=f"Top 25% (n={n_top})",
                    marker_color="rgba(76,175,80,0.75)",
                    marker_line_color="#2e7d32",
                    marker_line_width=0.8,
                    text=[f"{v:.2f}" for v in top_means.values],
                    textposition="outside",
                    hovertemplate="%{x}<br>Top 평균: %{y:.2f}<extra></extra>",
                )
            )
            fig_tb.add_trace(
                go.Bar(
                    x=compare_cols,
                    y=bot_means.values,
                    name=f"Bottom 25% (n={n_bot})",
                    marker_color="rgba(255,87,34,0.75)",
                    marker_line_color="#e64a19",
                    marker_line_width=0.8,
                    text=[f"{v:.2f}" for v in bot_means.values],
                    textposition="outside",
                    hovertemplate="%{x}<br>Bottom 평균: %{y:.2f}<extra></extra>",
                )
            )

            fig_tb.update_layout(
                height=340,
                barmode="group",
                font=dict(family="Malgun Gothic, Apple SD Gothic Neo, sans-serif"),
                margin=dict(l=70, r=20, t=40, b=40),
                legend=dict(
                    font=dict(family="Malgun Gothic, sans-serif"),
                    x=0.02,
                    y=0.98,
                ),
            )
            fig_tb.update_xaxes(
                tickfont=dict(family="Malgun Gothic", size=11),
                gridcolor="rgba(0,0,0,0.06)",
                title_font=dict(family="Malgun Gothic, sans-serif"),
            )
            fig_tb.update_yaxes(
                title_text="평균값",
                gridcolor="rgba(0,0,0,0.06)",
                tickfont=dict(family="Malgun Gothic, sans-serif"),
                title_font=dict(family="Malgun Gothic, sans-serif"),
                range_mode="tozero",
            )

            st.plotly_chart(fig_tb, use_container_width=False, width="stretch")

            uncertainty_note = ""
            if n_top < 10 or n_bot < 10:
                uncertainty_note = (
                    f"⚠️ 표본이 적습니다 (Top {n_top}개체, Bottom {n_bot}개체). "
                    "결과가 우연에 의한 것일 가능성이 있으므로 해석에 주의하세요."
                )
            st.caption(
                f"생중량 기준 상위 25%(Q3 이상, {n_top}개체)와 하위 25%(Q1 이하, {n_bot}개체)로 "
                "나눈 뒤, 각 그룹의 다른 생육 항목 평균을 비교한 막대그래프입니다. "
                "두 그룹 간 차이가 클수록 생중량이 큰 개체가 다른 항목에서도 전반적으로 우수하다는 뜻입니다. "
                + (uncertainty_note or "각 그룹 표본이 20개체 내외로 비교 결과는 비교적 안정적입니다.")
            )
        else:
            st.warning(
                "생육 결과 CSV에서 '잎 수' 관련 열을 찾지 못했습니다. "
                "열 이름이 '잎 수', '잎수', 'leaf' 등을 포함하면 자동으로 인식됩니다."
            )


# ════════════════════════════════════════════════════
#  탭4 ─ 데이터 다운로드
# ════════════════════════════════════════════════════
with tab4:
    st.header("📥 데이터 다운로드")

    if env_df is not None:
        env_fname = env_file.name if env_file else f"{school_name}_환경데이터.csv"
        csv_bytes_env = env_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label=f"🌡️ {env_fname} 다운로드 (원본)",
            data=csv_bytes_env,
            file_name=env_fname,
            mime="text/csv",
            help="utf-8-sig(BOM 포함)로 인코딩되어 엑셀에서 한글이 깨지지 않습니다.",
        )

    if growth_df is not None:
        growth_fname = growth_file.name if growth_file else f"{school_name}_생육결과데이터.csv"
        csv_bytes_growth = growth_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label=f"🌱 {growth_fname} 다운로드 (원본)",
            data=csv_bytes_growth,
            file_name=growth_fname,
            mime="text/csv",
            help="utf-8-sig(BOM 포함)로 인코딩되어 엑셀에서 한글이 깨지지 않습니다.",
        )

    st.divider()
    st.caption(
        "다운로드 파일은 모두 utf-8-sig(BOM 포함) 인코딩입니다. "
        "to_excel 및 openpyxl은 사용하지 않으며 CSV 형식만 제공합니다. "
        "원본 CSV의 열 이름·순서는 그대로 유지됩니다."
    )
