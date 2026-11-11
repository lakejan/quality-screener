# -*- coding: utf-8 -*-
"""
한·미 퀄리티 주식 스크리너 (Streamlit UI)
- 테리 스미스 / 퀄리티 투자 프레임워크 기반 필터링 및 참고 지표 동반 조회
- GPM (참고: OPM)
- ROCE (참고: EBIT Margin, 사용자본회전율)
- CCR (참고: 100% 미만/초과 원인 자동 진단, CapEx vs 감가상각비, 운전자본 변동)
- 이자보상배율 (무차입 기업 자동 예외 처리)
- 역DCF 기대성장률 (정상화 FCF = OCF - 감가상각비 기준, g = r - FCF Yield) 및 실시간 주가/시총 갱신
"""

from __future__ import annotations

from datetime import datetime
import html
import io
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import data_engine as de

st.set_page_config(
    page_title="한·미 퀄리티 기업 스크리너",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="auto",
)

# =====================================================================
# 보안 인증 (Streamlit Community Cloud 배포 시 비공개 유지)
# =====================================================================
def check_password() -> bool:
    """Streamlit Secrets에 APP_PASSWORD가 있을 때만 비공개 로그인 화면 노출"""
    if "APP_PASSWORD" not in st.secrets:
        return True
    if st.session_state.get("password_correct", False):
        return True

    st.markdown("### 🔒 퀄리티 스크리너 보안 인증")
    st.caption("비공개 투자 스크리너입니다. 설정된 비밀번호를 입력하세요.")
    pwd_input = st.text_input("비밀번호", type="password", key="password_input")
    if st.button("접속하기", type="primary", use_container_width=True):
        if pwd_input == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")
    return False

if not check_password():
    st.stop()

# =====================================================================
# 유틸리티 함수: 숫자 포맷팅 및 엑셀 다운로드
# =====================================================================
def format_currency_amount(val: float, market: str) -> str:
    if pd.isna(val):
        return "N/A"
    if str(market).upper() == "KR":
        uk = val / 1e8  # 억 원
        if abs(uk) >= 10000:
            return f"{uk / 10000:,.2f}조 원 ({uk:,.0f}억)"
        return f"{uk:,.0f}억 원"
    else:
        mil = val / 1e6  # Million USD
        if abs(mil) >= 1000:
            return f"${mil / 1000:,.2f}B (${mil:,.0f}M)"
        return f"${mil:,.1f}M"


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Screening_Result")
    return output.getvalue()


@st.cache_data(ttl=3600, show_spinner=False)
def get_cached_multiyear_data(
    symbol: str,
    market: str,
    ccr_denom: str,
    deduct_cash: bool,
) -> pd.DataFrame:
    """개별 기업 3~4개년 정밀 재무제표 캐싱 로더"""
    return de.fetch_stock_multiyear_data(
        symbol=symbol,
        market=market,
        ccr_denominator=ccr_denom,
        deduct_cash_from_ce=deduct_cash,
        max_years=4,
    )


# =====================================================================
# 지표별 계산 공식 및 설명 사전 (SSOT & ⓘ 호버 툴팁)
# =====================================================================
METRIC_DEFINITIONS: Dict[str, Dict[str, str]] = {
    "GPM (%)": {
        "title": "🎯 매출총이익률 (GPM, Gross Profit Margin)",
        "formula": "(매출총이익 / 매출액) × 100",
        "desc": "원가 경쟁력과 가격 결정력(Pricing Power)의 1차 방어선. 높은 GPM은 강력한 브랜드, 독점 기술 등 경제적 해자의 핵심 증거입니다.",
        "icon": "🎯",
    },
    "OPM (%)": {
        "title": "📎 영업이익률 (OPM, Operating Profit Margin)",
        "formula": "(영업이익 / 매출액) × 100",
        "desc": "매출액 중 판관비를 제하고 본업에서 남긴 순수 영업 마진. 본업의 수익 창출 효율성을 나타냅니다.",
        "icon": "📎",
    },
    "ROCE (%)": {
        "title": "🎯 사용자본이익률 (ROCE, Return on Capital Employed)",
        "formula": "(영업이익(EBIT) / 사용자본(CE)) × 100\n• 표준 사용자본(CE) = 총자산 - 유동부채\n• 현금차감 사용자본 = 총자산 - 유동부채 - 현금및단기금융상품\n• 듀퐁 항등식: ROCE = EBIT Margin × 사용자본회전율",
        "desc": "주주와 채권자가 사업에 실질적으로 묶어둔 자본 대비 얼마의 영업이익을 창출했는가를 측정하는 퀄리티 투자의 최우선 지표입니다.",
        "icon": "🎯",
    },
    "EBIT Margin (%)": {
        "title": "📎 EBIT 마진율 (EBIT Margin)",
        "formula": "(영업이익(EBIT) / 매출액) × 100",
        "desc": "ROCE 듀퐁 분해의 첫 번째 축. 매출 1원당 남기는 영업이익 마진의 크기를 나타냅니다.",
        "icon": "📎",
    },
    "사용자본회전율 (배)": {
        "title": "📎 사용자본회전율 (Capital Employed Turnover)",
        "formula": "매출액 / 사용자본(CE) (배)",
        "desc": "ROCE 듀퐁 분해의 두 번째 축. 투입된 자본 1원당 매출을 몇 배 회전시켜 창출하는지(자산 경량화 및 자본 회전 속도)를 측정합니다.",
        "icon": "📎",
    },
    "CCR (%)": {
        "title": "🎯 현금전환율 (CCR, Cash Conversion Ratio)",
        "formula": "설정 옵션에 따름:\n• [권장 A (세후 일치)]: (OCF - CapEx) / 당기순이익 × 100 (FCF / Net Income)\n• [권장 B (테리 스미스)]: (OCF + 법인세 - CapEx) / 영업이익 × 100\n• [대안 C (단순)]: (OCF - CapEx) / 영업이익 × 100\n• [대안 D (CapEx 미차감)]: OCF / 영업이익 × 100",
        "desc": "장부상 보고된 회계 이익이 실제 기업 통장에 꽂히는 잉여현금흐름(FCF)으로 얼마나 전환되는지 측정하는 '이익의 질(Quality of Earnings)' 지표입니다.",
        "icon": "🎯",
    },
    "CapEx/감가상각비 (%)": {
        "title": "📎 CapEx / 감가상각비 (D&A) 비율",
        "formula": "(자본적지출(CapEx) / 감가상각비(D&A)) × 100",
        "desc": "100% 초과 시 신규 증설·확장 투자가 활발함을 의미하며, 100% 미만 시 유지보수 위주의 자산 경량(Asset-light) 사업임을 의미합니다. CCR 100% 상·하회의 핵심 요인입니다.",
        "icon": "📎",
    },
    "운전자본변동/EBIT (%)": {
        "title": "📎 운전자본 변동 / EBIT 비율",
        "formula": "(현금흐름표상 운전자본 변동액 / 영업이익) × 100",
        "desc": "음수(-)면 매출채권·재고자산 증가로 현금이 사업에 잠김(현금 유출), 양수(+)면 선수금·매입채무 활용으로 현금이 선유입됨을 의미합니다.",
        "icon": "📎",
    },
    "CCR 상태 진단": {
        "title": "📎 CCR 100% 상·하회 원인 진단",
        "formula": "운전자본 변동 + CapEx vs D&A + 매입채무 변동 종합 분석",
        "desc": "CCR이 100%를 미달하거나 초과하는 근본적인 재무적 동력을 자동으로 추적·요약합니다.",
        "icon": "📎",
    },
    "이자보상배율": {
        "title": "🎯 이자보상배율 (Interest Coverage Ratio)",
        "formula": "영업이익(EBIT) / 이자비용 (배)\n• 무차입/순현금(이자비용 ≤ 0)인 흑자 기업: ∞ (자동 통과)",
        "desc": "영업활동으로 번 이익으로 금융 이자비용을 몇 배나 감당할 수 있는지 나타내는 재무 안정성 지표입니다.",
        "icon": "🎯",
    },
    "정상화 FCF": {
        "title": "📎 정상화 FCF (Normalized Free Cash Flow)",
        "formula": "영업현금흐름(OCF) - 감가상각비(D&A)",
        "desc": "일시적 대규모 확장 CapEx 왜곡을 제거하고 유지보수 CapEx를 감가상각비(D&A)로 근사한 테리 스미스·버핏 스타일의 정상화 주주이익(Owner Earnings)입니다.",
        "icon": "📎",
    },
    "정상화 FCF 수익률 (%)": {
        "title": "📎 정상화 FCF 수익률 (Normalized FCF Yield)",
        "formula": "(정상화 FCF / 시가총액) × 100\n• 정상화 FCF = 영업현금흐름(OCF) - 감가상각비(D&A)",
        "desc": "현재 시가총액 대비 정상화 주주이익의 비율로, 채권의 쿠폰 수익률에 대응하는 밸류에이션 지표입니다.",
        "icon": "📎",
    },
    "역DCF 기대성장률 (%)": {
        "title": "🔥 역DCF 내포 기대성장률 (Implied Growth Rate, g)",
        "formula": "g = 요구수익률(r) - 정상화 FCF 수익률 (%)\n• 산출 근거: 고든 성장 모델 역산 P = FCF / (r - g) ⟹ g = r - (FCF / P)",
        "desc": "현재 주가(시가총액)를 정당화하기 위해 시장이 기업에게 요구하는 영구 복리 성장률입니다. g가 낮거나 음수일수록 안전마진이 높습니다.",
        "icon": "🔥",
    },
    "무성장 내재가치": {
        "title": "💡 무성장 내재가치 (Zero Growth Fair Value)",
        "formula": "정상화 FCF / (요구수익률 r / 100)",
        "desc": "기업이 향후 영구히 성장을 전혀(0%) 하지 않더라도 현재 FCF를 매년 유지할 때의 영구 연금 가치입니다.",
        "icon": "💡",
    },
}


