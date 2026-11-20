# -*- coding: utf-8 -*-
"""
한·미 퀄리티 주식 스크리너 & 유니버스 보관함 (Streamlit UI)
- 테리 스미스 / 퀄리티 투자 프레임워크 기반 통합 스크리너 (모든 조건 통과 / 아깝게 1개 조건 미달 / 전체 종목)
- 최근 결산 수치 + 4~5개년 평균 수치 동시 조회 (4~5년 평균 FCF 수익률은 각 결산일 당시 시가총액 대비 FCF 수익률의 평균)
- 기업 상세 페이지 내 최근 4~5년 정상화 FCF 성장률(연평균 CAGR 및 연도별 YoY) 표시
- 유니버스(Universe) 영구 보관함: 관심 기업 별도 보관, 메모 & 웹 URL(구글 독스 등) 연결, 기업별 맞춤 성장기간(N년) 정밀 2단계 역DCF 계산
"""

from __future__ import annotations

from datetime import datetime
import html
import io
import re
from typing import Any, Dict, List, Optional

import importlib
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import data_engine as de
importlib.reload(de)

st.set_page_config(
    page_title="한·미 퀄리티 기업 스크리너 & 유니버스",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="auto",
)


# =====================================================================
# 보안 인증 (Streamlit Community Cloud 배포 시 비공개 유지)
# =====================================================================
def check_password() -> bool:
    """Streamlit Secrets에 APP_PASSWORD가 있을 때만 비공개 로그인 화면 노출"""
    try:
        has_secret = "APP_PASSWORD" in st.secrets
    except Exception:
        return True
    if not has_secret:
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
# 전역 모바일 반응형 & 타이포그래피 정돈 CSS 주입 (Material 아이콘 폰트 보존)
# =====================================================================
def inject_custom_css() -> None:
    st.markdown(
        """
        <style>
        /* 1. 전역 한글 가독성 설정 (단, Streamlit Material 아이콘 폰트 span은 절대 건드리지 않음) */
        html, body, p, label, table, th, td, h1, h2, h3, h4, .m-card-box {
            word-break: keep-all !important;
            font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Pretendard", "Segoe UI", Roboto, sans-serif;
        }
        /* Streamlit 아이콘(화살표 등) 폰트 보호: _arrow_right_, keyboard_double_arrow_left 글자 겹침 완벽 방지 */
        [data-testid="stIconMaterial"], .material-icons, span[translate="no"] {
            font-family: "Material Symbols Rounded", "Material Icons", sans-serif !important;
            word-break: normal !important;
        }

        /* 2. 제목/헤더 모바일 반응형 폰트 스케일링 & 행간 최적화 */
        h1 {
            font-size: clamp(1.25rem, 4.8vw, 1.85rem) !important;
            line-height: 1.25 !important;
            font-weight: 800 !important;
            letter-spacing: -0.02em !important;
            margin-bottom: 0.25rem !important;
        }
        h2 {
            font-size: clamp(1.1rem, 3.8vw, 1.45rem) !important;
            line-height: 1.3 !important;
            font-weight: 700 !important;
        }
        h3 {
            font-size: clamp(1.0rem, 3.2vw, 1.25rem) !important;
            line-height: 1.3 !important;
            font-weight: 700 !important;
        }
        h4 {
            font-size: clamp(0.9rem, 2.8vw, 1.1rem) !important;
            font-weight: 600 !important;
        }

        /* 3. 화면 최상단 헤더 바에 버튼/제목이 잘리지 않도록 충분한 상단 여백(3.8rem) 확보 */
        .block-container {
            padding-top: 3.8rem !important;
            padding-bottom: 2.5rem !important;
            padding-left: 1.0rem !important;
            padding-right: 1.0rem !important;
            max-width: 100% !important;
        }

        /* 4. Streamlit 메트릭(st.metric) 들쭉날쭉함 교정 */
        [data-testid="stMetricValue"] {
            font-size: clamp(1.15rem, 3.8vw, 1.45rem) !important;
            font-weight: 700 !important;
            line-height: 1.2 !important;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.8rem !important;
            color: #475569 !important;
            white-space: nowrap !important;
        }
        [data-testid="stMetricDelta"] {
            font-size: 0.75rem !important;
        }

        /* 5. 탭(Tabs) 모바일 가로 스크롤 및 컴팩트 폰트 */
        div[data-baseweb="tab-list"] {
            gap: 6px !important;
            overflow-x: auto !important;
            flex-wrap: nowrap !important;
            scrollbar-width: thin;
        }
        button[data-baseweb="tab"] {
            padding: 8px 16px !important;
            font-size: 0.92rem !important;
            font-weight: 700 !important;
            white-space: nowrap !important;
        }

        /* 6. 퍼널 관문 가로 스크롤 스텝 바 */
        .funnel-scroll-bar {
            display: flex;
            align-items: center;
            gap: 6px;
            overflow-x: auto;
            padding: 4px 2px 10px 2px;
            scrollbar-width: thin;
            -webkit-overflow-scrolling: touch;
        }
        .funnel-step-chip {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            padding: 4px 8px;
            font-size: 0.78rem;
            white-space: nowrap;
            color: #334155;
            flex-shrink: 0;
        }
        .funnel-step-chip.active {
            background: #eff6ff;
            border: 1.5px solid #2563eb;
            color: #1d4ed8;
            font-weight: 700;
        }
        .funnel-arrow-sep {
            color: #94a3b8;
            font-size: 0.75rem;
            flex-shrink: 0;
        }

        /* 7. 모바일 카드 전용 스타일 */
        .m-card-box {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            padding: 12px 14px;
            margin-bottom: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.03);
        }
        .m-card-box.in-universe {
            border: 1.5px solid #f59e0b;
            background: #fffdf9;
        }
        .m-card-header-row {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            border-bottom: 1px solid #f1f5f9;
            padding-bottom: 6px;
            margin-bottom: 8px;
        }
        .m-company-title {
            font-size: 1.05rem;
            font-weight: 700;
            color: #0f172a;
        }
        .m-company-meta {
            font-size: 0.75rem;
            color: #64748b;
            text-align: right;
            white-space: nowrap;
        }
        .m-dcf-strip {
            background: #fff7ed;
            border: 1px solid #fed7aa;
            border-radius: 6px;
            padding: 6px 10px;
            margin-bottom: 8px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .m-grid-2x2-tiles {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 6px;
            margin-bottom: 8px;
        }
        .m-tile-item {
            background: #f8fafc;
            border: 1px solid #f1f5f9;
            border-radius: 6px;
            padding: 6px 8px;
            text-align: center;
        }
        .m-tile-item-lbl {
            font-size: 0.72rem;
            color: #64748b;
            margin-bottom: 2px;
            white-space: nowrap;
        }
        .m-tile-item-val {
            font-size: 0.95rem;
            font-weight: 700;
            color: #1e293b;
        }
        .m-tile-item-sub {
            font-size: 0.71rem;
            color: #2563eb;
            font-weight: 600;
            margin-top: 2px;
        }
        .memo-url-chip {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            background: #eff6ff;
            border: 1px solid #bfdbfe;
            color: #1d4ed8 !important;
            text-decoration: none !important;
            padding: 3px 9px;
            border-radius: 14px;
            font-size: 0.76rem;
            font-weight: 600;
            margin-right: 6px;
            margin-top: 4px;
        }
        .memo-url-chip:hover {
            background: #dbeafe;
        }
        .pass-badge-ok {
            display: inline-block;
            background: #dcfce7;
            color: #166534;
            font-size: 0.73rem;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 12px;
        }
        .pass-badge-warn {
            display: inline-block;
            background: #fef3c7;
            color: #92400e;
            font-size: 0.73rem;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 12px;
        }
        .pass-badge-fail {
            display: inline-block;
            background: #fee2e2;
            color: #991b1b;
            font-size: 0.73rem;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 12px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


inject_custom_css()


# =====================================================================
# 유틸리티 함수: 숫자 포맷팅, URL 추출, 엑셀 다운로드
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


def extract_urls_from_text(text: str) -> List[str]:
    """메모 텍스트 내의 http:// 또는 https:// 웹 URL을 자동 추출합니다."""
    if not text:
        return []
    pattern = r"https?://[^\s<>\"')\]}]+"
    return re.findall(pattern, text)


def render_memo_with_links_html(memo_text: str) -> str:
    """메모 텍스트와 그 안에 포함된 웹 URL(구글독스 등) 바로가기 버튼 HTML을 생성합니다."""
    if not memo_text or not str(memo_text).strip():
        return "<div style='font-size:0.76rem; color:#94a3b8;'>작성된 메모가 없습니다.</div>"

    escaped_memo = html.escape(str(memo_text)).replace("\n", "<br>")
    urls = extract_urls_from_text(str(memo_text))
    links_html = ""
    if urls:
        chips = []
        for idx, u in enumerate(urls, 1):
            domain_label = "구글 독스/시트" if "docs.google.com" in u else (
                "노션(Notion)" if "notion." in u else f"웹 링크 #{idx}"
            )
            safe_u = html.escape(u, quote=True)
            chips.append(
                f"<a class='memo-url-chip' href='{safe_u}' target='_blank' rel='noopener noreferrer'>🔗 {domain_label} 열기 ↗</a>"
            )
        links_html = "<div style='margin-top:4px;'>" + "".join(chips) + "</div>"

    return (
        f"<div style='background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:7px 10px; margin:6px 0;'>"
        f"<div style='font-size:0.78rem; color:#1e293b; line-height:1.45;'>📝 {escaped_memo}</div>"
        f"{links_html}"
        f"</div>"
    )


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Screening_Result")
    return output.getvalue()


def open_company_detail(symbol: str, return_tab: str = "screener") -> None:
    """카드 또는 테이블 행 클릭 시 해당 기업의 상세 페이지 뷰로 즉시 전환합니다."""
    st.session_state["selected_symbol"] = symbol
    st.session_state["detail_view_symbol"] = symbol
    st.session_state["detail_return_tab"] = return_tab
    st.session_state["clear_screener_selection"] = True
    st.session_state["clear_universe_selection"] = True


def close_company_detail() -> None:
    """상세 페이지에서 이전 목록(스크리너 또는 유니버스 보관함)으로 복귀합니다."""
    st.session_state["detail_view_symbol"] = None


# =====================================================================
# 지표별 계산 공식 및 설명 사전 (SSOT & ⓘ 호버 툴팁)
# =====================================================================
METRIC_DEFINITIONS: Dict[str, Dict[str, str]] = {
    "GPM (%)": {
        "title": "🎯 매출총이익률 (GPM, Gross Profit Margin)",
        "formula": "(매출총이익 / 매출액) × 100\n• 다개년 평균: 최근 가용 4~5개년 GPM의 산술평균",
        "desc": "원가 경쟁력과 가격 결정력(Pricing Power)의 1차 방어선. 최근 수치와 4~5년 평균을 함께 보아 일시적 호황인지 구조적 해자인지 판별합니다.",
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
        "formula": "설정 옵션에 따름:\n• [권장 A (세후 일치)]: (OCF - CapEx) / 당기순이익 × 100\n• [권장 B (테리 스미스)]: (OCF + 법인세 - CapEx) / 영업이익 × 100\n• [대안 C (단순)]: (OCF - CapEx) / 영업이익 × 100\n• [대안 D (CapEx 미차감)]: OCF / 영업이익 × 100",
        "desc": "장부상 보고된 회계 이익이 실제 기업 통장에 꽂히는 잉여현금흐름(FCF)으로 얼마나 전환되는지 측정하는 '이익의 질(Quality of Earnings)' 지표입니다.",
        "icon": "🎯",
    },
    "CapEx/감가상각비 (%)": {
        "title": "📎 CapEx / 감가상각비 (D&A) 비율",
        "formula": "(자본적지출(CapEx) / 감가상각비(D&A)) × 100",
        "desc": "100% 초과 시 신규 증설·확장 투자가 활발함을 의미하며, 100% 미만 시 유지보수 위주의 자산 경량(Asset-light) 사업임을 의미합니다.",
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
        "title": "📎 정상화 FCF 수익률 (최근 vs 4~5년 당시 시총 대비 평균)",
        "formula": "• 최근 FCF 수익률 = (최근 결산 정상화 FCF / 현재 시가총액) × 100\n• 4~5년 평균 FCF 수익률 = 각 결산연도별 (당시 정상화 FCF / 결산 당시 시가총액)의 4~5년 평균",
        "desc": "과거 4~5년 동안 이 기업이 결산일 당시 시가총액 대비 평균 몇 %의 FCF 수익률(밸류에이션)에서 거래되었는지와 현재 FCF 수익률을 직접 비교합니다.",
        "icon": "📎",
    },
    "역DCF 기대성장률 (%)": {
        "title": "🔥 역DCF 내포 기대성장률 (최근 vs 과거 평균 밸류에이션)",
        "formula": "① 최근 역DCF g = 요구수익률(r) - 최근 FCF 수익률(현재시총 기준)\n② 4~5년 평균 역DCF g = 요구수익률(r) - 4~5년 평균 FCF 수익률(각 결산 당시 시총 기준)\n③ N년 성장 정밀 역DCF (유니버스/상세페이지): N년 뒤 성장 둔화(g2) 가정 시 현재 시총을 정당화하는 1~N년 요구성장률 역산",
        "desc": "과거 4~5년간 시장이 이 기업에 평균적으로 요구했던 기대성장률과 현재 주가에 내포된 기대성장률을 비교하여 현재의 저평가/고평가 정도를 파악합니다.",
        "icon": "🔥",
    },
}


def get_metric_tooltip(metric_key: str) -> str:
    """Streamlit 위젯의 help 파라미터용 텍스트 반환"""
    info = METRIC_DEFINITIONS.get(metric_key)
    if not info:
        return ""
    return f"📐 [계산 공식]\n{info['formula']}\n\n💡 [지표 설명]\n{info['desc']}"


def render_hover_chips_guide() -> None:
    """마우스를 올리면(호버) 지표 계산 공식과 설명이 풍선처럼 나타나는 퀵 가이드 칩 바"""
    key_metrics = [
        ("GPM (%)", "🎯 GPM (최근/평균) ⓘ"),
        ("ROCE (%)", "🎯 ROCE (최근/평균) ⓘ"),
        ("CCR (%)", "🎯 CCR (최근/평균) ⓘ"),
        ("이자보상배율", "🎯 이자보상배율 ⓘ"),
        ("역DCF 기대성장률 (%)", "🔥 역DCF (현재 vs 과거평균) ⓘ"),
        ("정상화 FCF 수익률 (%)", "📎 FCF 수익률 (당시시총 평균) ⓘ"),
        ("OPM (%)", "📎 OPM ⓘ"),
        ("CapEx/감가상각비 (%)", "📎 CapEx/D&A ⓘ"),
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
        padding: 10px 14px;
        margin: 6px 0 14px 0;
        position: relative;
        z-index: 9999;
        overflow: visible;
    }}
    .metric-guide-header {{
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 0.82rem;
        font-weight: 700;
        color: #334155;
        margin-bottom: 6px;
    }}
    .metric-guide-chips {{
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        overflow: visible;
    }}
    .hover-metric-chip {{
        position: relative;
        display: inline-flex;
        align-items: center;
        background: #ffffff;
        border: 1px solid #cbd5e1;
        border-radius: 16px;
        padding: 3px 10px;
        font-size: 0.78rem;
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
    .hover-tooltip-card {{
        visibility: hidden;
        opacity: 0;
        position: absolute;
        bottom: calc(100% + 9px);
        left: 0;
        width: 340px;
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
    .hover-tooltip-card::after {{
        content: '';
        position: absolute;
        top: 100%;
        left: 20px;
        border-width: 6px;
        border-style: solid;
        border-color: #0f172a transparent transparent transparent;
    }}
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
        font-size: 0.75rem;
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
            <span>💡 <b>지표 계산 공식 퀵 가이드</b> (마우스를 올리면 계산식과 투자 해석이 나타납니다)</span>
        </div>
        <div class="metric-guide-chips">
            {all_chips}
        </div>
    </div>
    """
    st.html(html_content)


# =====================================================================
# 사이드바: 1. 시장 선택 & 실시간 주가 갱신 & 데이터 수집 관리
# =====================================================================
st.sidebar.title("🎯 퀄리티 스크리너 설정")

universe_store = de.load_universe_store()
st.sidebar.info(f"⭐ **나의 유니버스 보관함**: 현재 **{len(universe_store)}개** 기업 보관 중")

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
    )
elif market_choice.startswith("US"):
    selected_market = "US"
    sub_market_choice = st.sidebar.selectbox(
        "🏛️ 세부 시장 (나스닥 / NYSE)",
        options=["전체 (나스닥 + NYSE)", "US (NASDAQ)", "US (NYSE)"],
        index=0,
    )
else:
    selected_market = "ALL"
    sub_market_choice = st.sidebar.selectbox(
        "🏛️ 세부 시장 (거래소 선택)",
        options=["전체 시장", "KR (KOSPI)", "KR (KOSDAQ)", "US (NASDAQ)", "US (NYSE)"],
        index=0,
    )

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
    st.caption("수집 시 각 기업의 최근 결산 데이터와 최근 4~5개년 히스토리(각 결산일 당시 시가총액 포함)를 한 번에 모두 모아 저장합니다.")
    fetch_target_mkt = st.selectbox("수집할 시장 선택", ["KR", "US"], index=0 if selected_market != "US" else 1)

    if fetch_target_mkt == "KR":
        min_mcap_uk = st.number_input("최소 시가총액 (억 원)", min_value=500, max_value=100000, value=2000, step=500)
        min_mcap_raw = float(min_mcap_uk) * 1e8
    else:
        min_mcap_bil = st.number_input("최소 시가총액 ($B, 십억 달러)", min_value=1.0, max_value=500.0, value=10.0, step=1.0)
        min_mcap_raw = float(min_mcap_bil) * 1e9

    max_fetch_cnt = st.slider("수집할 최대 기업 수 (시총 상위순)", min_value=30, max_value=300, value=150, step=10)
    pre_gpm_cut = st.number_input("1차 서버 프리필터: 최소 GPM (%)", min_value=0, max_value=80, value=25, step=5)

    if st.button("🚀 5개년 재무제표 새로 수집", use_container_width=True):
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
            prog_bar = st.progress(0, text=f"0 / {len(uni_items)} 기업 5개년 재무제표 수집 중...")

            def _update_prog(done: int, total: int) -> None:
                prog_bar.progress(done / total, text=f"{done} / {total} 기업 5개년 재무제표 & 당시 시총 파싱 중...")

            new_df = de.fetch_batch_raw_financials(uni_items, max_workers=12, progress_callback=_update_prog)
            de.save_raw_cache(new_df, fetch_target_mkt)
            prog_bar.empty()
            st.success(f"{fetch_target_mkt} 시장 {len(new_df)}개 기업 (최근+5개년+당시시총) 저장 완료!")
            st.rerun()

    st.markdown("---")
    custom_tickers_input = st.text_input(
        "➕ 개별 종목 직접 추가 (쉼표 구분)",
        placeholder="예: 058470.KQ, 340570.KQ, MSFT, VLTO",
        help="한국 코스피는 .KS, 코스닥은 .KQ를 붙이거나 6자리 숫자만 입력하세요.",
    )
    add_directly_to_universe = st.checkbox("추가와 동시에 ⭐ 유니버스 보관함에도 넣기", value=True)
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
                        if add_directly_to_universe:
                            de.upsert_universe_item(tk_info["symbol"], tk_info["name"], "KR")
                        break
            elif tok.endswith(".KS") or tok.endswith(".KQ"):
                base_c = tok.split(".")[0]
                tk_info = de.fetch_single_stock_raw(
                    {"symbol": tok, "name": krx_map.get(base_c, {}).get("name", tok), "market": "KR", "currency": "KRW"}
                )
                if tk_info is not None:
                    kr_add_items.append(tk_info)
                    if add_directly_to_universe:
                        de.upsert_universe_item(tk_info["symbol"], tk_info["name"], "KR")
            else:
                tk_info = de.fetch_single_stock_raw(
                    {"symbol": tok, "name": tok, "market": "US", "currency": "USD"}
                )
                if tk_info is not None:
                    us_add_items.append(tk_info)
                    if add_directly_to_universe:
                        de.upsert_universe_item(tk_info["symbol"], tk_info["name"], "US")

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
    help="기본 영구 역DCF(g = r - FCF Yield) 및 유니버스 기업별 N년 정밀 2단계 역DCF의 할인율(요구수익률)로 사용됩니다.",
)

deduct_cash_opt = st.sidebar.checkbox(
    "사용자본(CE)에서 현금성자산 차감",
    value=False,
    help="체크 시 (총자산 - 유동부채 - 현금및단기금융상품)으로 현금 부자 기업의 실질 ROCE(최근 및 다개년 평균 모두)를 계산합니다.",
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
)


# =====================================================================
# 사이드바: 3. 4대 핵심 필터 & 자유 추가 조건 설정
# =====================================================================
st.sidebar.markdown("---")
st.sidebar.subheader("🔍 1. 핵심 4대 필터 설정")
st.sidebar.caption("기준 수치를 설정하세요. 우측 화면에서 모든 조건 통과 / 아깝게 1개 조건 미달 / 전체 종목을 바로 전환해 볼 수 있습니다.")

# [필터 1] GPM
st.sidebar.markdown("**① 매출총이익률 (`GPM (%)`) ⓘ**", help=get_metric_tooltip("GPM (%)"))
c1, c2, c3 = st.sidebar.columns([1.2, 1.3, 2.0])
use_gpm = c1.checkbox("적용", value=True, key="chk_gpm")
op_gpm = c2.selectbox("연산", [">=", "<=", ">", "<"], index=0, key="op_gpm", label_visibility="collapsed")
val_gpm = c3.number_input("GPM 기준(%)", value=40.0, step=5.0, key="val_gpm", label_visibility="collapsed")

# [필터 2] ROCE
st.sidebar.markdown("**② 사용자본이익률 (`ROCE (%)`) ⓘ**", help=get_metric_tooltip("ROCE (%)"))
c1, c2, c3 = st.sidebar.columns([1.2, 1.3, 2.0])
use_roce = c1.checkbox("적용", value=True, key="chk_roce")
op_roce = c2.selectbox("연산", [">=", "<=", ">", "<"], index=0, key="op_roce", label_visibility="collapsed")
val_roce = c3.number_input("ROCE 기준(%)", value=15.0, step=2.5, key="val_roce", label_visibility="collapsed")

# [필터 3] CCR
st.sidebar.markdown("**③ 현금전환율 (`CCR (%)`) ⓘ**", help=get_metric_tooltip("CCR (%)"))
c1, c2, c3 = st.sidebar.columns([1.2, 1.3, 2.0])
use_ccr = c1.checkbox("적용", value=True, key="chk_ccr")
op_ccr = c2.selectbox("연산", [">=", "<=", ">", "<"], index=0, key="op_ccr", label_visibility="collapsed")
val_ccr = c3.number_input("CCR 기준(%)", value=95.0, step=5.0, key="val_ccr", label_visibility="collapsed")

# [필터 4] 이자보상배율
st.sidebar.markdown("**④ 이자보상배율 (`배`) ⓘ**", help=get_metric_tooltip("이자보상배율"))
c1, c2, c3 = st.sidebar.columns([1.2, 1.3, 2.0])
use_icr = c1.checkbox("적용", value=True, key="chk_icr")
op_icr = c2.selectbox("연산", [">=", "<=", ">", "<"], index=0, key="op_icr", label_visibility="collapsed")
val_icr = c3.number_input("이자보상 기준(배)", value=10.0, step=5.0, key="val_icr", label_visibility="collapsed")

with st.sidebar.expander("➕ 참고 지표 / 역DCF 추가 필터링 (선택)", expanded=False):
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
                    "short_name": m_sel.split(" ")[0],
                }
            )


# =====================================================================
# 데이터 로드 및 계산 수행
# =====================================================================
all_raw_df = pd.concat([de.load_raw_cache("KR"), de.load_raw_cache("US")], ignore_index=True)

if selected_market == "KR":
    raw_df = de.load_raw_cache("KR")
elif selected_market == "US":
    raw_df = de.load_raw_cache("US")
else:
    raw_df = all_raw_df.copy()

if raw_df is None or raw_df.empty:
    st.title("🎯 한·미 퀄리티 기업 스크리너 & 유니버스")
    st.info("로컬 캐시 데이터가 없습니다. 아래 버튼을 눌러 기본 유니버스를 수집하세요.")
    if st.button("⚡ 기본 유니버스(한국/미국 주요 종목) 지금 바로 수집하기"):
        with st.spinner("한국 및 미국 주요 상장사 5개년 재무제표를 수집하고 있습니다 (약 15~20초 소요)..."):
            kr_items = de.fetch_universe_symbols("KR", min_market_cap=200_000_000_000, max_count=150, only_profitable=True, pre_filter_gpm=25)
            kr_data = de.fetch_batch_raw_financials(kr_items, max_workers=12)
            de.save_raw_cache(kr_data, "KR")

            us_items = de.fetch_universe_symbols("US", min_market_cap=15_000_000_000, max_count=120, only_profitable=True, pre_filter_gpm=30)
            us_data = de.fetch_batch_raw_financials(us_items, max_workers=12)
            de.save_raw_cache(us_data, "US")
            st.rerun()
    st.stop()

all_metrics_df = de.compute_quality_metrics(
    all_raw_df,
    deduct_cash_from_ce=deduct_cash_opt,
    ccr_denominator=ccr_denom_key,
    allow_missing_gpm_as_opm=allow_missing_gpm,
    required_return_pct=required_return_r,
)

if selected_market in ["KR", "US"]:
    metrics_df = all_metrics_df[all_metrics_df["market"] == selected_market].reset_index(drop=True)
else:
    metrics_df = all_metrics_df.copy()

if sub_market_choice and not sub_market_choice.startswith("전체"):
    metrics_df = metrics_df[metrics_df["market_display"] == sub_market_choice].reset_index(drop=True)


# =====================================================================
# 🏢 [기업 심층 상세 페이지] 렌더링 함수 (카드/테이블 클릭 시 즉시 전환)
# =====================================================================
def render_company_detail_page(symbol: str) -> None:
    """
    카드나 테이블 행을 클릭했을 때 전환되는 개별 기업 심층 분석 & 유니버스/2단계 역DCF 설정 페이지
    """
    match_rows = all_metrics_df[all_metrics_df["symbol"] == symbol]
    if match_rows.empty:
        st.warning(f"선택한 종목(`{symbol}`) 데이터를 찾을 수 없습니다.")
        if st.button("⬅️ 목록으로 돌아가기"):
            close_company_detail()
            st.rerun()
        return

    row_data = match_rows.iloc[0]
    mkt_code = str(row_data["market"]).upper()
    mkt_disp = row_data.get("market_display", row_data["market"])
    comp_name = str(row_data["name"])

    uni_store = de.load_universe_store()
    in_uni = symbol in uni_store
    uni_info = uni_store.get(symbol, {})

    # 다개년 데이터 먼저 로드 (결산 당시 시가총액 및 FCF 성장률 자동 보강 포함)
    hist_json_str = row_data.get("history_json", None)
    df_multi = de.fetch_stock_multiyear_data(
        symbol=symbol,
        market=mkt_code,
        ccr_denominator=ccr_denom_key,
        deduct_cash_from_ce=deduct_cash_opt,
        allow_missing_gpm_as_opm=allow_missing_gpm,
        max_years=5,
        cached_history_json=hist_json_str if isinstance(hist_json_str, str) else None,
        current_market_cap=row_data.get("market_cap", np.nan),
        current_price=row_data.get("price", np.nan),
    )

    avg_yr_cnt = len(df_multi) if not df_multi.empty else int(row_data.get("평균_연도수", 1))
    if not df_multi.empty:
        fcf_cagr_num, fcf_cagr_str = de.compute_fcf_cagr_info(df_multi["norm_fcf"].tolist())
        hist_fcf_yield_avg = df_multi["당시시총_FCF수익률 (%)"].mean(skipna=True)
    else:
        fcf_cagr_num, fcf_cagr_str = row_data.get("FCF_CAGR_5Y (%)", np.nan), str(row_data.get("FCF_CAGR_표시", "N/A"))
        hist_fcf_yield_avg = row_data.get("정상화 FCF 수익률_5Y (%)", np.nan)

    # 최상단 네비게이션 & 다른 기업 빠른 전환 바
    nav_c1, nav_c2, nav_c3 = st.columns([2.3, 4.7, 2.0])
    with nav_c1:
        ret_label = "⭐ 유니버스 보관함으로 돌아가기" if st.session_state.get("detail_return_tab") == "universe" else "⬅️ 스크리너 목록으로 돌아가기"
        if st.button(ret_label, type="secondary", use_container_width=True):
            close_company_detail()
            st.rerun()
    with nav_c2:
        all_sym_options = [
            f"{'⭐ ' if r['symbol'] in uni_store else ''}{r['name']} ({r['symbol']}) - {r.get('시가총액_표시', '')}"
            for _, r in all_metrics_df.iterrows()
        ]
        sym_lookup = {opt: r["symbol"] for opt, (_, r) in zip(all_sym_options, all_metrics_df.iterrows())}
        cur_idx = next((i for i, (_, r) in enumerate(all_metrics_df.iterrows()) if r["symbol"] == symbol), 0)
        jumped_opt = st.selectbox(
            "다른 기업 바로 보기",
            options=all_sym_options,
            index=cur_idx,
            label_visibility="collapsed",
        )
        if sym_lookup.get(jumped_opt) and sym_lookup[jumped_opt] != symbol:
            open_company_detail(sym_lookup[jumped_opt], st.session_state.get("detail_return_tab", "screener"))
            st.rerun()
    with nav_c3:
        if in_uni:
            if st.button("✅ 유니버스 보관중 (제거)", use_container_width=True):
                de.remove_universe_item(symbol)
                st.toast(f"🗑️ {comp_name} 종목을 유니버스 보관함에서 제거했습니다.")
                st.rerun()
        else:
            if st.button("⭐ 유니버스 보관함에 추가", type="primary", use_container_width=True):
                de.upsert_universe_item(symbol=symbol, name=comp_name, market=mkt_code)
                st.toast(f"⭐ {comp_name} 종목을 유니버스 보관함에 담았습니다!")
                st.rerun()

    st.markdown(
        f"## 🏢 {comp_name} (`{symbol}`) {'⭐' if in_uni else ''}\n"
        f"**시장**: `{mkt_disp}` | **최근 결산일**: `{row_data['fiscal_date']}` | **현재 시가총액**: `{row_data['시가총액_표시']}`"
    )

    # -----------------------------------------------------------------
    # 섹션 A: 유니버스 메모 & 웹 URL (구글 독스 등) 보관 박스
    # -----------------------------------------------------------------
    with st.container(border=True):
        st.markdown("#### 📝 기업 분석 메모 & 웹 링크 (구글 독스 URL 등) 보관함")
        st.caption("메모 안에 `https://docs.google.com/...` 등 웹 주소를 적어두면 아래에 원클릭 바로가기 버튼이 자동으로 생성됩니다. 저장 시 자동으로 ⭐ 유니버스에 보관됩니다.")
        cur_memo = uni_info.get("memo", "")
        new_memo = st.text_area(
            "메모 및 분석 문서 URL",
            value=cur_memo,
            height=90,
            placeholder="예: [핵심 투자포인트] 반도체 테스트 소켓 독점력 & 순현금 재무구조\n분석 리포트: https://docs.google.com/document/d/...",
            key=f"detail_memo_{symbol}",
            label_visibility="collapsed",
        )
        mc1, mc2 = st.columns([2.2, 6.8])
        with mc1:
            if st.button("💾 메모 저장 (유니버스 반영)", key=f"btn_save_memo_{symbol}", type="primary", use_container_width=True):
                de.upsert_universe_item(
                    symbol=symbol,
                    name=comp_name,
                    market=mkt_code,
                    memo=new_memo,
                )
                st.toast(f"✅ {comp_name} 메모 및 링크가 유니버스에 저장되었습니다!")
                st.rerun()
        with mc2:
            urls_found = extract_urls_from_text(new_memo)
            if urls_found:
                st.markdown(render_memo_with_links_html(new_memo), unsafe_allow_html=True)

    # -----------------------------------------------------------------
    # 섹션 B: 최근 수치 vs 다개년 평균 지표 + [정상화 FCF 다개년 성장률(CAGR)] 카드
    # -----------------------------------------------------------------
    st.markdown(f"#### 📊 1️⃣ 핵심 퀄리티 지표 (`최근` vs `{avg_yr_cnt}개년 평균`) & 정상화 FCF 성장률")
    gpm_now, gpm_5y = row_data.get("GPM (%)", np.nan), row_data.get("GPM_5Y (%)", np.nan)
    opm_now, opm_5y = row_data.get("OPM (%)", np.nan), row_data.get("OPM_5Y (%)", np.nan)
    roce_now, roce_5y = row_data.get("ROCE (%)", np.nan), row_data.get("ROCE_5Y (%)", np.nan)
    ccr_now, ccr_5y = row_data.get("CCR (%)", np.nan), row_data.get("CCR_5Y (%)", np.nan)
    fcf_y_now = row_data.get("정상화 FCF 수익률 (%)", np.nan)

    def _f_pct(v: float) -> str:
        return f"{v:.1f}%" if pd.notna(v) else "N/A"

    summary_cards_html = f"""
    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(155px, 1fr)); gap:8px; margin-bottom:12px;">
        <div class="m-tile-item" style="padding:10px; border-top:3px solid #2563eb;">
            <div class="m-tile-item-lbl">🎯 GPM (매출총이익률)</div>
            <div class="m-tile-item-val" style="font-size:1.12rem;">최근 {_f_pct(gpm_now)}</div>
            <div class="m-tile-item-sub">{avg_yr_cnt}년 평균: {_f_pct(gpm_5y)}</div>
        </div>
        <div class="m-tile-item" style="padding:10px; border-top:3px solid #059669;">
            <div class="m-tile-item-lbl">📎 OPM (영업이익률)</div>
            <div class="m-tile-item-val" style="font-size:1.12rem;">최근 {_f_pct(opm_now)}</div>
            <div class="m-tile-item-sub">{avg_yr_cnt}년 평균: {_f_pct(opm_5y)}</div>
        </div>
        <div class="m-tile-item" style="padding:10px; border-top:3px solid #dc2626;">
            <div class="m-tile-item-lbl">🎯 ROCE (사용자본이익률)</div>
            <div class="m-tile-item-val" style="font-size:1.12rem;">최근 {_f_pct(roce_now)}</div>
            <div class="m-tile-item-sub">{avg_yr_cnt}년 평균: {_f_pct(roce_5y)}</div>
        </div>
        <div class="m-tile-item" style="padding:10px; border-top:3px solid #7c3aed;">
            <div class="m-tile-item-lbl">🎯 CCR (현금전환율)</div>
            <div class="m-tile-item-val" style="font-size:1.12rem;">최근 {_f_pct(ccr_now)}</div>
            <div class="m-tile-item-sub">{avg_yr_cnt}년 평균: {_f_pct(ccr_5y)}</div>
        </div>
        <div class="m-tile-item" style="padding:10px; border-top:3px solid #d97706; background:#fffbeb;">
            <div class="m-tile-item-lbl" style="color:#b45309; font-weight:700;">📈 {avg_yr_cnt}개년 FCF 연평균 성장률</div>
            <div class="m-tile-item-val" style="font-size:1.08rem; color:#92400e;">{html.escape(fcf_cagr_str)}</div>
            <div class="m-tile-item-sub" style="color:#b45309;">당시시총 대비 FCF수익률 평균: {_f_pct(hist_fcf_yield_avg)}</div>
        </div>
        <div class="m-tile-item" style="padding:10px; border-top:3px solid #475569;">
            <div class="m-tile-item-lbl">🎯 이자보상배율</div>
            <div class="m-tile-item-val" style="font-size:1.02rem;">{html.escape(str(row_data.get('이자보상배율_표시', 'N/A')))}</div>
            <div class="m-tile-item-sub" style="color:#64748b;">현재 FCF수익률: {_f_pct(fcf_y_now)}</div>
        </div>
    </div>
    """
    st.markdown(summary_cards_html, unsafe_allow_html=True)

    # -----------------------------------------------------------------
    # 섹션 C: 정밀 2단계(Two-Stage) 역DCF & 내재가치 시뮬레이터 (기업별 성장기간 지정)
    # -----------------------------------------------------------------
    st.markdown("#### 🔥 2️⃣ 기업별 맞춤 성장기간($N$년) 정밀 2단계 역DCF & 내재가치 계산기")
    with st.container(border=True):
        st.caption(
            f"💡 **과거 실제 FCF 성장률(`{fcf_cagr_str}`)**과 **현재 주가에 내포된 $N$년 역DCF 요구성장률**을 비교해 보세요. "
            f"향후 $N$년 동안만 성장하고 이후 성숙기 영구성장률($g_2$, 기본 0%)로 둔화되어 밸류에이션이 낮아지는(말기 FCF 수익률 $= r - g_2$) 정밀 2단계 할인모델입니다."
        )

        p_col1, p_col2, p_col3, p_col4, p_col5 = st.columns([1.9, 1.4, 1.6, 1.6, 1.8])
        with p_col1:
            fcf_base_choice = st.radio(
                "기준 정상화 FCF 선택",
                options=["최근 결산 FCF", f"{avg_yr_cnt}개년 평균 FCF"],
                index=0,
                key=f"fcf_base_{symbol}",
            )
        with p_col2:
            n_years_input = st.number_input(
                "⏳ 성장 지속기간 N (년)",
                min_value=1,
                max_value=40,
                value=int(uni_info.get("growth_years", 10)),
                step=1,
                key=f"n_yr_{symbol}",
                help="경쟁우위 지속기간(CAP). 예: 10년 또는 15년",
            )
        with p_col3:
            g1_est_input = st.number_input(
                "📈 성장기간 예상 성장률 g1 (%)",
                min_value=-30.0,
                max_value=100.0,
                value=float(uni_info.get("growth_rate_est", 10.0)),
                step=1.0,
                key=f"g1_est_{symbol}",
                help="향후 N년 동안 내가 예상하는 연평균 FCF 복리 성장률(%)",
            )
        with p_col4:
            g2_term_input = st.number_input(
                "⚓ N년 이후 영구성장률 g2 (%)",
                min_value=-10.0,
                max_value=float(required_return_r - 0.5),
                value=float(uni_info.get("terminal_growth_rate", 0.0)),
                step=0.5,
                key=f"g2_term_{symbol}",
                help="N년 이후 성숙기 영구성장률. 0%로 설정 시 N년 뒤 적정 FCF 수익률은 요구수익률 r(10%)과 같아집니다.",
            )
        with p_col5:
            st.write("")
            if st.button("💾 이 성장가정을 유니버스에 저장", key=f"save_dcf_params_{symbol}", use_container_width=True):
                de.upsert_universe_item(
                    symbol=symbol,
                    name=comp_name,
                    market=mkt_code,
                    memo=new_memo,
                    growth_years=int(n_years_input),
                    growth_rate_est=float(g1_est_input),
                    terminal_growth_rate=float(g2_term_input),
                )
                st.toast(f"⭐ {comp_name}의 성장기간({n_years_input}년) 및 성장률 가정이 유니버스에 저장되었습니다!")
                st.rerun()

        base_fcf = row_data.get("norm_fcf", np.nan) if fcf_base_choice == "최근 결산 FCF" else row_data.get("norm_fcf_5y", np.nan)
        cur_mcap = row_data.get("market_cap", np.nan)
        cur_fcf_yield = (base_fcf / cur_mcap * 100.0) if (pd.notna(base_fcf) and pd.notna(cur_mcap) and cur_mcap > 0) else np.nan
        perp_implied_g = (required_return_r - cur_fcf_yield) if pd.notna(cur_fcf_yield) else np.nan
        hist_implied_g = (required_return_r - hist_fcf_yield_avg) if pd.notna(hist_fcf_yield_avg) else np.nan

        two_stage_implied_g = de.solve_two_stage_implied_growth(
            fcf0=base_fcf,
            market_cap=cur_mcap,
            r_pct=required_return_r,
            n_years=int(n_years_input),
            g2_pct=float(g2_term_input),
        )

        dcf_res = de.calc_two_stage_dcf_value(
            fcf0=base_fcf,
            r_pct=required_return_r,
            n_years=int(n_years_input),
            g1_pct=float(g1_est_input),
            g2_pct=float(g2_term_input),
        )
        fair_mcap = dcf_res["intrinsic_value"]
        term_yield_pct = dcf_res["terminal_fcf_yield_pct"]
        upside_pct = ((fair_mcap / cur_mcap - 1.0) * 100.0) if (pd.notna(fair_mcap) and pd.notna(cur_mcap) and cur_mcap > 0) else np.nan

        fcf_str = format_currency_amount(base_fcf, mkt_code)
        yield_str = f"{cur_fcf_yield:.2f}%" if pd.notna(cur_fcf_yield) else "N/A"
        hist_yield_str = f"{hist_fcf_yield_avg:.2f}%" if pd.notna(hist_fcf_yield_avg) else "N/A"
        perp_g_str = f"{perp_implied_g:+.2f}%" if pd.notna(perp_implied_g) else "N/A"
        hist_g_str = f"{hist_implied_g:+.2f}%" if pd.notna(hist_implied_g) else "N/A"
        stage2_g_str = f"{two_stage_implied_g:+.2f}%" if pd.notna(two_stage_implied_g) else "산출불가 (FCF≤0)"
        fair_mcap_str = format_currency_amount(fair_mcap, mkt_code) if pd.notna(fair_mcap) else "N/A"
        upside_str = f"{upside_pct:+.1f}%" if pd.notna(upside_pct) else "N/A"
        term_yield_str = f"{term_yield_pct:.1f}%" if pd.notna(term_yield_pct) else "N/A"

        dcf_box_html = f"""
        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap:10px; margin-top:8px;">
            <div class="m-tile-item" style="padding:12px; border-left:4px solid #2563eb; text-align:left;">
                <div class="m-tile-item-lbl">① 현재 FCF 수익률 vs 과거 당시시총 평균</div>
                <div class="m-tile-item-val" style="font-size:1.08rem; color:#1d4ed8;">현재 {yield_str} <span style="font-size:0.82rem; color:#475569;">(과거평균 {hist_yield_str})</span></div>
                <div style="font-size:0.72rem; color:#64748b; margin-top:3px;">기준 FCF: {fcf_str} | 실제 FCF 성장률: {html.escape(fcf_cagr_str)}</div>
            </div>
            <div class="m-tile-item" style="padding:12px; border-left:4px solid #f59e0b; text-align:left;">
                <div class="m-tile-item-lbl">② 영구성장 역DCF 기대성장률 (∞)</div>
                <div class="m-tile-item-val" style="font-size:1.12rem; color:#b45309;">현재 {perp_g_str} <span style="font-size:0.8rem; color:#78716c;">(과거평균 {hist_g_str})</span></div>
                <div style="font-size:0.72rem; color:#78716c; margin-top:3px;">공식: r({required_return_r:.1f}%) - FCF 수익률</div>
            </div>
            <div class="m-tile-item" style="padding:12px; border-left:4px solid #dc2626; background:#fff7ed; text-align:left;">
                <div class="m-tile-item-lbl" style="color:#c2410c; font-weight:700;">③ 🔥 {int(n_years_input)}년 한정 정밀 역DCF 요구성장률</div>
                <div class="m-tile-item-val" style="font-size:1.22rem; color:#9a3412;">향후 {int(n_years_input)}년간 연 {stage2_g_str} 필요</div>
                <div style="font-size:0.72rem; color:#9a3412; margin-top:3px;">{int(n_years_input)}년 뒤 성장률 {g2_term_input:.1f}% 둔화 (말기 FCF수익률 {term_yield_str}) 가정</div>
            </div>
            <div class="m-tile-item" style="padding:12px; border-left:4px solid #059669; background:#f0fdf4; text-align:left;">
                <div class="m-tile-item-lbl" style="color:#047857; font-weight:700;">④ 💎 예상 성장률( 연 {g1_est_input:.1f}% ) 적용 적정 시총</div>
                <div class="m-tile-item-val" style="font-size:1.12rem; color:#065f46;">{fair_mcap_str} (괴리율 {upside_str})</div>
                <div style="font-size:0.72rem; color:#047857; margin-top:3px;">1~{int(n_years_input)}년 현가 {format_currency_amount(dcf_res['pv_stage1'], mkt_code)} + 말기가치 현가 {format_currency_amount(dcf_res['pv_terminal'], mkt_code)}</div>
            </div>
        </div>
        """
        st.markdown(dcf_box_html, unsafe_allow_html=True)

    st.markdown("---")

    # -----------------------------------------------------------------
    # 섹션 D: 최근 4~5개년 연도별 재무제표 (결산 당시 시가총액 & 당시 FCF 수익률 & FCF 성장률 포함)
    # -----------------------------------------------------------------
    if not df_multi.empty:
        st.markdown(f"#### 📈 3️⃣ 최근 {len(df_multi)}개년 연도별 궤적 & 다개년 평균 비교 (결산 당시 시총 & FCF 성장률 포함)")
        col_dates = df_multi["fiscal_date"].tolist()
        col_headers = []
        for idx, d in enumerate(col_dates):
            yr = d[:4]
            tag = " (최신)" if idx == len(col_dates) - 1 else ""
            col_headers.append(f"{yr}년{tag}")

        def _fmt_amt(v: float) -> str:
            return format_currency_amount(v, mkt_code)

        def _mean_str(series: pd.Series, fmt: str = "{:.1f}%") -> str:
            m = series.mean(skipna=True)
            return fmt.format(m) if pd.notna(m) else "N/A"

        def _mean_amt(series: pd.Series) -> str:
            m = series.mean(skipna=True)
            return _fmt_amt(m) if pd.notna(m) else "N/A"

        yoy_col = df_multi.get("정상화FCF_성장률_YoY (%)", pd.Series(np.nan, index=df_multi.index))
        hist_mcap_col = df_multi.get("hist_market_cap", pd.Series(np.nan, index=df_multi.index))
        hist_yield_col = df_multi.get("당시시총_FCF수익률 (%)", pd.Series(np.nan, index=df_multi.index))

        metric_rows = [
            ("🎯 GPM (매출총이익률)", [f"{v:.1f}%" if pd.notna(v) else "N/A" for v in df_multi["GPM (%)"]], _mean_str(df_multi["GPM (%)"])),
            ("📎 OPM (영업이익률)", [f"{v:.1f}%" if pd.notna(v) else "N/A" for v in df_multi["OPM (%)"]], _mean_str(df_multi["OPM (%)"])),
            ("🎯 ROCE (사용자본이익률)", [f"{v:.1f}%" if pd.notna(v) else "N/A" for v in df_multi["ROCE (%)"]], _mean_str(df_multi["ROCE (%)"])),
            ("  ↳ EBIT Margin (%)", [f"{v:.1f}%" if pd.notna(v) else "N/A" for v in df_multi["EBIT Margin (%)"]], _mean_str(df_multi["EBIT Margin (%)"])),
            ("  ↳ 사용자본회전율 (배)", [f"{v:.2f}배" if pd.notna(v) else "N/A" for v in df_multi["사용자본회전율 (배)"]], _mean_str(df_multi["사용자본회전율 (배)"], "{:.2f}배")),
            ("🎯 CCR (현금전환율)", [f"{v:.1f}%" if pd.notna(v) else "N/A" for v in df_multi["CCR (%)"]], _mean_str(df_multi["CCR (%)"])),
            ("  ↳ CapEx / 감가상각비 (%)", [f"{v:.0f}%" if pd.notna(v) else "N/A" for v in df_multi["CapEx/감가상각비 (%)"]], _mean_str(df_multi["CapEx/감가상각비 (%)"], "{:.0f}%")),
            ("  ↳ 운전자본변동 / EBIT (%)", [f"{v:+.1f}%" if pd.notna(v) else "N/A" for v in df_multi["운전자본변동/EBIT (%)"]], _mean_str(df_multi["운전자본변동/EBIT (%)"], "{:+.1f}%")),
            ("🎯 이자보상배율", df_multi["이자보상배율"].tolist(), "-"),
            ("📎 정상화 FCF (OCF - D&A)", [_fmt_amt(v) for v in df_multi["norm_fcf"]], _mean_amt(df_multi["norm_fcf"])),
            ("📈 정상화 FCF 성장률 (YoY / CAGR)", [f"{v:+.1f}%" if pd.notna(v) else "-" for v in yoy_col], f"CAGR {fcf_cagr_str}"),
            ("🏛️ 결산일 당시 시가총액", [_fmt_amt(v) for v in hist_mcap_col], _mean_amt(hist_mcap_col)),
            ("📎 당시 시총 대비 FCF 수익률 (%)", [f"{v:.2f}%" if pd.notna(v) else "N/A" for v in hist_yield_col], _mean_str(hist_yield_col, "{:.2f}%")),
            ("📎 회계상 FCF (OCF - CapEx)", [_fmt_amt(v) for v in df_multi["fcf"]], _mean_amt(df_multi["fcf"])),
            ("매출액 (Revenue)", [_fmt_amt(v) for v in df_multi["revenue"]], _mean_amt(df_multi["revenue"])),
            ("영업이익 (EBIT)", [_fmt_amt(v) for v in df_multi["operating_income"]], _mean_amt(df_multi["operating_income"])),
            ("당기순이익 (Net Income)", [_fmt_amt(v) for v in df_multi["net_income"]], _mean_amt(df_multi["net_income"])),
            ("영업현금흐름 (OCF)", [_fmt_amt(v) for v in df_multi["ocf"]], _mean_amt(df_multi["ocf"])),
            ("자본적지출 (CapEx)", [_fmt_amt(v) for v in df_multi["capex"]], _mean_amt(df_multi["capex"])),
            ("감가상각비 (D&A)", [_fmt_amt(v) for v in df_multi["da"]], _mean_amt(df_multi["da"])),
            ("사용자본 (CE)", [_fmt_amt(v) for v in df_multi["ce"]], _mean_amt(df_multi["ce"])),
        ]

        table_data: Dict[str, List[str]] = {"구분 / 핵심 지표": [r[0] for r in metric_rows]}
        for idx, hdr in enumerate(col_headers):
            table_data[hdr] = [r[1][idx] for r in metric_rows]
        table_data[f"📊 {len(df_multi)}개년 평균 / CAGR"] = [r[2] for r in metric_rows]

        multi_display_df = pd.DataFrame(table_data)
        st.dataframe(multi_display_df, use_container_width=True, hide_index=True)

        c_chart1, c_chart2 = st.columns(2)
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
                title=dict(text=f"📈 마진율 & ROCE {len(df_multi)}개년 궤적", font=dict(size=13)),
                xaxis_title="결산연도",
                yaxis_title="비율 (%)",
                height=320,
                margin=dict(l=15, r=15, t=35, b=50),
                legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5, font=dict(size=11)),
            )
            st.plotly_chart(fig_margin, use_container_width=True)

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
                title=dict(text=f"💵 이익 vs 현금흐름 {len(df_multi)}개년 ({u_str}) — FCF CAGR: {fcf_cagr_str}", font=dict(size=13)),
                barmode="group",
                xaxis_title="결산연도",
                yaxis_title=u_str,
                height=320,
                margin=dict(l=15, r=15, t=35, b=50),
                legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5, font=dict(size=11)),
            )
            st.plotly_chart(fig_cf, use_container_width=True)

        st.markdown("---")

    # -----------------------------------------------------------------
    # 섹션 E: 최신 결산 ROCE 듀퐁 항등식 & CCR 현금전환 브릿지
    # -----------------------------------------------------------------
    st.markdown("#### 🔬 4️⃣ 최신 결산기 정밀 분해 (ROCE 듀퐁 항등식 & CCR 현금 브릿지)")
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("##### 📐 ROCE 듀퐁 항등식 세부 분해 (`EBIT Margin × 사용자본회전율`)")
        roce_v = row_data["ROCE (%)"]
        ebit_m_v = row_data["EBIT Margin (%)"]
        turn_v = row_data["사용자본회전율 (배)"]

        st.markdown(
            f"$$\\text{{ROCE ({roce_v:.1f}\\%)}} = \\text{{EBIT Margin ({ebit_m_v:.1f}\\%)}} \\times \\text{{사용자본회전율 ({turn_v:.2f}배)}}$$"
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

        st.markdown(f"**자동 진단 요약**: `{row_data['CCR 상태 진단']}`")

        if pd.notna(ccr_v) and ccr_v < 100.0:
            st.warning("##### 🔍 [CCR 100% 미만 원인 체크리스트]")
            wc_flag = "✅ **[해당]**" if (pd.notna(chg_wc_v) and chg_wc_v < 0) else "⬜ [미해당]"
            capex_flag = "✅ **[해당]**" if (capex_v > da_v) else "⬜ [미해당]"
            st.markdown(
                f"""
                1. {wc_flag} **운전자본 증가 (현금 유출)**: **{format_currency_amount(chg_wc_v, mkt_code)}**
                2. {capex_flag} **감가상각비보다 큰 CapEx**: D&A **{format_currency_amount(da_v, mkt_code)}** vs CapEx **{format_currency_amount(capex_v, mkt_code)}** (`{capex_da_ratio:.0f}%`)
                """
            )
        else:
            st.success("##### 🔍 [CCR 100% 이상 동력 체크리스트]")
            wc_in_flag = "✅ **[해당]**" if (pd.notna(chg_wc_v) and chg_wc_v > 0) else "⬜ [미해당]"
            da_big_flag = "✅ **[해당]**" if (da_v >= capex_v) else "⬜ [미해당]"
            st.markdown(
                f"""
                1. {wc_in_flag} **선수금 및 운전자본 현금 유입**: **{format_currency_amount(chg_wc_v, mkt_code)}**
                2. {da_big_flag} **낮은 설비 재투자 부담**: D&A **{format_currency_amount(da_v, mkt_code)}** vs CapEx **{format_currency_amount(capex_v, mkt_code)}** (`CapEx/D&A = {capex_da_ratio:.0f}%`)
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
            height=320,
            margin=dict(l=20, r=20, t=40, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)


# =====================================================================
# 상세 페이지 활성 시 전체 화면을 상세 페이지로 즉시 라우팅
# =====================================================================
active_detail_sym = st.session_state.get("detail_view_symbol", None)
if active_detail_sym:
    render_company_detail_page(active_detail_sym)
    st.stop()


# =====================================================================
# 메인 대시보드 헤더 & 결산 당시 시가총액 보강 배너
# =====================================================================
hdr_col1, hdr_col2 = st.columns([6.5, 2.5])
with hdr_col1:
    st.title("🎯 한·미 퀄리티 기업 스크리너 & 유니버스")
    mkt_info_str = f"`{market_choice}` ({sub_market_choice})" if sub_market_choice and not sub_market_choice.startswith("전체") else f"`{market_choice}`"
    st.caption(
        f"**분석 시장**: {mkt_info_str} | "
        f"**사용자본(CE)**: `{'현금차감' if deduct_cash_opt else '표준(총자산-유동부채)'}` | "
        f"**CCR 산식**: `{ccr_denom_label}` | "
        f"**요구수익률 ($r={required_return_r:.1f}\\%$)**"
    )
with hdr_col2:
    st.write("")
    if st.button("🔄 현재가·시가총액 실시간 갱신", use_container_width=True):
        with st.spinner("최신 주가 및 시가총액 반영 중..."):
            cnt = de.refresh_prices_and_market_cap(selected_market)
            st.session_state["last_price_refresh"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.toast(f"✅ {cnt}개 기업 주가·시가총액 및 역DCF 기대성장률이 갱신되었습니다!")
        st.rerun()

# 캐시에 5개년 히스토리 또는 결산 당시 시가총액(`hist_market_cap`)이 아직 없는 경우 원클릭 보강 배너 노출
sample_hist_str = ""
if "history_json" in metrics_df.columns and not metrics_df["history_json"].dropna().empty:
    sample_hist_str = str(metrics_df["history_json"].dropna().iloc[0])

needs_hist_mcap_update = ("hist_market_cap" not in sample_hist_str)
if needs_hist_mcap_update:
    with st.container(border=True):
        bc1, bc2 = st.columns([6.5, 2.5])
        with bc1:
            st.markdown(
                "💡 **각 결산연도 당시 시가총액 기준 `4~5년 평균 FCF 수익률` 및 `5년 FCF 성장률(CAGR)` 기능이 추가되었습니다.**\n"
                "우측 버튼을 한 번만 누르면 모든 기업의 **과거 결산일 당시 시가총액과 5개년 히스토리**가 일괄 업데이트됩니다. *(기업 상세 페이지에서는 클릭 시 즉시 자동 계산됩니다)*"
            )
        with bc2:
            if st.button("⚡ 결산 당시 시총 & 5개년 데이터 일괄 업데이트", type="primary", use_container_width=True):
                prog = st.progress(0, text="결산 당시 시가총액 및 5개년 재무 데이터 업데이트 중...")

                def _bf_prog(d: int, t: int) -> None:
                    prog.progress(d / t, text=f"{d} / {t} 기업 과거 결산 당시 시총 및 5개년 FCF 수집 중...")

                cnt_bf = de.backfill_multiyear_history_for_cache(selected_market, max_workers=12, progress_callback=_bf_prog, force_all=True)
                prog.empty()
                st.toast(f"✅ {cnt_bf}개 기업의 과거 결산 당시 시총 및 5개년 FCF 데이터 업데이트 완료!")
                st.rerun()

# 카드/테이블을 볼 때 필터 기준(최근 결산 vs 다개년 평균 vs 동시 충족) 선택 바
filter_basis_mode = st.radio(
    "🎛️ 필터링 평가 기준 선택 (카드와 테이블에는 항상 최근 결산 수치와 4~5개년 평균 수치가 나란히 함께 표시됩니다)",
    options=[
        "최근 결산 기준",
        "5개년 평균 기준",
        "최근 + 5개년 평균 동시 충족",
    ],
    index=0,
    horizontal=True,
    key="filter_basis_mode",
)

gpm_col_target = "GPM_5Y (%)" if filter_basis_mode == "5개년 평균 기준" else "GPM (%)"
roce_col_target = "ROCE_5Y (%)" if filter_basis_mode == "5개년 평균 기준" else "ROCE (%)"
ccr_col_target = "CCR_5Y (%)" if filter_basis_mode == "5개년 평균 기준" else "CCR (%)"

active_rules: List[Dict[str, Any]] = [
    {
        "metric": gpm_col_target,
        "operator": op_gpm,
        "value": float(val_gpm),
        "enabled": use_gpm,
        "label": f"{'평균 ' if '5Y' in gpm_col_target else ''}GPM {op_gpm} {val_gpm:.0f}%",
        "short_name": "GPM(평균)" if "5Y" in gpm_col_target else "GPM",
    },
    {
        "metric": roce_col_target,
        "operator": op_roce,
        "value": float(val_roce),
        "enabled": use_roce,
        "label": f"{'평균 ' if '5Y' in roce_col_target else ''}ROCE {op_roce} {val_roce:.0f}%",
        "short_name": "ROCE(평균)" if "5Y" in roce_col_target else "ROCE",
    },
    {
        "metric": ccr_col_target,
        "operator": op_ccr,
        "value": float(val_ccr),
        "enabled": use_ccr,
        "label": f"{'평균 ' if '5Y' in ccr_col_target else ''}CCR {op_ccr} {val_ccr:.0f}%",
        "short_name": "CCR(평균)" if "5Y" in ccr_col_target else "CCR",
    },
]

if filter_basis_mode == "최근 + 5개년 평균 동시 충족":
    active_rules.extend([
        {
            "metric": "GPM_5Y (%)",
            "operator": op_gpm,
            "value": float(val_gpm),
            "enabled": use_gpm,
            "label": f"평균 GPM {op_gpm} {val_gpm:.0f}%",
            "short_name": "GPM(평균)",
        },
        {
            "metric": "ROCE_5Y (%)",
            "operator": op_roce,
            "value": float(val_roce),
            "enabled": use_roce,
            "label": f"평균 ROCE {op_roce} {val_roce:.0f}%",
            "short_name": "ROCE(평균)",
        },
        {
            "metric": "CCR_5Y (%)",
            "operator": op_ccr,
            "value": float(val_ccr),
            "enabled": use_ccr,
            "label": f"평균 CCR {op_ccr} {val_ccr:.0f}%",
            "short_name": "CCR(평균)",
        },
    ])

active_rules.append(
    {
        "metric": "이자보상배율 (배)",
        "operator": op_icr,
        "value": float(val_icr),
        "enabled": use_icr,
        "label": f"이자보상 {op_icr} {val_icr:.0f}배",
        "short_name": "이자보상",
    }
)
active_rules.extend(extra_rules)

passed_df, annotated_df, funnel_stats = de.apply_filter_rules(metrics_df, active_rules)

enabled_rules = [r for r in active_rules if r.get("enabled", True) and r["metric"] in annotated_df.columns]

if not annotated_df.empty:
    failed_labels_per_row: List[str] = []
    failed_count_per_row: List[int] = []
    for _, r in annotated_df.iterrows():
        f_list = []
        for rule in enabled_rules:
            m_col = rule["metric"]
            pass_col = f"통과_{m_col}"
            if pass_col in r and not bool(r[pass_col]):
                s_name = rule.get("short_name") or rule.get("label") or m_col
                actual_val = r.get(m_col, np.nan)
                if pd.notna(actual_val) and actual_val > -900:
                    val_s = f"{actual_val:.1f}"
                else:
                    val_s = "N/A"
                f_list.append(f"❌ {s_name}({val_s})")
        failed_count_per_row.append(len(f_list))
        if len(f_list) == 0:
            failed_labels_per_row.append("✅ 모든 조건 통과")
        else:
            failed_labels_per_row.append(f"⚠️ {len(f_list)}개 미달: " + ", ".join(f_list))

    annotated_df["미달_조건수"] = failed_count_per_row
    annotated_df["통과_상태_요약"] = failed_labels_per_row

if funnel_stats:
    chips_html = []
    for idx, stat in enumerate(funnel_stats):
        st_name = "전체 유니버스" if idx == 0 else (stat.get("label") or stat.get("stage", ""))
        cnt = stat["remaining"]
        is_last = idx == len(funnel_stats) - 1
        active_cls = "active" if is_last else ""
        chips_html.append(
            f"<div class='funnel-step-chip {active_cls}'>"
            f"<span>{html.escape(st_name)}</span>"
            f"<span style='color:{'#1d4ed8' if is_last else '#0f172a'}; font-weight:700;'>{cnt}개</span>"
            f"</div>"
        )
    funnel_bar_html = "<div class='funnel-scroll-bar'>" + "<div class='funnel-arrow-sep'>➔</div>".join(chips_html) + "</div>"
    st.markdown(funnel_bar_html, unsafe_allow_html=True)

st.markdown("---")

# =====================================================================
# 2개 통합 메인 탭 구성:
# - TAB 1: 🔍 퀄리티 스크리너 (모든 조건 / 아깝게 1개 조건 미달 / 전체 종목)
# - TAB 2: ⭐ 나의 유니버스 보관함 (기업별 성장기간 N년 정밀 역DCF & 메모/링크)
# =====================================================================
universe_store = de.load_universe_store()
tab1_label = f"🔍 퀄리티 스크리너 (통과 {len(passed_df)} / 전체 {len(annotated_df)})"
tab2_label = f"⭐ 나의 유니버스 보관함 ({len(universe_store)}개)"

if st.session_state.pop("clear_screener_selection", False):
    st.session_state["df_screener_table"] = {"selection": {"rows": [], "columns": []}}
if st.session_state.pop("clear_universe_selection", False):
    st.session_state["df_universe_table"] = {"selection": {"rows": [], "columns": []}}

tab_screener, tab_universe = st.tabs([tab1_label, tab2_label])


# ---------------------------------------------------------------------
# TAB 1: 통합 퀄리티 스크리너 (모든 조건 / 아깝게 1개 조건 / 전체 종목)
# ---------------------------------------------------------------------
with tab_screener:
    render_hover_chips_guide()

    df_all_pass = annotated_df[annotated_df["미달_조건수"] == 0].copy() if not annotated_df.empty else pd.DataFrame()
    df_near_miss = annotated_df[annotated_df["미달_조건수"] == 1].copy() if not annotated_df.empty else pd.DataFrame()
    df_full = annotated_df.copy()

    opt_all_pass = f"✅ 모든 조건 통과 ({len(df_all_pass)}개)"
    opt_near_miss = f"🤏 아깝게 1개 조건 미달 ({len(df_near_miss)}개)"
    opt_full = f"📊 전체 종목 ({len(df_full)}개)"

    group_options = [opt_all_pass, opt_near_miss, opt_full]
    group_df_map = {
        opt_all_pass: df_all_pass,
        opt_near_miss: df_near_miss,
        opt_full: df_full,
    }

    with st.container(border=True):
        selected_group_opt = st.radio(
            "조회할 기업 그룹 선택",
            options=group_options,
            index=0,
            horizontal=True,
            key="screener_group_opt",
        )

        ctrl_c1, ctrl_c2, ctrl_c3 = st.columns([2.8, 2.0, 3.2])
        with ctrl_c1:
            sort_by_metric = st.selectbox(
                "정렬 기준",
                options=[
                    "역DCF 기대성장률 (%)",
                    "정상화 FCF 수익률 (%)",
                    "ROCE (%)",
                    "ROCE_5Y (%)",
                    "GPM (%)",
                    "GPM_5Y (%)",
                    "CCR (%)",
                    "CCR_5Y (%)",
                    "OPM (%)",
                    "market_cap",
                ],
                index=2 if filter_basis_mode == "최근 결산 기준" else 3,
            )
        with ctrl_c2:
            default_asc = True if "역DCF" in sort_by_metric else False
            sort_asc = st.checkbox("오름차순 정렬 (낮은 순)", value=default_asc)
        with ctrl_c3:
            view_mode = st.radio(
                "화면 표시 모드",
                options=["📱 모바일 카드 뷰", "📊 PC 와이드 테이블"],
                index=0,
                horizontal=True,
                key="screener_view_mode",
            )

    target_df = group_df_map.get(selected_group_opt, pd.DataFrame())

    if target_df.empty:
        st.warning("선택한 조건 그룹에 해당하는 기업이 없습니다. 다른 그룹을 클릭하거나 좌측 필터 기준을 조절해 보세요.")
    else:
        disp_df = target_df.sort_values(
            by=["미달_조건수", sort_by_metric],
            ascending=[True, sort_asc],
        ).reset_index(drop=True)

        if view_mode.startswith("📱"):
            st.caption(
                "💡 **FCF 수익률 및 역DCF 안내**: `최근 수치`는 **현재 시가총액 대비 최근 FCF**, `4~5년 평균 수치`는 **각 결산연도 당시 시가총액 대비 당시 FCF 수익률의 평균**입니다."
            )
            for c_idx, row in disp_df.iterrows():
                sym = row["symbol"]
                name = row["name"]
                mkt_code = str(row["market"]).upper()
                mkt_d = row.get("market_display", row["market"])
                mcap = row.get("시가총액_표시", "N/A")
                fdate = row.get("fiscal_date", "N/A")
                yr_cnt = int(row.get("평균_연도수", 1))

                g_val = row.get("역DCF 기대성장률 (%)", np.nan)
                g_5y = row.get("역DCF 기대성장률_5Y (%)", np.nan)
                fcf_y = row.get("정상화 FCF 수익률 (%)", np.nan)
                fcf_y_5y = row.get("정상화 FCF 수익률_5Y (%)", np.nan)

                gpm, gpm_5y = row.get("GPM (%)", np.nan), row.get("GPM_5Y (%)", np.nan)
                roce, roce_5y = row.get("ROCE (%)", np.nan), row.get("ROCE_5Y (%)", np.nan)
                ccr, ccr_5y = row.get("CCR (%)", np.nan), row.get("CCR_5Y (%)", np.nan)
                opm, opm_5y = row.get("OPM (%)", np.nan), row.get("OPM_5Y (%)", np.nan)
                ccr_diag = row.get("CCR 상태 진단", "")
                int_cov = row.get("이자보상배율_표시", "N/A")

                fail_cnt = int(row.get("미달_조건수", 0))
                status_summary = str(row.get("통과_상태_요약", ""))
                if fail_cnt == 0:
                    badge_html = f"<span class='pass-badge-ok'>{html.escape(status_summary)}</span>"
                elif fail_cnt == 1:
                    badge_html = f"<span class='pass-badge-warn'>{html.escape(status_summary)}</span>"
                else:
                    badge_html = f"<span class='pass-badge-fail'>{html.escape(status_summary)}</span>"

                in_uni = sym in universe_store
                uni_badge = "⭐ [유니버스 보관중]" if in_uni else ""
                box_cls = "m-card-box in-universe" if in_uni else "m-card-box"

                g_text = f"{g_val:+.1f}%" if pd.notna(g_val) else "N/A"
                g_5y_text = f"(당시시총 기준 {yr_cnt}년평균: {g_5y:+.1f}%)" if pd.notna(g_5y) else ""
                fcf_text = f"FCF수익률: 최근 {fcf_y:.1f}%" if pd.notna(fcf_y) else ""
                if pd.notna(fcf_y_5y):
                    fcf_text += f" ({yr_cnt}년평균 {fcf_y_5y:.1f}%)"

                gpm_str = f"{gpm:.1f}%" if pd.notna(gpm) else "N/A"
                gpm_5y_str = f"{yr_cnt}년 평균 {gpm_5y:.1f}%" if pd.notna(gpm_5y) else "N/A"
                roce_str = f"{roce:.1f}%" if pd.notna(roce) else "N/A"
                roce_5y_str = f"{yr_cnt}년 평균 {roce_5y:.1f}%" if pd.notna(roce_5y) else "N/A"
                ccr_str = f"{ccr:.1f}%" if pd.notna(ccr) else "N/A"
                ccr_5y_str = f"{yr_cnt}년 평균 {ccr_5y:.1f}%" if pd.notna(ccr_5y) else "N/A"
                opm_5y_str = f"OPM 최근 {opm:.1f}% ({yr_cnt}년 {opm_5y:.1f}%)" if (pd.notna(opm) and pd.notna(opm_5y)) else ""

                diag_html = (
                    f"<div style='font-size:0.75rem; color:#475569; margin:4px 0 6px 0; background:#f8fafc; padding:4px 8px; border-radius:4px;'>"
                    f"🩺 <b>CCR 진단</b>: {html.escape(str(ccr_diag))}</div>"
                    if (ccr_diag and ccr_diag != "-")
                    else ""
                )

                memo_preview_html = ""
                if in_uni and universe_store[sym].get("memo"):
                    memo_preview_html = render_memo_with_links_html(universe_store[sym]["memo"])

                card_html = f"""
                <div class="{box_cls}">
                    <div class="m-card-header-row">
                        <div>
                            <span class="m-company-title">{html.escape(name)}</span>
                            <span style="font-size:0.78rem; color:#64748b; margin-left:4px;">({html.escape(sym)})</span>
                            <span style="margin-left:6px;">{badge_html}</span>
                            <span style="font-size:0.76rem; color:#d97706; font-weight:700; margin-left:6px;">{uni_badge}</span>
                        </div>
                        <div class="m-company-meta">{html.escape(str(mkt_d))} · {html.escape(str(mcap))}</div>
                    </div>
                    <div class="m-dcf-strip">
                        <div>
                            <div style="font-size:0.72rem; color:#c2410c; font-weight:600;">🔥 영구 역DCF 기대성장률 (r={required_return_r:.0f}%)</div>
                            <div style="font-size:1.12rem; font-weight:800; color:#9a3412; line-height:1.2;">{g_text} <span style="font-size:0.75rem; font-weight:600; color:#c2410c;">{g_5y_text}</span></div>
                        </div>
                        <div style="text-align:right;">
                            <div style="font-size:0.74rem; color:#ea580c; font-weight:600;">{fcf_text}</div>
                            <div style="font-size:0.7rem; color:#78716c;">결산 {html.escape(str(fdate))}</div>
                        </div>
                    </div>
                    <div class="m-grid-2x2-tiles">
                        <div class="m-tile-item">
                            <div class="m-tile-item-lbl">🎯 GPM (매출총이익률)</div>
                            <div class="m-tile-item-val">최근 {gpm_str}</div>
                            <div class="m-tile-item-sub">📊 {gpm_5y_str}</div>
                        </div>
                        <div class="m-tile-item">
                            <div class="m-tile-item-lbl">🎯 ROCE (사용자본이익률)</div>
                            <div class="m-tile-item-val">최근 {roce_str}</div>
                            <div class="m-tile-item-sub">📊 {roce_5y_str}</div>
                        </div>
                        <div class="m-tile-item">
                            <div class="m-tile-item-lbl">🎯 CCR (현금전환율)</div>
                            <div class="m-tile-item-val">최근 {ccr_str}</div>
                            <div class="m-tile-item-sub">📊 {ccr_5y_str}</div>
                        </div>
                        <div class="m-tile-item">
                            <div class="m-tile-item-lbl">🎯 이자보상 / 영업이익률</div>
                            <div class="m-tile-item-val" style="font-size:0.86rem;">{html.escape(str(int_cov))}</div>
                            <div class="m-tile-item-sub" style="color:#475569;">{html.escape(opm_5y_str)}</div>
                        </div>
                    </div>
                    {diag_html}
                    {memo_preview_html}
                </div>
                """
                st.markdown(card_html, unsafe_allow_html=True)

                btn_c1, btn_c2 = st.columns([3.2, 1.5])
                with btn_c1:
                    if st.button(f"🏢 {name} 상세 페이지 열기 (5개년 추이 · FCF 성장률 · N년 역DCF)", key=f"btn_detail_{sym}_{c_idx}", use_container_width=True):
                        open_company_detail(sym, return_tab="screener")
                        st.rerun()
                with btn_c2:
                    if in_uni:
                        if st.button("✅ 유니버스 보관중 (해제)", key=f"btn_uni_{sym}_{c_idx}", use_container_width=True):
                            de.remove_universe_item(sym)
                            st.toast(f"🗑️ {name} 종목을 유니버스에서 제거했습니다.")
                            st.rerun()
                    else:
                        if st.button("⭐ 유니버스 보관", key=f"btn_uni_{sym}_{c_idx}", use_container_width=True):
                            de.upsert_universe_item(symbol=sym, name=name, market=mkt_code)
                            st.toast(f"⭐ {name} 종목을 유니버스 보관함에 추가했습니다!")
                            st.rerun()
        else:
            st.caption("👉 **테이블의 기업 행을 클릭**하면 즉시 해당 기업의 **[🏢 기업 심층 상세 페이지]**로 화면이 전환됩니다.")
            disp_df["⭐ 유니버스"] = disp_df["symbol"].apply(lambda s: "⭐ 보관중" if s in universe_store else "")

            view_cols = [
                "⭐ 유니버스",
                "symbol",
                "name",
                "market_display",
                "시가총액_표시",
                "통과_조건수",
                "통과_상태_요약",
                "정상화 FCF 수익률 (%)",
                "정상화 FCF 수익률_5Y (%)",
                "역DCF 기대성장률 (%)",
                "GPM (%)",
                "GPM_5Y (%)",
                "ROCE (%)",
                "ROCE_5Y (%)",
                "CCR (%)",
                "CCR_5Y (%)",
                "OPM (%)",
                "OPM_5Y (%)",
                "이자보상배율_표시",
                "CCR 상태 진단",
                "fiscal_date",
            ]
            view_df = disp_df[view_cols].rename(
                columns={
                    "symbol": "티커",
                    "name": "기업명",
                    "market_display": "시장",
                    "시가총액_표시": "현재 시가총액",
                    "통과_조건수": "통과수",
                    "통과_상태_요약": "조건별 통과/미달 진단",
                    "정상화 FCF 수익률 (%)": "FCF수익률(최근)",
                    "정상화 FCF 수익률_5Y (%)": "FCF수익률(당시시총 평균)",
                    "역DCF 기대성장률 (%)": f"🔥 역DCF g (r={required_return_r:.0f}%)",
                    "GPM (%)": "🎯 GPM(최근)",
                    "GPM_5Y (%)": "📊 GPM(평균)",
                    "ROCE (%)": "🎯 ROCE(최근)",
                    "ROCE_5Y (%)": "📊 ROCE(평균)",
                    "CCR (%)": "🎯 CCR(최근)",
                    "CCR_5Y (%)": "📊 CCR(평균)",
                    "OPM (%)": "📎 OPM(최근)",
                    "OPM_5Y (%)": "📊 OPM(평균)",
                    "이자보상배율_표시": "🎯 이자보상배율",
                    "CCR 상태 진단": "🩺 CCR 원인 진단",
                    "fiscal_date": "결산기준일",
                }
            )
            g_col_name = f"🔥 역DCF g (r={required_return_r:.0f}%)"

            event_screener = st.dataframe(
                view_df.style.format(
                    {
                        "FCF수익률(최근)": "{:.2f}%",
                        "FCF수익률(당시시총 평균)": "{:.2f}%",
                        g_col_name: "{:+.2f}%",
                        "🎯 GPM(최근)": "{:.1f}%",
                        "📊 GPM(평균)": "{:.1f}%",
                        "🎯 ROCE(최근)": "{:.1f}%",
                        "📊 ROCE(평균)": "{:.1f}%",
                        "🎯 CCR(최근)": "{:.1f}%",
                        "📊 CCR(평균)": "{:.1f}%",
                        "📎 OPM(최근)": "{:.1f}%",
                        "📊 OPM(평균)": "{:.1f}%",
                    },
                    na_rep="N/A",
                ),
                use_container_width=True,
                height=min(650, 120 + len(view_df) * 38),
                on_select="rerun",
                selection_mode="single-row",
                key="df_screener_table",
            )

            if event_screener and hasattr(event_screener, "selection"):
                s_rows = event_screener.selection.get("rows", [])
                if s_rows:
                    sel_idx = s_rows[0]
                    if sel_idx < len(disp_df):
                        clicked_sym = disp_df.iloc[sel_idx]["symbol"]
                        open_company_detail(clicked_sym, return_tab="screener")
                        st.rerun()

        export_cols = [
            "symbol", "name", "market_display", "시가총액_표시",
            "통과_조건수", "통과_상태_요약",
            "정상화 FCF 수익률 (%)", "정상화 FCF 수익률_5Y (%)", "역DCF 기대성장률 (%)",
            "GPM (%)", "GPM_5Y (%)", "ROCE (%)", "ROCE_5Y (%)",
            "CCR (%)", "CCR_5Y (%)", "OPM (%)", "OPM_5Y (%)",
            "이자보상배율_표시", "CCR 상태 진단", "fiscal_date",
        ]
        export_df = disp_df[export_cols]
        dl_col1, dl_col2, _ = st.columns([2, 2, 6])
        csv_bytes = export_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        dl_col1.download_button(
            label="📥 현재 목록 CSV 다운로드 (utf-8-sig)",
            data=csv_bytes,
            file_name=f"quality_screener_{selected_market}.csv",
            mime="text/csv",
            use_container_width=True,
        )
        excel_bytes = to_excel_bytes(export_df)
        dl_col2.download_button(
            label="📥 현재 목록 Excel (.xlsx) 다운로드",
            data=excel_bytes,
            file_name=f"quality_screener_{selected_market}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )


# ---------------------------------------------------------------------
# TAB 2: ⭐ 나의 유니버스 보관함 (기업별 성장기간 N년 정밀 역DCF & 메모/링크)
# ---------------------------------------------------------------------
with tab_universe:
    st.subheader(f"⭐ 나의 유니버스 보관함 ({len(universe_store)}개 기업)")
    st.caption(
        "유니버스에 보관된 기업들만 따로 모아 **기업별 맞춤 성장기간($N$년)·성장기간 성장률($g_1$)·이후 성장률($g_2$) 기반 정밀 역DCF**를 계산하고, **구글 독스 등 웹 링크가 포함된 메모**를 영구 관리합니다."
    )

    with st.expander("➕ 스크리너 캐시 종목 중 유니버스에 바로 추가하기", expanded=len(universe_store) == 0):
        avail_to_add = [
            f"{r['name']} ({r['symbol']}) - {r.get('market_display', '')} | {r.get('시가총액_표시', '')}"
            for _, r in all_metrics_df.iterrows()
            if r["symbol"] not in universe_store
        ]
        sym_add_map = {
            f"{r['name']} ({r['symbol']}) - {r.get('market_display', '')} | {r.get('시가총액_표시', '')}": (r["symbol"], r["name"], r["market"])
            for _, r in all_metrics_df.iterrows()
            if r["symbol"] not in universe_store
        }
        ac1, ac2 = st.columns([4, 1.5])
        with ac1:
            sel_to_add = st.multiselect("유니버스에 담을 기업을 선택하세요", options=avail_to_add, placeholder="기업명 또는 티커 검색...")
        with ac2:
            st.write("")
            if st.button("⭐ 선택 기업 유니버스 추가", type="primary", use_container_width=True) and sel_to_add:
                for item_lbl in sel_to_add:
                    s_code, s_name, s_mkt = sym_add_map[item_lbl]
                    de.upsert_universe_item(symbol=s_code, name=s_name, market=s_mkt)
                st.toast(f"⭐ {len(sel_to_add)}개 기업을 유니버스 보관함에 추가했습니다!")
                st.rerun()

    if not universe_store:
        st.info("아직 유니버스 보관함에 담긴 기업이 없습니다. [🔍 퀄리티 스크리너] 카드에서 `⭐ 유니버스 보관` 버튼을 누르거나 위 검색창에서 기업을 추가해 보세요.")
    else:
        uni_symbols = list(universe_store.keys())
        uni_df = all_metrics_df[all_metrics_df["symbol"].isin(uni_symbols)].copy().reset_index(drop=True)

        missing_in_cache = [s for s in uni_symbols if s not in set(uni_df["symbol"].tolist())]
        if missing_in_cache:
            st.warning(f"캐시에 재무제표가 아직 없는 유니버스 종목({', '.join(missing_in_cache)})이 있습니다. 좌측 사이드바 [개별 종목 직접 추가]에서 추가해 주세요.")

        if not uni_df.empty:
            uni_view_mode = st.radio(
                "유니버스 표시 모드",
                options=["📱 기업별 성장기간(N년) 시뮬레이션 & 메모 카드 뷰", "📊 유니버스 한눈에 비교 테이블 (행 클릭 시 상세 페이지)"],
                index=0,
                horizontal=True,
                key="uni_view_mode",
            )

            n_list, g1_est_list, g2_list, g_imp_n_list, fair_mcap_list, upside_list, memo_list = [], [], [], [], [], [], []
            for _, r in uni_df.iterrows():
                sym = r["symbol"]
                u_item = universe_store.get(sym, {})
                n_yr = int(u_item.get("growth_years", 10))
                g1_est = float(u_item.get("growth_rate_est", 10.0))
                g2_term = float(u_item.get("terminal_growth_rate", 0.0))
                memo_txt = str(u_item.get("memo", ""))

                fcf0 = r.get("norm_fcf", np.nan)
                mcap0 = r.get("market_cap", np.nan)
                mkt_c = str(r.get("market", "KR")).upper()

                g_imp_n = de.solve_two_stage_implied_growth(fcf0, mcap0, required_return_r, n_yr, g2_term)
                dcf_out = de.calc_two_stage_dcf_value(fcf0, required_return_r, n_yr, g1_est, g2_term)
                f_mcap = dcf_out["intrinsic_value"]
                up_pct = ((f_mcap / mcap0 - 1.0) * 100.0) if (pd.notna(f_mcap) and pd.notna(mcap0) and mcap0 > 0) else np.nan

                n_list.append(n_yr)
                g1_est_list.append(g1_est)
                g2_list.append(g2_term)
                g_imp_n_list.append(g_imp_n)
                fair_mcap_list.append(format_currency_amount(f_mcap, mkt_c) if pd.notna(f_mcap) else "N/A")
                upside_list.append(up_pct)
                memo_list.append(memo_txt)

            uni_df["성장기간(N년)"] = n_list
            uni_df["예상성장률_g1(%)"] = g1_est_list
            uni_df["이후성장률_g2(%)"] = g2_list
            uni_df["N년_정밀역DCF_요구성장률(%)"] = g_imp_n_list
            uni_df["적정시가총액"] = fair_mcap_list
            uni_df["상승여력(%)"] = upside_list
            uni_df["메모"] = memo_list

            if uni_view_mode.startswith("📱"):
                for u_idx, row in uni_df.iterrows():
                    sym = row["symbol"]
                    name = row["name"]
                    mkt_code = str(row["market"]).upper()
                    mkt_d = row.get("market_display", row["market"])
                    mcap_str = row.get("시가총액_표시", "N/A")
                    yr_cnt = int(row.get("평균_연도수", 1))
                    u_item = universe_store.get(sym, {})

                    with st.container(border=True):
                        hc1, hc2, hc3 = st.columns([5.0, 2.5, 1.5])
                        with hc1:
                            st.markdown(
                                f"### ⭐ {name} (`{sym}`) — `{mkt_d}` · 시총 `{mcap_str}`"
                            )
                        with hc2:
                            if st.button(f"🏢 {name} 상세 페이지 열기", key=f"uni_open_detail_{sym}", type="primary", use_container_width=True):
                                open_company_detail(sym, return_tab="universe")
                                st.rerun()
                        with hc3:
                            if st.button("🗑️ 보관함에서 제거", key=f"uni_del_{sym}", use_container_width=True):
                                de.remove_universe_item(sym)
                                st.toast(f"🗑️ {name} 종목을 유니버스에서 제거했습니다.")
                                st.rerun()

                        gpm_now, gpm_5y = row.get("GPM (%)", np.nan), row.get("GPM_5Y (%)", np.nan)
                        roce_now, roce_5y = row.get("ROCE (%)", np.nan), row.get("ROCE_5Y (%)", np.nan)
                        ccr_now, ccr_5y = row.get("CCR (%)", np.nan), row.get("CCR_5Y (%)", np.nan)
                        fcf_y_now = row.get("정상화 FCF 수익률 (%)", np.nan)
                        fcf_y_5y = row.get("정상화 FCF 수익률_5Y (%)", np.nan)
                        g_inf = row.get("역DCF 기대성장률 (%)", np.nan)
                        g_imp_n = row.get("N년_정밀역DCF_요구성장률(%)", np.nan)
                        n_yr_cur = int(row["성장기간(N년)"])
                        g1_cur = float(row["예상성장률_g1(%)"])
                        g2_cur = float(row["이후성장률_g2(%)"])
                        fair_mcap_s = row["적정시가총액"]
                        upside_v = row.get("상승여력(%)", np.nan)

                        def _fp(v: float) -> str:
                            return f"{v:.1f}%" if pd.notna(v) else "N/A"

                        g_inf_s = f"{g_inf:+.1f}%" if pd.notna(g_inf) else "N/A"
                        g_imp_n_s = f"{g_imp_n:+.1f}%" if pd.notna(g_imp_n) else "산출불가(FCF≤0)"
                        upside_s = f"{upside_v:+.1f}%" if pd.notna(upside_v) else "N/A"
                        term_yield_s = f"{(required_return_r - g2_cur):.1f}%"

                        uni_metrics_html = f"""
                        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(185px, 1fr)); gap:8px; margin:6px 0 10px 0;">
                            <div class="m-tile-item" style="background:#fff7ed; border:1px solid #fed7aa; text-align:left; padding:8px 10px;">
                                <div class="m-tile-item-lbl" style="color:#c2410c; font-weight:700;">🔥 {n_yr_cur}년 한정 정밀 역DCF 요구성장률</div>
                                <div class="m-tile-item-val" style="font-size:1.15rem; color:#9a3412;">연 {g_imp_n_s} <span style="font-size:0.75rem; font-weight:600;">({n_yr_cur}년간)</span></div>
                                <div style="font-size:0.71rem; color:#9a3412;">영구성장 역DCF: {g_inf_s} | {n_yr_cur}년뒤 FCF수익률 {term_yield_s}</div>
                            </div>
                            <div class="m-tile-item" style="background:#f0fdf4; border:1px solid #bbf7d0; text-align:left; padding:8px 10px;">
                                <div class="m-tile-item-lbl" style="color:#047857; font-weight:700;">💎 예상 성장률(연 {g1_cur:.1f}%) 적정 시총</div>
                                <div class="m-tile-item-val" style="font-size:1.08rem; color:#065f46;">{fair_mcap_s} ({upside_s})</div>
                                <div style="font-size:0.71rem; color:#047857;">FCF수익률: 최근 {_fp(fcf_y_now)} (당시시총 평균 {_fp(fcf_y_5y)})</div>
                            </div>
                            <div class="m-tile-item" style="padding:8px 10px;">
                                <div class="m-tile-item-lbl">🎯 GPM (원가경쟁력)</div>
                                <div class="m-tile-item-val">최근 {_fp(gpm_now)}</div>
                                <div class="m-tile-item-sub">📊 {yr_cnt}년 평균 {_fp(gpm_5y)}</div>
                            </div>
                            <div class="m-tile-item" style="padding:8px 10px;">
                                <div class="m-tile-item-lbl">🎯 ROCE (자본배치)</div>
                                <div class="m-tile-item-val">최근 {_fp(roce_now)}</div>
                                <div class="m-tile-item-sub">📊 {yr_cnt}년 평균 {_fp(roce_5y)}</div>
                            </div>
                            <div class="m-tile-item" style="padding:8px 10px;">
                                <div class="m-tile-item-lbl">🎯 CCR (현금전환율)</div>
                                <div class="m-tile-item-val">최근 {_fp(ccr_now)}</div>
                                <div class="m-tile-item-sub">📊 {yr_cnt}년 평균 {_fp(ccr_5y)}</div>
                            </div>
                        </div>
                        """
                        st.markdown(uni_metrics_html, unsafe_allow_html=True)

                        cur_memo_str = u_item.get("memo", "")
                        st.markdown(render_memo_with_links_html(cur_memo_str), unsafe_allow_html=True)

                        with st.expander(f"⚙️ {name} 맞춤 성장기간(N년)·성장률 및 메모/링크 수정", expanded=False):
                            ec1, ec2, ec3 = st.columns(3)
                            with ec1:
                                edit_n = st.number_input("성장 지속기간 N (년)", min_value=1, max_value=40, value=n_yr_cur, step=1, key=f"u_n_{sym}")
                            with ec2:
                                edit_g1 = st.number_input("성장기간 예상 성장률 g1 (%)", min_value=-30.0, max_value=100.0, value=g1_cur, step=1.0, key=f"u_g1_{sym}")
                            with ec3:
                                edit_g2 = st.number_input("N년 이후 영구성장률 g2 (%)", min_value=-10.0, max_value=float(required_return_r - 0.5), value=g2_cur, step=0.5, key=f"u_g2_{sym}")

                            edit_memo = st.text_area(
                                "기업 메모 & 웹 URL (구글 독스 주소 등)",
                                value=cur_memo_str,
                                height=75,
                                key=f"u_memo_{sym}",
                            )
                            if st.button("💾 변경사항 저장", key=f"u_save_{sym}", type="primary"):
                                de.upsert_universe_item(
                                    symbol=sym,
                                    name=name,
                                    market=mkt_code,
                                    memo=edit_memo,
                                    growth_years=int(edit_n),
                                    growth_rate_est=float(edit_g1),
                                    terminal_growth_rate=float(edit_g2),
                                )
                                st.toast(f"✅ {name}의 유니버스 설정이 업데이트되었습니다!")
                                st.rerun()
            else:
                st.caption("👉 **기업 행을 클릭**하면 해당 기업의 **[🏢 기업 심층 상세 페이지]**로 즉시 이동합니다.")
                uni_table_cols = [
                    "symbol",
                    "name",
                    "market_display",
                    "시가총액_표시",
                    "정상화 FCF 수익률 (%)",
                    "정상화 FCF 수익률_5Y (%)",
                    "역DCF 기대성장률 (%)",
                    "성장기간(N년)",
                    "이후성장률_g2(%)",
                    "N년_정밀역DCF_요구성장률(%)",
                    "예상성장률_g1(%)",
                    "적정시가총액",
                    "상승여력(%)",
                    "GPM (%)",
                    "GPM_5Y (%)",
                    "ROCE (%)",
                    "ROCE_5Y (%)",
                    "CCR (%)",
                    "CCR_5Y (%)",
                    "메모",
                ]
                uni_t_df = uni_df[uni_table_cols].rename(
                    columns={
                        "symbol": "티커",
                        "name": "기업명",
                        "market_display": "시장",
                        "시가총액_표시": "현재 시가총액",
                        "정상화 FCF 수익률 (%)": "FCF수익률(최근)",
                        "정상화 FCF 수익률_5Y (%)": "FCF수익률(당시시총 평균)",
                        "역DCF 기대성장률 (%)": "영구 역DCF g(∞)",
                        "성장기간(N년)": "성장기간(N년)",
                        "이후성장률_g2(%)": "이후성장률(g2)",
                        "N년_정밀역DCF_요구성장률(%)": "🔥 N년 정밀 역DCF 요구성장률",
                        "예상성장률_g1(%)": "내 예상성장률(g1)",
                        "적정시가총액": "💎 적정 시가총액",
                        "상승여력(%)": "상승여력(%)",
                        "GPM (%)": "GPM(최근)",
                        "GPM_5Y (%)": "GPM(평균)",
                        "ROCE (%)": "ROCE(최근)",
                        "ROCE_5Y (%)": "ROCE(평균)",
                        "CCR (%)": "CCR(최근)",
                        "CCR_5Y (%)": "CCR(평균)",
                        "메모": "📝 메모 & 링크",
                    }
                )
                ev_uni = st.dataframe(
                    uni_t_df.style.format(
                        {
                            "FCF수익률(최근)": "{:.2f}%",
                            "FCF수익률(당시시총 평균)": "{:.2f}%",
                            "영구 역DCF g(∞)": "{:+.2f}%",
                            "성장기간(N년)": "{:.0f}년",
                            "이후성장률(g2)": "{:+.1f}%",
                            "🔥 N년 정밀 역DCF 요구성장률": "{:+.2f}%",
                            "내 예상성장률(g1)": "{:+.1f}%",
                            "상승여력(%)": "{:+.1f}%",
                            "GPM(최근)": "{:.1f}%",
                            "GPM(평균)": "{:.1f}%",
                            "ROCE(최근)": "{:.1f}%",
                            "ROCE(평균)": "{:.1f}%",
                            "CCR(최근)": "{:.1f}%",
                            "CCR(평균)": "{:.1f}%",
                        },
                        na_rep="N/A",
                    ),
                    use_container_width=True,
                    height=min(600, 140 + len(uni_t_df) * 38),
                    on_select="rerun",
                    selection_mode="single-row",
                    key="df_universe_table",
                )
                if ev_uni and hasattr(ev_uni, "selection"):
                    u_rows = ev_uni.selection.get("rows", [])
                    if u_rows:
                        sel_u_idx = u_rows[0]
                        if sel_u_idx < len(uni_df):
                            open_company_detail(uni_df.iloc[sel_u_idx]["symbol"], return_tab="universe")
                            st.rerun()