def get_metric_tooltip(metric_key: str) -> str:
    """Streamlit 위젯의 help 파라미터용 텍스트 반환"""
    info = METRIC_DEFINITIONS.get(metric_key)
    if not info:
        return ""
    return f"📐 [계산 공식]\n{info['formula']}\n\n💡 [지표 설명]\n{info['desc']}"


def render_hover_chips_guide() -> None:
    """
    마우스를 올리면(호버) 지표 계산 공식과 설명이 풍선처럼 나타나는
    인터랙티브 ⓘ 퀵 가이드 칩 바를 렌더링합니다.
    """
    key_metrics = [
        ("GPM (%)", "🎯 GPM ⓘ"),
        ("ROCE (%)", "🎯 ROCE ⓘ"),
        ("CCR (%)", "🎯 CCR ⓘ"),
        ("이자보상배율", "🎯 이자보상배율 ⓘ"),
        ("역DCF 기대성장률 (%)", "🔥 역DCF 기대성장률(g) ⓘ"),
        ("정상화 FCF 수익률 (%)", "📎 FCF 수익률 ⓘ"),
        ("OPM (%)", "📎 OPM ⓘ"),
        ("CapEx/감가상각비 (%)", "📎 CapEx/D&A ⓘ"),
        ("운전자본변동/EBIT (%)", "📎 운전자본/EBIT ⓘ"),
    ]

    chips_html = []
    for m_key, m_label in key_metrics:
        info = METRIC_DEFINITIONS.get(m_key, {})
        title = html.escape(info.get("title", m_label))
        formula = html.escape(info.get("formula", ""))
        desc = html.escape(info.get("desc", ""))

        chip_markup = f"""
        <div class="hover-metric-chip">
            <span class="chip-text">{m_label}</span>
            <div class="hover-tooltip-card">
                <div class="tt-header">{title}</div>
                <div class="tt-formula-label">📐 계산 공식</div>
                <div class="tt-formula">{formula}</div>
                <div class="tt-desc-label">💡 지표 해석 & 의미</div>
                <div class="tt-desc">{desc}</div>
            </div>
        </div>
        """
        chips_html.append(chip_markup)

    all_chips = "\n".join(chips_html)

    html_content = f"""
    <style>
    div[data-testid="stHtml"] {{
        position: relative !important;
        z-index: 9999 !important;
        overflow: visible !important;
    }}
    .metric-guide-wrapper {{
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 12px 14px;
        margin: 8px 0 16px 0;
        position: relative;
        z-index: 9999;
        overflow: visible;
    }}
    .metric-guide-header {{
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 0.83rem;
        font-weight: 700;
        color: #334155;
        margin-bottom: 8px;
    }}
    .metric-guide-chips {{
        display: flex;
        flex-wrap: wrap;
        gap: 7px;
        overflow: visible;
    }}
    .hover-metric-chip {{
        position: relative;
        display: inline-flex;
        align-items: center;
        background: #ffffff;
        border: 1px solid #cbd5e1;
        border-radius: 16px;
        padding: 4px 10px;
        font-size: 0.80rem;
        font-weight: 600;
        color: #1e293b;
        cursor: pointer;
        transition: all 0.15s ease-in-out;
        z-index: 10000;
    }}
    .hover-metric-chip:hover {{
        background: #eff6ff;
        border-color: #3b82f6;
        color: #1d4ed8;
        transform: translateY(-1px);
        box-shadow: 0 3px 8px rgba(37, 99, 235, 0.15);
        z-index: 999999;
    }}
    .hover-metric-chip .chip-text {{
        user-select: none;
    }}
    /* 호버 툴팁 카드: 칩 위쪽으로 띄워 아래 셀렉트박스와 절대 겹치지 않도록 처리 */
    .hover-tooltip-card {{
        visibility: hidden;
        opacity: 0;
        position: absolute;
        bottom: calc(100% + 9px);
        left: 0;
        width: 330px;
        background-color: #0f172a;
        color: #f8fafc;
        border-radius: 8px;
        padding: 12px 14px;
        box-shadow: 0 16px 36px rgba(0, 0, 0, 0.4);
        z-index: 999999 !important;
        pointer-events: none;
        transition: opacity 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        text-align: left;
    }}
    .hover-metric-chip:hover .hover-tooltip-card {{
        visibility: visible;
        opacity: 1;
    }}
    /* 말풍선 꼬리표: 아래쪽으로 칩을 가리킴 */
    .hover-tooltip-card::after {{
        content: '';
        position: absolute;
        top: 100%;
        left: 20px;
        border-width: 6px;
        border-style: solid;
        border-color: #0f172a transparent transparent transparent;
    }}
    /* 우측 끝 칩들은 화면 오른쪽 밖으로 넘치지 않게 오른쪽 정렬 */
    .metric-guide-chips > .hover-metric-chip:nth-last-child(-n+3) .hover-tooltip-card {{
        left: auto;
        right: 0;
    }}
    .metric-guide-chips > .hover-metric-chip:nth-last-child(-n+3) .hover-tooltip-card::after {{
        left: auto;
        right: 20px;
    }}
    .tt-header {{
        font-size: 0.83rem;
        font-weight: 700;
        color: #f1f5f9;
        margin-bottom: 6px;
        border-bottom: 1px solid #334155;
        padding-bottom: 4px;
    }}
    .tt-formula-label {{
        font-size: 0.72rem;
        font-weight: 700;
        color: #38bdf8;
        margin-top: 4px;
    }}
    .tt-formula {{
        font-family: Consolas, monospace;
        font-size: 0.76rem;
        color: #bae6fd;
        background: rgba(56, 189, 248, 0.12);
        padding: 4px 7px;
        border-radius: 4px;
        margin: 2px 0 6px 0;
        line-height: 1.35;
        word-break: break-all;
        white-space: pre-line;
    }}
    .tt-desc-label {{
        font-size: 0.72rem;
        font-weight: 700;
        color: #94a3b8;
    }}
    .tt-desc {{
        font-size: 0.74rem;
        color: #cbd5e1;
        line-height: 1.4;
        margin-top: 2px;
    }}
    </style>
    <div class="metric-guide-wrapper">
        <div class="metric-guide-header">
            <span>💡 <b>지표 계산 공식 퀵 가이드</b> (지표에 마우스를 올리면 계산식과 투자 해석이 나타납니다)</span>
        </div>
        <div class="metric-guide-chips">
            {all_chips}
        </div>
    </div>
    """
    st.html(html_content)


def build_column_config(req_r: float) -> Dict[str, Any]:
    """Tab 1 st.dataframe 용 컬럼 헤더 ⓘ 및 호버 툴팁(help) 설정"""
    g_col_name = f"🔥 [역DCF] 기대성장률 g (r={req_r:.0f}%)"
    return {
        "티커": st.column_config.TextColumn("티커", width="small"),
        "기업명": st.column_config.TextColumn("기업명", width="medium"),
        "시장": st.column_config.TextColumn("시장", width="medium"),
        "시가총액": st.column_config.TextColumn("시가총액", width="medium"),
        "📎 [참고] FCF 수익률 (%)": st.column_config.NumberColumn(
            "📎 [참고] FCF 수익률 (%) ⓘ",
            help=get_metric_tooltip("정상화 FCF 수익률 (%)"),
            format="%.2f%%",
        ),
        g_col_name: st.column_config.NumberColumn(
            f"🔥 [역DCF] 기대성장률 g (r={req_r:.0f}%) ⓘ",
            help=get_metric_tooltip("역DCF 기대성장률 (%)"),
            format="%+.2f%%",
        ),
        "🎯 GPM (%)": st.column_config.NumberColumn(
            "🎯 GPM (%) ⓘ",
            help=get_metric_tooltip("GPM (%)"),
            format="%.1f%%",
        ),
        "📎 [참고] OPM (%)": st.column_config.NumberColumn(
            "📎 [참고] OPM (%) ⓘ",
            help=get_metric_tooltip("OPM (%)"),
            format="%.1f%%",
        ),
        "🎯 ROCE (%)": st.column_config.NumberColumn(
            "🎯 ROCE (%) ⓘ",
            help=get_metric_tooltip("ROCE (%)"),
            format="%.1f%%",
        ),
        "📎 [참고] EBIT Margin (%)": st.column_config.NumberColumn(
            "📎 [참고] EBIT Margin (%) ⓘ",
            help=get_metric_tooltip("EBIT Margin (%)"),
            format="%.1f%%",
        ),
        "📎 [참고] 사용자본회전율 (배)": st.column_config.NumberColumn(
            "📎 [참고] 사용자본회전율 (배) ⓘ",
            help=get_metric_tooltip("사용자본회전율 (배)"),
            format="%.2f배",
        ),
        "🎯 CCR (%)": st.column_config.NumberColumn(
            "🎯 CCR (%) ⓘ",
            help=get_metric_tooltip("CCR (%)"),
            format="%.1f%%",
        ),
        "📎 [참고] CapEx/D&A (%)": st.column_config.NumberColumn(
            "📎 [참고] CapEx/D&A (%) ⓘ",
            help=get_metric_tooltip("CapEx/감가상각비 (%)"),
            format="%.0f%%",
        ),
        "📎 [참고] 운전자본변동/EBIT (%)": st.column_config.NumberColumn(
            "📎 [참고] 운전자본변동/EBIT (%) ⓘ",
            help=get_metric_tooltip("운전자본변동/EBIT (%)"),
            format="%+.1f%%",
        ),
        "📎 [참고] CCR 100% 상·하회 원인 진단": st.column_config.TextColumn(
            "📎 [참고] CCR 원인 진단 ⓘ",
            help=get_metric_tooltip("CCR 상태 진단"),
            width="large",
        ),
        "🎯 이자보상배율": st.column_config.TextColumn(
            "🎯 이자보상배율 ⓘ",
            help=get_metric_tooltip("이자보상배율"),
            width="medium",
        ),
        "결산기준일": st.column_config.TextColumn("결산기준일", width="small"),
    }


def build_matrix_column_config() -> Dict[str, Any]:
    """Tab 3 st.dataframe 용 컬럼 헤더 ⓘ 및 호버 툴팁(help) 설정"""
    return {
        "symbol": st.column_config.TextColumn("티커", width="small"),
        "name": st.column_config.TextColumn("기업명", width="medium"),
        "market_display": st.column_config.TextColumn("시장", width="medium"),
        "시가총액_표시": st.column_config.TextColumn("시가총액", width="medium"),
        "통과_조건수": st.column_config.TextColumn("통과조건수", width="small"),
        "정상화 FCF 수익률 (%)": st.column_config.NumberColumn(
            "FCF 수익률 (%) ⓘ",
            help=get_metric_tooltip("정상화 FCF 수익률 (%)"),
            format="%.2f%%",
        ),
        "역DCF 기대성장률 (%)": st.column_config.NumberColumn(
            "역DCF g (%) ⓘ",
            help=get_metric_tooltip("역DCF 기대성장률 (%)"),
            format="%+.2f%%",
        ),
        "GPM (%)": st.column_config.NumberColumn(
            "GPM (%) ⓘ",
            help=get_metric_tooltip("GPM (%)"),
            format="%.1f%%",
        ),
        "OPM (%)": st.column_config.NumberColumn(
            "OPM (%) ⓘ",
            help=get_metric_tooltip("OPM (%)"),
            format="%.1f%%",
        ),
        "ROCE (%)": st.column_config.NumberColumn(
            "ROCE (%) ⓘ",
            help=get_metric_tooltip("ROCE (%)"),
            format="%.1f%%",
        ),
        "EBIT Margin (%)": st.column_config.NumberColumn(
            "EBIT Margin (%) ⓘ",
            help=get_metric_tooltip("EBIT Margin (%)"),
            format="%.1f%%",
        ),
        "사용자본회전율 (배)": st.column_config.NumberColumn(
            "회전율 (배) ⓘ",
            help=get_metric_tooltip("사용자본회전율 (배)"),
            format="%.2f배",
        ),
        "CCR (%)": st.column_config.NumberColumn(
            "CCR (%) ⓘ",
            help=get_metric_tooltip("CCR (%)"),
            format="%.1f%%",
        ),
        "CapEx/감가상각비 (%)": st.column_config.NumberColumn(
            "CapEx/D&A (%) ⓘ",
            help=get_metric_tooltip("CapEx/감가상각비 (%)"),
            format="%.0f%%",
        ),
        "CCR 상태 진단": st.column_config.TextColumn(
            "CCR 원인 진단 ⓘ",
            help=get_metric_tooltip("CCR 상태 진단"),
            width="large",
        ),
        "이자보상배율_표시": st.column_config.TextColumn(
            "이자보상배율 ⓘ",
            help=get_metric_tooltip("이자보상배율"),
            width="medium",
        ),
    }


# =====================================================================
# 사이드바: 1. 시장 선택 & 실시간 주가 갱신 & 데이터 수집 관리
# =====================================================================
st.sidebar.title("🎯 퀄리티 스크리너 설정")

market_choice = st.sidebar.radio(
    "🌍 분석 대상 시장",
    options=["KR (한국 주식)", "US (미국 주식)", "ALL (한·미 통합)"],
    index=0,
)

if market_choice.startswith("KR"):
    selected_market = "KR"
    sub_market_choice = st.sidebar.selectbox(
        "🏛️ 세부 시장 (코스피 / 코스닥)",
        options=["전체 (코스피 + 코스닥)", "KR (KOSPI)", "KR (KOSDAQ)"],
        index=0,
        help="한국 유가증권시장(KOSPI) 또는 코스닥(KOSDAQ) 상장 기업만 선택하여 필터링합니다.",
    )
elif market_choice.startswith("US"):
    selected_market = "US"
    sub_market_choice = st.sidebar.selectbox(
        "🏛️ 세부 시장 (나스닥 / NYSE)",
        options=["전체 (나스닥 + NYSE)", "US (NASDAQ)", "US (NYSE)"],
        index=0,
        help="미국 나스닥(NASDAQ) 또는 뉴욕증권거래소(NYSE) 상장 기업만 선택하여 필터링합니다.",
    )
else:
    selected_market = "ALL"
    sub_market_choice = st.sidebar.selectbox(
        "🏛️ 세부 시장 (거래소 선택)",
        options=["전체 시장", "KR (KOSPI)", "KR (KOSDAQ)", "US (NASDAQ)", "US (NYSE)"],
        index=0,
        help="특정 국가나 거래소만 선별하여 한·미 통합 분석할 수 있습니다.",
    )

# 실시간 주가·시가총액 빠른 갱신 버튼 (사이드바 상단)
if st.sidebar.button("⚡ 실시간 주가·시총 갱신 (역DCF 최신화)", use_container_width=True, type="primary"):
    with st.sidebar:
        with st.spinner("최신 주가 및 시가총액 갱신 중 (약 1~2초)..."):
            cnt = de.refresh_prices_and_market_cap(selected_market)
            st.session_state["last_price_refresh"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st.cache_data.clear()
        st.success(f"{cnt}개 기업 주가·시총 갱신 완료!")
        st.rerun()

if "last_price_refresh" in st.session_state:
    st.sidebar.caption(f"⏱️ 최근 주가 갱신: `{st.session_state['last_price_refresh']}`")

with st.sidebar.expander("🔄 데이터 수집 / 종목 유니버스 관리", expanded=False):
    st.caption("로컬 캐시된 재무 데이터를 즉시 불러오며, 원할 때 최신 재무제표를 새로 수집할 수 있습니다.")
    fetch_target_mkt = st.selectbox("수집할 시장 선택", ["KR", "US"], index=0 if selected_market != "US" else 1)

    if fetch_target_mkt == "KR":
        min_mcap_uk = st.number_input("최소 시가총액 (억 원)", min_value=500, max_value=100000, value=2000, step=500)
        min_mcap_raw = float(min_mcap_uk) * 1e8
    else:
        min_mcap_bil = st.number_input("최소 시가총액 ($B, 십억 달러)", min_value=1.0, max_value=500.0, value=10.0, step=1.0)
        min_mcap_raw = float(min_mcap_bil) * 1e9

    max_fetch_cnt = st.slider("수집할 최대 기업 수 (시총 상위순)", min_value=30, max_value=300, value=150, step=10)
    pre_gpm_cut = st.number_input("1차 서버 프리필터: 최소 GPM (%)", min_value=0, max_value=80, value=25, step=5, help="속도 최적화를 위해 서버에서 GPM이 이 값 이상인 흑자 기업만 먼저 가져옵니다.")

    if st.button("🚀 유니버스 재무제표 새로 수집", use_container_width=True):
        with st.spinner(f"{fetch_target_mkt} 시장 유니버스 조회 중..."):
            uni_items = de.fetch_universe_symbols(
                market=fetch_target_mkt,
                min_market_cap=min_mcap_raw,
                max_count=max_fetch_cnt,
                only_profitable=True,
                pre_filter_gpm=pre_gpm_cut if pre_gpm_cut > 0 else None,
            )
        if not uni_items:
            st.error("조건에 맞는 종목을 찾지 못했습니다.")
        else:
            prog_bar = st.progress(0, text=f"0 / {len(uni_items)} 기업 재무제표 수집 중...")

            def _update_prog(done: int, total: int) -> None:
                prog_bar.progress(done / total, text=f"{done} / {total} 기업 정밀 재무제표 파싱 중...")

            new_df = de.fetch_batch_raw_financials(uni_items, max_workers=12, progress_callback=_update_prog)
            de.save_raw_cache(new_df, fetch_target_mkt)
            prog_bar.empty()
            st.success(f"{fetch_target_mkt} 시장 {len(new_df)}개 기업 저장 완료!")
            st.rerun()

    st.markdown("---")
    custom_tickers_input = st.text_input(
        "➕ 개별 종목 직접 추가 (쉼표 구분)",
        placeholder="예: 058470.KQ, 340570.KQ, MSFT, VLTO",
        help="한국 코스피는 .KS, 코스닥은 .KQ를 붙이거나 6자리 숫자만 입력하세요.",
    )
    if st.button("개별 종목 캐시에 추가", use_container_width=True) and custom_tickers_input.strip():
        raw_tokens = [t.strip().upper() for t in custom_tickers_input.split(",") if t.strip()]
        krx_map = de.load_krx_name_map()
        kr_add_items = []
        us_add_items = []

        for tok in raw_tokens:
            if len(tok) == 6 and tok.isdigit():
                for suffix in [".KS", ".KQ"]:
                    test_sym = tok + suffix
                    tk_info = de.fetch_single_stock_raw(
                        {"symbol": test_sym, "name": krx_map.get(tok, {}).get("name", test_sym), "market": "KR", "currency": "KRW"}
                    )
                    if tk_info is not None:
                        kr_add_items.append(tk_info)
                        break
            elif tok.endswith(".KS") or tok.endswith(".KQ"):
                base_c = tok.split(".")[0]
                tk_info = de.fetch_single_stock_raw(
                    {"symbol": tok, "name": krx_map.get(base_c, {}).get("name", tok), "market": "KR", "currency": "KRW"}
                )
                if tk_info is not None:
                    kr_add_items.append(tk_info)
            else:
                tk_info = de.fetch_single_stock_raw(
                    {"symbol": tok, "name": tok, "market": "US", "currency": "USD"}
                )
                if tk_info is not None:
                    us_add_items.append(tk_info)

        added_cnt = 0
        if kr_add_items:
            old_kr = de.load_raw_cache("KR")
            merged_kr = pd.concat([old_kr, pd.DataFrame(kr_add_items)], ignore_index=True).drop_duplicates(subset=["symbol"], keep="last")
            de.save_raw_cache(merged_kr, "KR")
            de.refresh_prices_and_market_cap("KR")
            added_cnt += len(kr_add_items)
        if us_add_items:
            old_us = de.load_raw_cache("US")
            merged_us = pd.concat([old_us, pd.DataFrame(us_add_items)], ignore_index=True).drop_duplicates(subset=["symbol"], keep="last")
            de.save_raw_cache(merged_us, "US")
            de.refresh_prices_and_market_cap("US")
            added_cnt += len(us_add_items)

        if added_cnt > 0:
            st.success(f"{added_cnt}개 종목 재무제표가 추가되었습니다!")
            st.rerun()
        else:
            st.warning("유효한 재무제표를 찾을 수 없습니다. 티커를 확인해 주세요.")


# =====================================================================
# 사이드바: 2. 재무제표 산식 해석 옵션 & 역DCF 요구수익률(r)
# =====================================================================
st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ 재무 지표 & 역DCF 산출 기준")

required_return_r = st.sidebar.number_input(
    "🔥 역DCF 요구수익률 r (%)",
    min_value=5.0,
    max_value=25.0,
    value=10.0,
    step=0.5,
    help="역DCF 공식: 기대성장률(g) = 요구수익률(r) - 정상화 FCF 수익률. 여기서 정상화 FCF = OCF - 감가상각비(D&A)로 계산합니다.",
)

deduct_cash_opt = st.sidebar.checkbox(
    "사용자본(CE)에서 현금성자산 차감",
    value=False,
    help="체크 해제 시 표준 공식(총자산 - 유동부채)을 사용하며, 체크 시 (총자산 - 유동부채 - 현금및단기금융상품)으로 현금 부자 기업의 실질 ROCE를 계산합니다.",
)

ccr_denom_label = st.sidebar.selectbox(
    "CCR (현금전환율) 산출 공식",
    options=[
        "권장 A (세후 일치): (OCF - CapEx) / 당기순이익",
        "권장 B (테리 스미스 세전 일치): (OCF + 법인세 - CapEx) / 영업이익",
        "대안 C (단순): (OCF - CapEx) / 영업이익(EBIT)",
        "대안 D (CapEx 차감 전): OCF / 영업이익",
    ],
    index=0,
    help="OCF는 이미 법인세가 차감된 세후 현금흐름이므로, 분모를 '당기순이익(세후)'으로 맞추거나 분자에 '법인세'를 다시 더해 세전 영업이익과 비교해야 D&A=CapEx & 운전자본변동=0일 때 정확히 100%가 됩니다.",
)
if "당기순이익" in ccr_denom_label:
    ccr_denom_key = "net_income"
elif "테리 스미스" in ccr_denom_label:
    ccr_denom_key = "pretax_ebit"
elif "CapEx 차감 전" in ccr_denom_label:
    ccr_denom_key = "ocf_only"
else:
    ccr_denom_key = "ebit"

allow_missing_gpm = st.sidebar.checkbox(
    "GPM 결측 시 OPM으로 대체 (플랫폼/IT 등)",
    value=False,
    help="한국 일부 IT/서비스 기업처럼 매출원가를 별도 구분하지 않아 매출총이익(GPM)이 비어 있는 경우 영업이익률(OPM)로 대체하여 평가합니다.",
)


# =====================================================================
# 사이드바: 3. 4대 핵심 필터 & 자유 추가 조건 설정
# =====================================================================
st.sidebar.markdown("---")
st.sidebar.subheader("🔍 1. 핵심 4대 필터 설정")
st.sidebar.caption("각 지표의 ON/OFF, 부등호(`>=`, `<=`, `>`, `<`), 목표 수치를 자유롭게 조절하세요. (지표명에 마우스를 올리면 계산식이 뜹니다)")

# [필터 1] GPM
st.sidebar.markdown(
    "**① 매출총이익률 (`GPM (%)`) ⓘ** *(참고: OPM)*",
    help=get_metric_tooltip("GPM (%)"),
)
c1, c2, c3 = st.sidebar.columns([1.2, 1.3, 2.0])
use_gpm = c1.checkbox("적용", value=True, key="chk_gpm")
op_gpm = c2.selectbox("연산", [">=", "<=", ">", "<"], index=0, key="op_gpm", label_visibility="collapsed")
val_gpm = c3.number_input("GPM 기준(%)", value=40.0, step=5.0, key="val_gpm", label_visibility="collapsed")

# [필터 2] ROCE
st.sidebar.markdown(
    "**② 사용자본이익률 (`ROCE (%)`) ⓘ** *(참고: EBIT마진, 회전율)*",
    help=get_metric_tooltip("ROCE (%)"),
)
c1, c2, c3 = st.sidebar.columns([1.2, 1.3, 2.0])
use_roce = c1.checkbox("적용", value=True, key="chk_roce")
op_roce = c2.selectbox("연산", [">=", "<=", ">", "<"], index=0, key="op_roce", label_visibility="collapsed")
val_roce = c3.number_input("ROCE 기준(%)", value=15.0, step=2.5, key="val_roce", label_visibility="collapsed")

# [필터 3] CCR
st.sidebar.markdown(
    "**③ 현금전환율 (`CCR (%)`) ⓘ** *(참고: 100% 상·하회 원인)*",
    help=get_metric_tooltip("CCR (%)"),
)
c1, c2, c3 = st.sidebar.columns([1.2, 1.3, 2.0])
use_ccr = c1.checkbox("적용", value=True, key="chk_ccr")
op_ccr = c2.selectbox("연산", [">=", "<=", ">", "<"], index=0, key="op_ccr", label_visibility="collapsed")
val_ccr = c3.number_input("CCR 기준(%)", value=95.0, step=5.0, key="val_ccr", label_visibility="collapsed")

# [필터 4] 이자보상배율
st.sidebar.markdown(
    "**④ 이자보상배율 (`배`) ⓘ** *(무차입 기업 ∞ 자동 통과)*",
    help=get_metric_tooltip("이자보상배율"),
)
c1, c2, c3 = st.sidebar.columns([1.2, 1.3, 2.0])
use_icr = c1.checkbox("적용", value=True, key="chk_icr")
op_icr = c2.selectbox("연산", [">=", "<=", ">", "<"], index=0, key="op_icr", label_visibility="collapsed")
val_icr = c3.number_input("이자보상 기준(배)", value=10.0, step=5.0, key="val_icr", label_visibility="collapsed")

# [자유 추가 필터 빌더]
with st.sidebar.expander("➕ 참고 지표 / 역DCF 추가 필터링 (선택)", expanded=False):
    st.caption("기본은 참고용으로만 가져오지만, 필요시 추가 필터 조건으로 걸 수 있습니다.")
    extra_metrics_avail = [
        "선택 안 함",
        "역DCF 기대성장률 (%)",
        "정상화 FCF 수익률 (%)",
        "OPM (%)",
        "EBIT Margin (%)",
        "사용자본회전율 (배)",
        "CapEx/감가상각비 (%)",
        "운전자본변동/EBIT (%)",
        "시가총액_단위수치",
    ]
    extra_rules: List[Dict[str, Any]] = []
    for i in range(1, 3):
        st.markdown(f"**추가 조건 #{i}**")
        m_sel = st.selectbox(f"지표 선택 #{i}", extra_metrics_avail, index=0, key=f"ext_m_{i}", label_visibility="collapsed")
        if m_sel != "선택 안 함":
            ec1, ec2 = st.columns([1.5, 2.0])
            default_op_idx = 1 if "기대성장률" in m_sel else 0
            e_op = ec1.selectbox("연산자", [">=", "<=", ">", "<"], index=default_op_idx, key=f"ext_op_{i}", label_visibility="collapsed")
            e_val = ec2.number_input("값", value=6.0 if "기대성장률" in m_sel else 10.0, step=1.0, key=f"ext_val_{i}", label_visibility="collapsed")
            extra_rules.append(
                {
                    "metric": m_sel,
                    "operator": e_op,
                    "value": float(e_val),
                    "enabled": True,
                    "label": f"{m_sel} {e_op} {e_val}",
                }
            )


# =====================================================================
# 데이터 로드 및 계산 수행
# =====================================================================
if selected_market == "KR":
    raw_df = de.load_raw_cache("KR")
elif selected_market == "US":
    raw_df = de.load_raw_cache("US")
else:
    raw_df = pd.concat([de.load_raw_cache("KR"), de.load_raw_cache("US")], ignore_index=True)

if raw_df is None or raw_df.empty:
    st.title("🎯 한·미 퀄리티 기업 스크리너")
    st.info("로컬 캐시 데이터를 준비 중이거나 아직 수집된 데이터가 없습니다. 아래 버튼을 눌러 기본 유니버스를 수집하세요.")
    if st.button("⚡ 기본 유니버스(한국/미국 주요 종목) 지금 바로 수집하기"):
        with st.spinner("한국 및 미국 주요 상장사 재무제표를 수집하고 있습니다 (약 15~20초 소요)..."):
            kr_items = de.fetch_universe_symbols("KR", min_market_cap=200_000_000_000, max_count=150, only_profitable=True, pre_filter_gpm=25)
            kr_data = de.fetch_batch_raw_financials(kr_items, max_workers=12)
            de.save_raw_cache(kr_data, "KR")

            us_items = de.fetch_universe_symbols("US", min_market_cap=15_000_000_000, max_count=120, only_profitable=True, pre_filter_gpm=30)
            us_data = de.fetch_batch_raw_financials(us_items, max_workers=12)
            de.save_raw_cache(us_data, "US")

            st.rerun()
    st.stop()

metrics_df = de.compute_quality_metrics(
    raw_df,
    deduct_cash_from_ce=deduct_cash_opt,
    ccr_denominator=ccr_denom_key,
    allow_missing_gpm_as_opm=allow_missing_gpm,
    required_return_pct=required_return_r,
)

# 세부 시장 (KOSPI, KOSDAQ, NASDAQ, NYSE) 필터링
if sub_market_choice and not sub_market_choice.startswith("전체"):
    metrics_df = metrics_df[metrics_df["market_display"] == sub_market_choice].reset_index(drop=True)

# 활성 필터 규칙 조립
active_rules: List[Dict[str, Any]] = [
    {
        "metric": "GPM (%)",
        "operator": op_gpm,
        "value": float(val_gpm),
        "enabled": use_gpm,
        "label": f"GPM {op_gpm} {val_gpm:.0f}%",
    },
    {
        "metric": "ROCE (%)",
        "operator": op_roce,
        "value": float(val_roce),
        "enabled": use_roce,
        "label": f"ROCE {op_roce} {val_roce:.0f}%",
    },
    {
        "metric": "CCR (%)",
        "operator": op_ccr,
        "value": float(val_ccr),
        "enabled": use_ccr,
        "label": f"CCR {op_ccr} {val_ccr:.0f}%",
    },
    {
        "metric": "이자보상배율 (배)",
        "operator": op_icr,
        "value": float(val_icr),
        "enabled": use_icr,
        "label": f"이자보상 {op_icr} {val_icr:.0f}배",
    },
] + extra_rules

passed_df, annotated_df, funnel_stats = de.apply_filter_rules(metrics_df, active_rules)


# =====================================================================
# 메인 화면 헤더 + 실시간 주가 갱신 버튼 & 퍼널 KPI 카드
# =====================================================================
hdr_col1, hdr_col2 = st.columns([6.5, 2.5])
with hdr_col1:
    st.title("🎯 한·미 퀄리티 기업 스크리너")
    mkt_info_str = f"`{market_choice}` ({sub_market_choice})" if sub_market_choice and not sub_market_choice.startswith("전체") else f"`{market_choice}`"
    st.caption(
        f"**분석 시장**: {mkt_info_str} | "
        f"**사용자본(CE)**: `{'현금차감' if deduct_cash_opt else '표준(총자산-유동부채)'}` | "
        f"**CCR 산식**: `{ccr_denom_label}` | "
        f"**역DCF ($r={required_return_r:.1f}\\%$)**: `FCF = OCF - 감가상각비`, $g = r - \\text{{FCF Yield}}$"
    )
with hdr_col2:
    st.write("")
    if st.button("🔄 현재가·시가총액 실시간 갱신 (역DCF 업데이트)", use_container_width=True):
        with st.spinner("최신 주가 및 시가총액 반영 중..."):
            cnt = de.refresh_prices_and_market_cap(selected_market)
            st.session_state["last_price_refresh"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.toast(f"✅ {cnt}개 기업 주가·시가총액 및 역DCF 기대성장률이 갱신되었습니다!")
        st.rerun()

if funnel_stats:
    cols = st.columns(len(funnel_stats))
    for idx, stat in enumerate(funnel_stats):
        with cols[idx]:
            if idx == 0:
                st.metric(label="① 전체 분석 대상", value=f"{stat['remaining']}개 기업")
            else:
                st.metric(
                    label=f"관문: {stat['label'] if 'label' in stat else stat['stage']}",
                    value=f"{stat['remaining']}개 생존",
                    delta=f"단독 통과 {stat['single_pass']}개",
                    delta_color="off",
                )

st.markdown("---")

# =====================================================================
# 3개 메인 탭 구성 (클릭 시 개별기업 탭 자동 이동 연동)
# =====================================================================
tab1_label = f"✅ 필터 통과 기업 리스트 ({len(passed_df)}개)"
tab2_label = "🔬 개별 기업 CCR·ROCE·역DCF 정밀 해부"
tab3_label = f"📊 전체 종목 통과/탈락 매트릭스 ({len(annotated_df)}개)"
tab_labels = [tab1_label, tab2_label, tab3_label]

# 행 클릭에 따른 탭 자동 이동 의도 처리 (st.tabs 위젯 생성 전 세션 스테이트 할당)
target_intent = st.session_state.pop("target_tab_intent", None)
if target_intent == "tab2":
    st.session_state["main_tabs"] = tab2_label
elif target_intent == "tab3":
    st.session_state["main_tabs"] = tab3_label
elif target_intent == "tab1":
    st.session_state["main_tabs"] = tab1_label

# 테이블 행 클릭 시 이전 선택 상태 초기화 (재클릭 및 탭 복귀 원활화)
if st.session_state.pop("clear_passed_selection", False):
    st.session_state["df_passed_table"] = {"selection": {"rows": [], "columns": []}}

if st.session_state.pop("clear_matrix_selection", False):
    st.session_state["df_matrix_table"] = {"selection": {"rows": [], "columns": []}}

if "main_tabs" not in st.session_state:
    st.session_state["main_tabs"] = tab1_label
elif st.session_state["main_tabs"] not in tab_labels:
    cur_tab_str = str(st.session_state["main_tabs"])
    if "개별 기업" in cur_tab_str:
        st.session_state["main_tabs"] = tab2_label
    elif "매트릭스" in cur_tab_str:
        st.session_state["main_tabs"] = tab3_label
    else:
        st.session_state["main_tabs"] = tab1_label

tab1, tab2, tab3 = st.tabs(
    tab_labels,
    key="main_tabs",
    on_change="rerun",
)

# ---------------------------------------------------------------------
# TAB 1: 필터 통과 기업 리스트 + 참고 지표 & 역DCF 동반 조회
# ---------------------------------------------------------------------
with tab1:
    st.subheader(f"✅ 모든 활성 조건을 만족한 기업 ({len(passed_df)}개 / 전체 {len(annotated_df)}개)")

    st.info(
        f"💡 **[필터 지표]** 통과 기업에 대해 **[참고 지표]**(`OPM`, `EBIT Margin`, `사용자본회전율`, `CCR 원인 진단`) 및 **정상화 FCF(`= OCF - 감가상각비`) 기반 [`FCF 수익률`, `역DCF 기대성장률(g = {required_return_r:.1f}% - FCF Yield)`]**을 함께 표시합니다."
    )

    # 지표 호버링 계산 공식 퀵 가이드 칩 바
    render_hover_chips_guide()

    if passed_df.empty:
        st.warning("현재 설정된 필터 조건을 모두 만족하는 기업이 없습니다. 좌측 사이드바에서 기준 수치를 완화하거나 [📊 전체 종목 통과/탈락 매트릭스] 탭을 확인해 보세요.")
    else:
        sort_col1, sort_col2, mode_col = st.columns([2.5, 2.0, 3.5])
        with sort_col1:
            sort_by_metric = st.selectbox(
                "정렬 기준",
                options=[
                    "역DCF 기대성장률 (%)",
                    "정상화 FCF 수익률 (%)",
                    "ROCE (%)",
                    "GPM (%)",
                    "CCR (%)",
                    "OPM (%)",
                    "사용자본회전율 (배)",
                    "market_cap",
                ],
                index=2,
            )
        with sort_col2:
            default_asc = True if sort_by_metric == "역DCF 기대성장률 (%)" else False
            sort_asc = st.checkbox("오름차순 정렬 (낮은 순)", value=default_asc)
        with mode_col:
            view_mode = st.radio(
                "화면 표시 모드",
                options=["📱 모바일 카드 뷰", "📊 PC 와이드 테이블"],
                index=0,
                horizontal=True,
                key="passed_view_mode",
            )

        disp_df = passed_df.sort_values(by=sort_by_metric, ascending=sort_asc).reset_index(drop=True)

        view_cols = [
            "symbol",
            "name",
            "market_display",
            "시가총액_표시",
            "정상화 FCF 수익률 (%)",
            "역DCF 기대성장률 (%)",
            "GPM (%)",
            "OPM (%)",
            "ROCE (%)",
            "EBIT Margin (%)",
            "사용자본회전율 (배)",
            "CCR (%)",
            "CapEx/감가상각비 (%)",
            "운전자본변동/EBIT (%)",
            "CCR 상태 진단",
            "이자보상배율_표시",
            "fiscal_date",
        ]
        view_df = disp_df[view_cols].rename(
            columns={
                "symbol": "티커",
                "name": "기업명",
                "market_display": "시장",
                "시가총액_표시": "시가총액",
                "정상화 FCF 수익률 (%)": "📎 [참고] FCF 수익률 (%)",
                "역DCF 기대성장률 (%)": f"🔥 [역DCF] 기대성장률 g (r={required_return_r:.0f}%)",
                "GPM (%)": "🎯 GPM (%)",
                "OPM (%)": "📎 [참고] OPM (%)",
                "ROCE (%)": "🎯 ROCE (%)",
                "EBIT Margin (%)": "📎 [참고] EBIT Margin (%)",
                "사용자본회전율 (배)": "📎 [참고] 사용자본회전율 (배)",
                "CCR (%)": "🎯 CCR (%)",
                "CapEx/감가상각비 (%)": "📎 [참고] CapEx/D&A (%)",
                "운전자본변동/EBIT (%)": "📎 [참고] 운전자본변동/EBIT (%)",
                "CCR 상태 진단": "📎 [참고] CCR 100% 상·하회 원인 진단",
                "이자보상배율_표시": "🎯 이자보상배율",
                "fiscal_date": "결산기준일",
            }
        )

        g_col_name = f"🔥 [역DCF] 기대성장률 g (r={required_return_r:.0f}%)"

        if view_mode == "📱 모바일 카드 뷰":
            st.caption("💡 스마트폰에 최적화된 1장 요약 카드입니다. 카드의 버튼을 누르면 즉시 3개년 정밀 재무제표로 이동합니다.")
            for c_idx, row in disp_df.iterrows():
                sym = row["symbol"]
                name = row["name"]
                mkt_d = row.get("market_display", row["market"])
                mcap = row.get("시가총액_표시", "N/A")
                g_val = row.get("역DCF 기대성장률 (%)", np.nan)
                fcf_y = row.get("정상화 FCF 수익률 (%)", np.nan)
                gpm = row.get("GPM (%)", np.nan)
                roce = row.get("ROCE (%)", np.nan)
                ccr = row.get("CCR (%)", np.nan)
                ccr_diag = row.get("CCR 상태 진단", "")
                int_cov = row.get("이자보상배율_표시", "N/A")

                with st.container(border=True):
                    header_c1, header_c2 = st.columns([3, 2])
                    with header_c1:
                        st.markdown(f"#### **{name}** (`{sym}`)")
                        st.caption(f"시장: `{mkt_d}` | 시총: `{mcap}` | 결산일: `{row.get('fiscal_date', 'N/A')}`")
                    with header_c2:
                        if pd.notna(g_val):
                            st.metric(
                                label=f"🔥 역DCF 기대성장률 (r={required_return_r:.0f}%)",
                                value=f"{g_val:+.1f}%",
                                delta=f"FCF수익률 {fcf_y:.1f}%" if pd.notna(fcf_y) else None,
                            )

                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("🎯 GPM", f"{gpm:.1f}%" if pd.notna(gpm) else "N/A")
                    m2.metric("🎯 ROCE", f"{roce:.1f}%" if pd.notna(roce) else "N/A")
                    m3.metric("🎯 CCR", f"{ccr:.1f}%" if pd.notna(ccr) else "N/A")
                    m4.metric("🎯 이자보상", str(int_cov))

                    if ccr_diag and ccr_diag != "-":
                        st.caption(f"🩺 **CCR 진단**: {ccr_diag}")

                    if st.button(f"🔍 {name} 3개년 정밀 재무제표 & 듀퐁 해부 보기", key=f"btn_card_{sym}_{c_idx}", use_container_width=True):
                        st.session_state["selected_symbol"] = sym
                        st.session_state["target_tab_intent"] = "tab2"
                        st.session_state["clear_passed_selection"] = True
                        st.rerun()
        else:
            st.caption("👉 **기업 행을 클릭**하면 해당 기업의 **[🔬 개별 기업 정밀 해부]** 탭으로 즉시 이동하여 3개년 추이를 확인합니다.")
            event_passed = st.dataframe(
                view_df.style.format(
                    {
                        "📎 [참고] FCF 수익률 (%)": "{:.2f}%",
                        g_col_name: "{:+.2f}%",
                        "🎯 GPM (%)": "{:.1f}%",
                        "📎 [참고] OPM (%)": "{:.1f}%",
                        "🎯 ROCE (%)": "{:.1f}%",
                        "📎 [참고] EBIT Margin (%)": "{:.1f}%",
                        "📎 [참고] 사용자본회전율 (배)": "{:.2f}배",
                        "🎯 CCR (%)": "{:.1f}%",
                        "📎 [참고] CapEx/D&A (%)": "{:.0f}%",
                        "📎 [참고] 운전자본변동/EBIT (%)": "{:+.1f}%",
                    },
                    na_rep="N/A",
                ),
                column_config=build_column_config(required_return_r),
                use_container_width=True,
                height=min(650, 120 + len(view_df) * 38),
                on_select="rerun",
                selection_mode="single-row",
                key="df_passed_table",
            )

            # 행 클릭 감지 및 개별 기업 탭으로 즉시 이동
            if event_passed and hasattr(event_passed, "selection"):
                p_rows = event_passed.selection.get("rows", [])
                if p_rows:
                    sel_idx = p_rows[0]
                    if sel_idx < len(disp_df):
                        clicked_sym = disp_df.iloc[sel_idx]["symbol"]
                        st.session_state["selected_symbol"] = clicked_sym
                        st.session_state["target_tab_intent"] = "tab2"
                        st.session_state["clear_passed_selection"] = True
                        st.rerun()

        dl_col1, dl_col2, _ = st.columns([2, 2, 6])
        csv_bytes = view_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        dl_col1.download_button(
            label="📥 결과 CSV 다운로드 (utf-8-sig)",
            data=csv_bytes,
            file_name=f"quality_screener_{selected_market}.csv",
            mime="text/csv",
            use_container_width=True,
        )
        excel_bytes = to_excel_bytes(view_df)
        dl_col2.download_button(
            label="📥 결과 Excel (.xlsx) 다운로드",
            data=excel_bytes,
            file_name=f"quality_screener_{selected_market}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )


# ---------------------------------------------------------------------
# TAB 2: 개별 기업 CCR · ROCE · 역DCF 심층 해부
# ---------------------------------------------------------------------
with tab2:
    st.subheader("🔬 개별 기업 역DCF 기대성장률 & ROCE · CCR 정밀 해부")

    passed_syms = set(passed_df["symbol"].tolist()) if not passed_df.empty else set()
    all_options = []
    symbol_map = {}

    for _, r in annotated_df.iterrows():
        badge = "✅ [통과]" if r["symbol"] in passed_syms else f"❌ [{r['통과_조건수']} 통과]"
        g_val = r.get("역DCF 기대성장률 (%)", np.nan)
        g_str = f"역DCF g={g_val:+.1f}%" if pd.notna(g_val) else "역DCF N/A"
        label_str = f"{badge} {r['name']} ({r['symbol']}) - {g_str} | GPM {r['GPM (%)']:.1f}% | ROCE {r['ROCE (%)']:.1f}% | CCR {r['CCR (%)']:.1f}%"
        all_options.append(label_str)
        symbol_map[label_str] = r["symbol"]

    all_options.sort(key=lambda x: (0 if x.startswith("✅") else 1, x))

    target_sym = st.session_state.get("selected_symbol")
    default_opt_idx = 0
    if target_sym:
        for idx, opt in enumerate(all_options):
            if symbol_map.get(opt) == target_sym:
                default_opt_idx = idx
                break

    selected_label = st.selectbox("분석할 기업을 선택하세요", options=all_options, index=default_opt_idx)
    sel_sym = symbol_map[selected_label]
    st.session_state["selected_symbol"] = sel_sym
    row_data = annotated_df[annotated_df["symbol"] == sel_sym].iloc[0]
    mkt_code = str(row_data["market"]).upper()

    mkt_disp = row_data.get("market_display", row_data["market"])
    st.markdown(
        f"### 📌 {row_data['name']} (`{row_data['symbol']}`) — 시장: `{mkt_disp}` | 결산일: `{row_data['fiscal_date']}` | 시가총액: `{row_data['시가총액_표시']}`"
    )

    # [상단 배너] 역DCF 밸류에이션 온도계 (FCF = OCF - 감가상각비)
    norm_fcf_v = row_data.get("norm_fcf", np.nan)
    fcf_yield_v = row_data.get("정상화 FCF 수익률 (%)", np.nan)
    implied_g_v = row_data.get("역DCF 기대성장률 (%)", np.nan)
    no_growth_val = (norm_fcf_v / (required_return_r / 100.0)) if pd.notna(norm_fcf_v) and required_return_r > 0 else np.nan

    st.markdown("#### 🔥 0️⃣ 역DCF 밸류에이션 온도계 (`정상화 FCF = OCF - 감가상각비` 기준)")
    v1, v2, v3, v4 = st.columns(4)
    v1.metric(
        "정상화 FCF (OCF - D&A) ⓘ",
        format_currency_amount(norm_fcf_v, mkt_code),
        help=get_metric_tooltip("정상화 FCF"),
    )
    v2.metric(
        "정상화 FCF 수익률 (Yield) ⓘ",
        f"{fcf_yield_v:.2f}%" if pd.notna(fcf_yield_v) else "N/A",
        help=get_metric_tooltip("정상화 FCF 수익률 (%)"),
    )
    v3.metric(
        f"🔥 역DCF 내포 기대성장률 (g) ⓘ",
        f"{implied_g_v:+.2f}%" if pd.notna(implied_g_v) else "N/A",
        delta=f"요구수익률 r = {required_return_r:.1f}% 기준",
        delta_color="off",
        help=get_metric_tooltip("역DCF 기대성장률 (%)"),
    )
    v4.metric(
        f"무성장 내재가치 (g=0%, r={required_return_r:.0f}%) ⓘ",
        format_currency_amount(no_growth_val, mkt_code) if pd.notna(no_growth_val) and no_growth_val > 0 else "N/A",
        help=get_metric_tooltip("무성장 내재가치"),
    )

    st.caption(
        f"📐 **산출 근거**: $\\text{{정상화 FCF}} = \\text{{OCF}}({format_currency_amount(row_data['ocf'], mkt_code)}) - \\text{{감가상각비}}({format_currency_amount(row_data['da'], mkt_code)}) = {format_currency_amount(norm_fcf_v, mkt_code)}$ "
        f"$\\implies \\text{{FCF Yield}} = \\frac{{\\text{{정상화 FCF}}}}{{\\text{{시가총액}}({row_data['시가총액_표시']})}} = {fcf_yield_v:.2f}\\%$ "
        f"$\\implies \\mathbf{{g = r({required_return_r:.1f}\\%) - \\text{{FCF Yield}}({fcf_yield_v:.2f}\\%) = {implied_g_v:+.2f}\\%}}$"
    )
    st.markdown("---")

    # [중단 섹션] 최근 3~4개년 퀄리티 & 재무 지표 트렌드 (다개년 종합 검증)
    with st.spinner(f"⏳ {row_data['name']} 최근 3~4개년 정밀 재무제표 분석 중..."):
        df_multi = get_cached_multiyear_data(sel_sym, mkt_code, ccr_denom_key, deduct_cash_opt)

    if not df_multi.empty:
        st.markdown("#### 1️⃣ 최근 3~4개년 핵심 퀄리티 & 재무 지표 트렌드")
        st.caption("단일 연도의 일시적 왜곡을 방지하기 위해 최근 3~4개년 동안의 가격 결정력(GPM), 자본배치 효율(ROCE), 현금창출력(CCR)의 연속적 궤적을 검증합니다.")

        col_dates = df_multi["fiscal_date"].tolist()
        col_headers = []
        for idx, d in enumerate(col_dates):
            yr = d[:4]
            tag = " (최신)" if idx == len(col_dates) - 1 else ""
            col_headers.append(f"{yr}년{tag}")

        def _fmt_amt(v: float) -> str:
            return format_currency_amount(v, mkt_code)

        metric_rows = [
            ("🎯 GPM (매출총이익률)", [f"{v:.1f}%" if pd.notna(v) else "N/A" for v in df_multi["GPM (%)"]]),
            ("📎 OPM (영업이익률)", [f"{v:.1f}%" if pd.notna(v) else "N/A" for v in df_multi["OPM (%)"]]),
            ("🎯 ROCE (사용자본이익률)", [f"{v:.1f}%" if pd.notna(v) else "N/A" for v in df_multi["ROCE (%)"]]),
            ("  ↳ EBIT Margin (%)", [f"{v:.1f}%" if pd.notna(v) else "N/A" for v in df_multi["EBIT Margin (%)"]]),
            ("  ↳ 사용자본회전율 (배)", [f"{v:.2f}배" if pd.notna(v) else "N/A" for v in df_multi["사용자본회전율 (배)"]]),
            ("🎯 CCR (현금전환율)", [f"{v:.1f}%" if pd.notna(v) else "N/A" for v in df_multi["CCR (%)"]]),
            ("  ↳ CapEx / 감가상각비 (%)", [f"{v:.0f}%" if pd.notna(v) else "N/A" for v in df_multi["CapEx/감가상각비 (%)"]]),
            ("  ↳ 운전자본변동 / EBIT (%)", [f"{v:+.1f}%" if pd.notna(v) else "N/A" for v in df_multi["운전자본변동/EBIT (%)"]]),
            ("🎯 이자보상배율", df_multi["이자보상배율"].tolist()),
            ("📎 정상화 FCF (OCF - D&A)", [_fmt_amt(v) for v in df_multi["norm_fcf"]]),
            ("📎 회계상 FCF (OCF - CapEx)", [_fmt_amt(v) for v in df_multi["fcf"]]),
            ("매출액 (Revenue)", [_fmt_amt(v) for v in df_multi["revenue"]]),
            ("영업이익 (EBIT)", [_fmt_amt(v) for v in df_multi["operating_income"]]),
            ("당기순이익 (Net Income)", [_fmt_amt(v) for v in df_multi["net_income"]]),
            ("영업현금흐름 (OCF)", [_fmt_amt(v) for v in df_multi["ocf"]]),
            ("자본적지출 (CapEx)", [_fmt_amt(v) for v in df_multi["capex"]]),
            ("감가상각비 (D&A)", [_fmt_amt(v) for v in df_multi["da"]]),
            ("사용자본 (CE)", [_fmt_amt(v) for v in df_multi["ce"]]),
        ]

        table_data = {"구분 / 핵심 지표": [r[0] for r in metric_rows]}
        for idx, hdr in enumerate(col_headers):
            table_data[hdr] = [r[1][idx] for r in metric_rows]

        multi_display_df = pd.DataFrame(table_data)
        st.dataframe(multi_display_df, use_container_width=True, hide_index=True)

        # 3개년 시각화 차트 2종 (Plotly)
        c_chart1, c_chart2 = st.columns(2)

        # 1) 마진율 & ROCE 3개년 궤적 차트
        with c_chart1:
            years_x = [d[:4] for d in col_dates]
            fig_margin = go.Figure()
            fig_margin.add_trace(go.Scatter(
                x=years_x,
                y=df_multi["GPM (%)"],
                mode="lines+markers+text",
                name="GPM (%)",
                text=[f"{v:.1f}%" if pd.notna(v) else "" for v in df_multi["GPM (%)"]],
                textposition="top center",
                line=dict(color="#2563eb", width=3),
            ))
            fig_margin.add_trace(go.Scatter(
                x=years_x,
                y=df_multi["OPM (%)"],
                mode="lines+markers+text",
                name="OPM (%)",
                text=[f"{v:.1f}%" if pd.notna(v) else "" for v in df_multi["OPM (%)"]],
                textposition="top center",
                line=dict(color="#059669", width=2, dash="dash"),
            ))
            fig_margin.add_trace(go.Scatter(
                x=years_x,
                y=df_multi["ROCE (%)"],
                mode="lines+markers+text",
                name="ROCE (%)",
                text=[f"{v:.1f}%" if pd.notna(v) else "" for v in df_multi["ROCE (%)"]],
                textposition="bottom center",
                line=dict(color="#dc2626", width=3),
            ))
            fig_margin.update_layout(
                title="📈 마진율 & ROCE 3개년 궤적 (GPM · OPM · ROCE)",
                xaxis_title="결산연도",
                yaxis_title="비율 (%)",
                height=320,
                margin=dict(l=20, r=20, t=40, b=20),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig_margin, use_container_width=True)

        # 2) 이익 vs 현금흐름 3개년 비교 차트
        with c_chart2:
            unit_d = 1e8 if mkt_code == "KR" else 1e6
            u_str = "억 원" if mkt_code == "KR" else "$M"

            fig_cf = go.Figure()
            fig_cf.add_trace(go.Bar(
                x=years_x,
                y=df_multi["operating_income"] / unit_d,
                name="영업이익(EBIT)",
                marker_color="#94a3b8",
            ))
            fig_cf.add_trace(go.Bar(
                x=years_x,
                y=df_multi["net_income"] / unit_d,
                name="당기순이익",
                marker_color="#cbd5e1",
            ))
            fig_cf.add_trace(go.Scatter(
                x=years_x,
                y=df_multi["norm_fcf"] / unit_d,
                mode="lines+markers",
                name="정상화 FCF (주주이익)",
                line=dict(color="#2563eb", width=3),
            ))
            fig_cf.add_trace(go.Scatter(
                x=years_x,
                y=df_multi["fcf"] / unit_d,
                mode="lines+markers",
                name="회계상 FCF (OCF-CapEx)",
                line=dict(color="#f59e0b", width=2, dash="dot"),
            ))
            fig_cf.update_layout(
                title=f"💵 이익 vs 현금흐름 3개년 비교 (단위: {u_str})",
                barmode="group",
                xaxis_title="결산연도",
                yaxis_title=u_str,
                height=320,
                margin=dict(l=20, r=20, t=40, b=20),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig_cf, use_container_width=True)

        st.markdown("---")

    st.markdown("#### 2️⃣ 최신 결산기 정밀 분해 (ROCE 듀퐁 항등식 & CCR 현금 브릿지)")
    col_left, col_right = st.columns(2)

    # [좌측 카드] GPM -> OPM & ROCE 듀퐁 분해
    with col_left:
        st.markdown("##### 📐 ROCE 듀퐁 항등식 세부 분해 (`EBIT Margin × 사용자본회전율`)")
        gpm_v = row_data["GPM (%)"]
        opm_v = row_data["OPM (%)"]
        roce_v = row_data["ROCE (%)"]
        ebit_m_v = row_data["EBIT Margin (%)"]
        turn_v = row_data["사용자본회전율 (배)"]

        m1, m2, m3 = st.columns(3)
        m1.metric(
            "🎯 GPM (매출총이익률) ⓘ",
            f"{gpm_v:.1f}%" if pd.notna(gpm_v) else "N/A",
            help=get_metric_tooltip("GPM (%)"),
        )
        m2.metric(
            "📎 [참고] OPM (영업이익률) ⓘ",
            f"{opm_v:.1f}%" if pd.notna(opm_v) else "N/A",
            help=get_metric_tooltip("OPM (%)"),
        )
        m3.metric(
            "🎯 이자보상배율 ⓘ",
            str(row_data["이자보상배율_표시"]),
            help=get_metric_tooltip("이자보상배율"),
        )

        st.markdown("---")
        st.markdown(
            f"""
            **📐 ROCE 듀퐁 항등식 검증**:
            $$\\text{{ROCE ({roce_v:.1f}\\%)}} = \\text{{EBIT Margin ({ebit_m_v:.1f}\\%)}} \\times \\text{{사용자본회전율 ({turn_v:.2f}배)}}$$
            """
        )

        ce_std = row_data["total_assets"] - row_data["current_liabilities"]
        cash_v = row_data["cash_and_sti"]
        ce_net = ce_std - cash_v

        roce_table = pd.DataFrame(
            [
                {"항목": "매출액 (Revenue)", "금액": format_currency_amount(row_data["revenue"], mkt_code)},
                {"항목": "매출총이익 (Gross Profit)", "금액": format_currency_amount(row_data["gross_profit"], mkt_code)},
                {"항목": "영업이익 (EBIT)", "금액": format_currency_amount(row_data["operating_income"], mkt_code)},
                {"항목": "총자산 (Total Assets)", "금액": format_currency_amount(row_data["total_assets"], mkt_code)},
                {"항목": "유동부채 (Current Liabilities)", "금액": format_currency_amount(row_data["current_liabilities"], mkt_code)},
                {"항목": "표준 사용자본 (총자산 - 유동부채)", "금액": format_currency_amount(ce_std, mkt_code)},
                {"항목": "보유 현금및단기금융상품", "금액": format_currency_amount(cash_v, mkt_code)},
                {"항목": "현금차감 사용자본 (표준 CE - 현금)", "금액": format_currency_amount(ce_net, mkt_code)},
                {
                    "항목": "💡 ROCE 비교 (표준 vs 현금차감)",
                    "금액": f"표준 {row_data['ROCE_표준 (%)']:.1f}%  vs  현금차감 {row_data['ROCE_현금차감 (%)']:.1f}%",
                },
            ]
        )
        st.table(roce_table)

    # [우측 카드] CCR (현금전환율) 100% 상·하회 원인 체크리스트 진단
    with col_right:
        st.markdown("##### 🔍 CCR (현금전환율) 원인 정밀 해부")
        ccr_v = row_data["CCR (%)"]
        capex_v = row_data["capex"]
        da_v = row_data["da"]
        capex_da_ratio = row_data["CapEx/감가상각비 (%)"]
        chg_wc_v = row_data["chg_wc"]
        ocf_v = row_data["ocf"]
        fcf_v = row_data["fcf"]
        ebit_v = row_data["operating_income"]

        c_m1, c_m2, c_m3 = st.columns(3)
        c_m1.metric(
            "🎯 CCR (현금전환율) ⓘ",
            f"{ccr_v:.1f}%" if pd.notna(ccr_v) else "N/A",
            help=get_metric_tooltip("CCR (%)"),
        )
        c_m2.metric(
            "📎 CapEx / 감가상각비 ⓘ",
            f"{capex_da_ratio:.0f}%" if pd.notna(capex_da_ratio) else "N/A",
            help=get_metric_tooltip("CapEx/감가상각비 (%)"),
        )
        c_m3.metric(
            "📎 운전자본변동 / EBIT ⓘ",
            f"{row_data['운전자본변동/EBIT (%)']:+.1f}%" if pd.notna(row_data["운전자본변동/EBIT (%)"]) else "N/A",
            help=get_metric_tooltip("운전자본변동/EBIT (%)"),
        )

        st.markdown(f"**자동 진단 요약**: `{row_data['CCR 상태 진단']}`")

        if pd.notna(ccr_v) and ccr_v < 100.0:
            st.warning("##### 🔍 [CCR 100% 미만 원인 체크리스트]")
            wc_flag = "✅ **[해당]**" if (pd.notna(chg_wc_v) and chg_wc_v < 0) else "⬜ [미해당]"
            capex_flag = "✅ **[해당]**" if (capex_v > da_v) else "⬜ [미해당]"
            st.markdown(
                f"""
                1. {wc_flag} **운전자본이 계속 늘어남 (현금 유출)**
                   - 현금흐름표상 운전자본 변동: **{format_currency_amount(chg_wc_v, mkt_code)}** *(음수면 매출채권·재고 증가 등으로 현금이 묶임)*
                   - 세부: 매출채권 변동 `{format_currency_amount(row_data['chg_receivables'], mkt_code)}` | 재고자산 변동 `{format_currency_amount(row_data['chg_inventory'], mkt_code)}` | 매입채무 변동 `{format_currency_amount(row_data['chg_payables'], mkt_code)}`
                2. {capex_flag} **감가상각비보다 더 큰 CapEx 지출**
                   - 감가상각비(D&A): **{format_currency_amount(da_v, mkt_code)}** vs 자본적지출(CapEx): **{format_currency_amount(capex_v, mkt_code)}**
                   - CapEx가 감가상각비의 **{capex_da_ratio:.0f}%** 수준입니다.
                """
            )
        else:
            st.success("##### 🔍 [CCR 100% 이상 동력 체크리스트]")
            wc_in_flag = "✅ **[해당]**" if (pd.notna(chg_wc_v) and chg_wc_v > 0) else "⬜ [미해당]"
            da_big_flag = "✅ **[해당]**" if (da_v >= capex_v) else "⬜ [미해당]"
            ap_flag = "✅ **[해당]**" if (pd.notna(row_data["chg_payables"]) and row_data["chg_payables"] > 0) else "⬜ [미해당]"
            st.markdown(
                f"""
                1. {wc_in_flag} **선수금(1년치 구독료 등) 및 운전자본 현금 유입**
                   - 현금흐름표상 운전자본 변동: **{format_currency_amount(chg_wc_v, mkt_code)}** *(양수면 영업 과정에서 현금 선유입)*
                2. {da_big_flag} **감가상각비가 CapEx보다 더 큼 (낮은 설비 재투자 부담)**
                   - 감가상각비(D&A): **{format_currency_amount(da_v, mkt_code)}** vs 자본적지출(CapEx): **{format_currency_amount(capex_v, mkt_code)}** (`CapEx/D&A = {capex_da_ratio:.0f}%`)
                3. {ap_flag} **매입채무 활용 (거래처 협상력)**
                   - 매입채무 및 미지급비용 증감: **{format_currency_amount(row_data['chg_payables'], mkt_code)}**
                """
            )

        unit_div = 1e8 if mkt_code == "KR" else 1e6
        unit_label = "억 원" if mkt_code == "KR" else "$M"
        other_ocf_adj = ocf_v - (ebit_v + da_v + (chg_wc_v if pd.notna(chg_wc_v) else 0.0))

        fig = go.Figure(
            go.Waterfall(
                name="Cash Conversion Bridge",
                orientation="v",
                measure=["absolute", "relative", "relative", "relative", "total", "relative", "total"],
                x=[
                    "영업이익(EBIT)",
                    "+ 감가상각비(D&A)",
                    "± 운전자본 변동",
                    "± 세금·기타조정",
                    "영업현금흐름(OCF)",
                    "- CapEx",
                    "잉여현금흐름(FCF)",
                ],
                y=[
                    (ebit_v or 0) / unit_div,
                    (da_v or 0) / unit_div,
                    (chg_wc_v if pd.notna(chg_wc_v) else 0) / unit_div,
                    (other_ocf_adj if pd.notna(other_ocf_adj) else 0) / unit_div,
                    (ocf_v or 0) / unit_div,
                    -(capex_v or 0) / unit_div,
                    (fcf_v or 0) / unit_div,
                ],
                connector={"line": {"color": "rgb(63, 63, 63)"}},
            )
        )
        fig.update_layout(
            title=f"현금전환 브릿지 (단위: {unit_label})",
            height=340,
            margin=dict(l=20, r=20, t=40, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------
# TAB 3: 전체 유니버스 통과/탈락 매트릭스 (아깝게 탈락한 기업 확인)
# ---------------------------------------------------------------------
with tab3:
    st.subheader(f"📊 전체 종목 조건별 통과/탈락 현황 ({len(annotated_df)}개 기업)")
    st.caption(
        "예: GPM·ROCE·이자보상배율은 모두 초우량인데, 올해 대규모 증설(CapEx > 감가상각비) 때문에 CCR 조건 1개만 미달한 기업 등을 이곳에서 쉽게 발굴할 수 있습니다."
    )

    # 지표 호버링 계산 공식 퀵 가이드 칩 바
    render_hover_chips_guide()

    filter_mode = st.radio(
        "표시할 그룹 선택",
        options=["전체 보기", "아깝게 1개 조건만 미달한 기업만 보기", "최종 통과 기업만 보기"],
        horizontal=True,
    )

    mat_df = annotated_df.copy()
    active_cnt = sum(1 for r in active_rules if r.get("enabled", True))

    if filter_mode == "아깝게 1개 조건만 미달한 기업만 보기" and active_cnt > 1:
        target_str = f"{active_cnt - 1} / {active_cnt}"
        mat_df = mat_df[mat_df["통과_조건수"] == target_str]
    elif filter_mode == "최종 통과 기업만 보기":
        mat_df = mat_df[mat_df["최종_통과"] == True]

    mat_df = mat_df.reset_index(drop=True)

    pass_cols = [c for c in mat_df.columns if c.startswith("통과_") and c != "통과_조건수"]
    base_mat_cols = [
        "symbol",
        "name",
        "market_display",
        "시가총액_표시",
        "통과_조건수",
        "정상화 FCF 수익률 (%)",
        "역DCF 기대성장률 (%)",
        "GPM (%)",
        "OPM (%)",
        "ROCE (%)",
        "EBIT Margin (%)",
        "사용자본회전율 (배)",
        "CCR (%)",
        "CapEx/감가상각비 (%)",
        "CCR 상태 진단",
        "이자보상배율_표시",
    ] + pass_cols

    st.caption("👉 **기업 행을 클릭**하면 해당 기업의 **[🔬 개별 기업 정밀 해부]** 탭으로 즉시 이동하여 3개년 추이를 확인합니다.")
    event_matrix = st.dataframe(
        mat_df[base_mat_cols].style.format(
            {
                "정상화 FCF 수익률 (%)": "{:.2f}%",
                "역DCF 기대성장률 (%)": "{:+.2f}%",
                "GPM (%)": "{:.1f}%",
                "OPM (%)": "{:.1f}%",
                "ROCE (%)": "{:.1f}%",
                "EBIT Margin (%)": "{:.1f}%",
                "사용자본회전율 (배)": "{:.2f}배",
                "CCR (%)": "{:.1f}%",
                "CapEx/감가상각비 (%)": "{:.0f}%",
            },
            na_rep="N/A",
        ),
        column_config=build_matrix_column_config(),
        use_container_width=True,
        height=600,
        on_select="rerun",
        selection_mode="single-row",
        key="df_matrix_table",
    )

    # 행 클릭 감지 및 개별 기업 탭으로 즉시 이동
    if event_matrix and hasattr(event_matrix, "selection"):
        m_rows = event_matrix.selection.get("rows", [])
        if m_rows:
            sel_idx = m_rows[0]
            if sel_idx < len(mat_df):
                clicked_sym = mat_df.iloc[sel_idx]["symbol"]
                st.session_state["selected_symbol"] = clicked_sym
                st.session_state["target_tab_intent"] = "tab2"
                st.session_state["clear_matrix_selection"] = True
                st.rerun()
