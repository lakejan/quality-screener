# -*- coding: utf-8 -*-
"""
한·미 퀄리티 주식 스크리너 & 유니버스 보관함 (Toss Design System Edition)
- 토스(TDS) & 토스증권 디자인 철학 반영:
  1) 쿨그레이 캔버스(#F2F4F6) 위 순백색 무테두리 라운드 카드(#FFFFFF, 20px)와 명확한 타이포그래피 위계
  2) 과잉 이모지·원색 테두리 제거, 토스 블루(#3182F6) 및 소프트 상태 배지(초록/앰버/레드) 중심의 시각적 절제
  3) PC 2열 바둑판 그리드 & 모바일 1열 자동 반응형 카드 레이아웃
  4) 복잡한 공식 설명은 [ⓘ 지표 공식 가이드] 팝오버로 숨기고, 결론 중심의 자연스러운 한국어 금융 카피라이팅 제공
- 핵심 기능 100% 유지:
  - 모든 조건 통과 / 아깝게 1개 조건 미달 / 전체 종목 원클릭 전환
  - 최근 결산 수치 + 4~5개년 평균 수치(각 결산일 당시 시가총액 기준 FCF 수익률 평균) 동시 표시 및 필터 기준 전환
  - 유니버스 영구 보관함(메모 & 구글 독스 등 웹 URL 원클릭 링크)
  - 기업별 맞춤 성장기간(N년)·예상성장률(g1)·이후성장률(g2) 기반 정밀 2단계 역DCF & 적정 시가총액 시뮬레이터
  - 최근 4~5년 정상화 FCF 연평균 복리 성장률(CAGR) 및 연도별 YoY 성장률 분석
"""

from __future__ import annotations

from datetime import datetime
import html
import importlib
import io
import re
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import data_engine as de
importlib.reload(de)

st.set_page_config(
    page_title="퀄리티 주식 스크리너 · 유니버스",
    page_icon="💙",
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
# 토스 디자인 시스템 (Toss Design System - TDS) 전역 CSS 주입
# =====================================================================
def inject_tds_css() -> None:
    st.markdown(
        """
        <style>
        /* 1. 토스 프리텐다드 타이포그래피 & 한글 단어 끊김 방지 (단, Streamlit Material 아이콘 span 제외) */
        html, body, p, label, table, th, td, h1, h2, h3, h4, .tds-card, .tds-hero {
            word-break: keep-all !important;
            font-family: "Pretendard Variable", "Pretendard", -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Segoe UI", Roboto, sans-serif;
            letter-spacing: -0.015em;
        }
        /* Streamlit Material 아이콘 폰트 철저 보호 (_arrow_right_ 등 텍스트 겹침 완벽 방지) */
        [data-testid="stIconMaterial"], .material-icons, span[translate="no"] {
            font-family: "Material Symbols Rounded", "Material Icons", sans-serif !important;
            word-break: normal !important;
            letter-spacing: normal !important;
        }

        /* 2. 전체 배경 쿨그레이(#F2F4F6) & 상단 여백 확보 */
        .stApp {
            background-color: #F2F4F6 !important;
        }
        .block-container {
            padding-top: 3.8rem !important;
            padding-bottom: 3rem !important;
            padding-left: 1.2rem !important;
            padding-right: 1.2rem !important;
            max-width: 1440px !important;
        }

        /* 사이드바 클린 화이트 스타일링 */
        section[data-testid="stSidebar"] {
            background-color: #FFFFFF !important;
            border-right: 1px solid #E5E8EB !important;
        }

        /* 3. 헤더 타이포그래피 위계 (Toss Ink #191F28) */
        h1 {
            font-size: clamp(1.35rem, 4.5vw, 1.85rem) !important;
            font-weight: 800 !important;
            color: #191F28 !important;
            letter-spacing: -0.03em !important;
            line-height: 1.25 !important;
            margin-bottom: 0.2rem !important;
        }
        h2 {
            font-size: clamp(1.15rem, 3.6vw, 1.45rem) !important;
            font-weight: 800 !important;
            color: #191F28 !important;
            letter-spacing: -0.025em !important;
            line-height: 1.3 !important;
        }
        h3 {
            font-size: clamp(1.02rem, 3.0vw, 1.22rem) !important;
            font-weight: 700 !important;
            color: #191F28 !important;
            letter-spacing: -0.02em !important;
        }

        /* 4. 토스 스타일 상단 탭 (Segmented Underline / Pill Tabs) */
        div[data-baseweb="tab-list"] {
            gap: 8px !important;
            background: transparent !important;
            border-bottom: 1px solid #E5E8EB !important;
            padding-bottom: 0px !important;
        }
        button[data-baseweb="tab"] {
            padding: 10px 18px !important;
            font-size: 0.96rem !important;
            font-weight: 700 !important;
            color: #8B95A1 !important;
            border-radius: 12px 12px 0 0 !important;
            transition: all 0.15s ease !important;
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            color: #191F28 !important;
            font-weight: 800 !important;
        }

        /* 5. Streamlit 기본 컨테이너(border=True)를 토스 화이트 카드로 변환 */
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background-color: #FFFFFF !important;
            border: 1px solid rgba(0, 0, 0, 0.04) !important;
            border-radius: 20px !important;
            padding: 18px 20px !important;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.03) !important;
            margin-bottom: 10px !important;
        }

        /* 6. 버튼 스타일 (토스 라운드 버튼) */
        .stButton > button {
            border-radius: 12px !important;
            font-weight: 700 !important;
            font-size: 0.84rem !important;
            padding: 0.45rem 0.9rem !important;
            border: 1px solid #E5E8EB !important;
            transition: all 0.15s ease !important;
        }
        .stButton > button[kind="primary"] {
            background-color: #3182F6 !important;
            border-color: #3182F6 !important;
            color: #FFFFFF !important;
        }
        .stButton > button[kind="primary"]:hover {
            background-color: #1B64DA !important;
            border-color: #1B64DA !important;
        }
        .stButton > button[kind="secondary"] {
            background-color: #F2F4F6 !important;
            border-color: transparent !important;
            color: #333D4B !important;
        }
        .stButton > button[kind="secondary"]:hover {
            background-color: #E5E8EB !important;
            color: #191F28 !important;
        }

        /* 7. 토스 퍼널(관문) 미니멀 스텝 바 */
        .tds-funnel-bar {
            display: flex;
            align-items: center;
            gap: 6px;
            overflow-x: auto;
            padding: 4px 2px 12px 2px;
            scrollbar-width: none;
        }
        .tds-funnel-pill {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: #FFFFFF;
            border-radius: 999px;
            padding: 5px 12px;
            font-size: 0.78rem;
            font-weight: 600;
            color: #6B7684;
            box-shadow: 0 1px 4px rgba(0,0,0,0.03);
            white-space: nowrap;
            flex-shrink: 0;
        }
        .tds-funnel-pill .cnt {
            color: #191F28;
            font-weight: 800;
        }
        .tds-funnel-pill.active {
            background: #E8F3FF;
            color: #1B64DA;
            font-weight: 700;
        }
        .tds-funnel-pill.active .cnt {
            color: #3182F6;
        }
        .tds-funnel-sep {
            color: #B0B8C1;
            font-size: 0.75rem;
            flex-shrink: 0;
        }

        /* 8. 토스 종목 카드 (.tds-card) */
        .tds-card {
            background: #FFFFFF;
            border-radius: 20px;
            padding: 20px 22px 16px 22px;
            margin-bottom: 8px;
            box-shadow: 0 2px 12px rgba(0, 0, 0, 0.035);
            border: 1.5px solid transparent;
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        .tds-card:hover {
            box-shadow: 0 6px 20px rgba(0, 0, 0, 0.065);
        }
        .tds-card.in-universe {
            border-color: rgba(49, 130, 246, 0.35);
            background: #FFFFFF;
        }
        .tds-card-top {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 8px;
            margin-bottom: 14px;
        }
        .tds-comp-name {
            font-size: 1.15rem;
            font-weight: 800;
            color: #191F28;
            line-height: 1.25;
        }
        .tds-comp-sub {
            font-size: 0.78rem;
            font-weight: 500;
            color: #8B95A1;
            margin-top: 2px;
        }
        .tds-mcap-text {
            font-size: 0.92rem;
            font-weight: 800;
            color: #333D4B;
            text-align: right;
            white-space: nowrap;
        }

        /* 토스 소프트 캡슐 배지 */
        .tds-badge {
            display: inline-flex;
            align-items: center;
            padding: 3px 9px;
            border-radius: 999px;
            font-size: 0.73rem;
            font-weight: 700;
            white-space: nowrap;
        }
        .tds-badge.blue {
            background: #E8F3FF;
            color: #3182F6;
        }
        .tds-badge.green {
            background: #E8FAF0;
            color: #00A84D;
        }
        .tds-badge.amber {
            background: #FFF4E5;
            color: #D97706;
        }
        .tds-badge.red {
            background: #FFEEEE;
            color: #E11D48;
        }
        .tds-badge.gray {
            background: #F2F4F6;
            color: #4E5968;
        }

        /* 카드 내 역DCF 밸류에이션 하이라이트 영역 */
        .tds-val-banner {
            background: #F9FAFB;
            border-radius: 14px;
            padding: 12px 16px;
            margin-bottom: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 10px;
        }
        .tds-val-banner.blue-tint {
            background: #F4F8FF;
        }
        .tds-val-lbl {
            font-size: 0.74rem;
            font-weight: 600;
            color: #6B7684;
            margin-bottom: 2px;
        }
        .tds-val-main {
            font-size: 1.25rem;
            font-weight: 800;
            color: #191F28;
            line-height: 1.2;
        }
        .tds-val-main.accent {
            color: #3182F6;
        }
        .tds-val-sub {
            font-size: 0.74rem;
            font-weight: 600;
            color: #8B95A1;
            margin-top: 2px;
        }

        /* 카드 내 4대 지표 미니멀 그리드 */
        .tds-metric-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 8px;
            margin-bottom: 10px;
        }
        @media (max-width: 640px) {
            .tds-metric-grid {
                grid-template-columns: repeat(2, 1fr);
            }
        }
        .tds-metric-cell {
            background: #F9FAFB;
            border-radius: 12px;
            padding: 10px 10px;
            text-align: left;
        }
        .tds-metric-cell.missed {
            background: #FFF8F8;
            border: 1px solid rgba(225, 29, 72, 0.18);
        }
        .tds-m-lbl {
            font-size: 0.72rem;
            font-weight: 600;
            color: #8B95A1;
            margin-bottom: 3px;
            white-space: nowrap;
        }
        .tds-m-val {
            font-size: 1.05rem;
            font-weight: 800;
            color: #191F28;
            line-height: 1.2;
        }
        .tds-m-avg {
            font-size: 0.72rem;
            font-weight: 600;
            color: #6B7684;
            margin-top: 3px;
            white-space: nowrap;
        }

        /* CCR 한 줄 인사이트 캡션 */
        .tds-ccr-caption {
            font-size: 0.75rem;
            color: #6B7684;
            background: #F9FAFB;
            border-radius: 10px;
            padding: 6px 11px;
            margin-top: 6px;
        }

        /* 메모 & 구글독스 웹 링크 칩 */
        .tds-memo-box {
            background: #F9FAFB;
            border-radius: 12px;
            padding: 10px 14px;
            margin-top: 8px;
            font-size: 0.80rem;
            color: #333D4B;
            line-height: 1.45;
        }
        .tds-link-pill {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            background: #E8F3FF;
            color: #3182F6 !important;
            text-decoration: none !important;
            padding: 4px 11px;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 700;
            margin-right: 6px;
            margin-top: 6px;
            transition: background 0.15s ease;
        }
        .tds-link-pill:hover {
            background: #D0E6FF;
        }

        /* 상세 페이지 히어로 카드 & 결론 카드 */
        .tds-hero {
            background: #FFFFFF;
            border-radius: 24px;
            padding: 24px 26px;
            margin-bottom: 14px;
            box-shadow: 0 2px 14px rgba(0, 0, 0, 0.04);
        }
        .tds-kpi-strip {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
            gap: 10px;
            margin-top: 18px;
        }
        .tds-kpi-box {
            background: #F9FAFB;
            border-radius: 16px;
            padding: 14px 14px;
            text-align: left;
        }
        .tds-kpi-box.highlight {
            background: #F4F8FF;
        }
        .tds-conclusion-card {
            background: #F9FAFB;
            border-radius: 18px;
            padding: 18px 20px;
            height: 100%;
        }
        .tds-conclusion-card.blue {
            background: #F4F8FF;
        }
        .tds-conclusion-card.green {
            background: #F2FBF6;
        }
        .tds-conclusion-title {
            font-size: 0.78rem;
            font-weight: 700;
            color: #6B7684;
            margin-bottom: 6px;
        }
        .tds-conclusion-headline {
            font-size: 1.05rem;
            font-weight: 700;
            color: #191F28;
            line-height: 1.45;
            margin-bottom: 8px;
        }
        .tds-conclusion-sub {
            font-size: 0.78rem;
            color: #6B7684;
            line-height: 1.4;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


inject_tds_css()


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


def render_raw_html(raw_html: str) -> None:
    """여러 줄 HTML 문자열의 앞쪽 들여쓰기 공백과 빈 줄을 제거하여 마크다운 코드블록(<pre><code>) 변환을 100% 방지합니다."""
    clean_html = "\n".join(line.strip() for line in raw_html.splitlines() if line.strip())
    st.markdown(clean_html, unsafe_allow_html=True)


def extract_urls_from_text(text: str) -> List[str]:
    """메모 텍스트 내의 http:// 또는 https:// 웹 URL을 자동 추출합니다."""
    if not text:
        return []
    pattern = r"https?://[^\s<>\"')\]}]+"
    return re.findall(pattern, text)


def render_memo_with_links_html(memo_text: str) -> str:
    """토스 스타일 메모 박스 및 웹 URL(구글독스 등) 바로가기 캡슐 버튼 HTML 생성"""
    if not memo_text or not str(memo_text).strip():
        return ""

    escaped_memo = html.escape(str(memo_text)).replace("\n", "<br>")
    urls = extract_urls_from_text(str(memo_text))
    links_html = ""
    if urls:
        chips = []
        for idx, u in enumerate(urls, 1):
            domain_label = "구글 독스 · 시트 열기" if "docs.google.com" in u else (
                "노션(Notion) 열기" if "notion." in u else f"연결된 링크 #{idx} 열기"
            )
            safe_u = html.escape(u, quote=True)
            chips.append(
                f"<a class='tds-link-pill' href='{safe_u}' target='_blank' rel='noopener noreferrer'>🔗 {domain_label} ↗</a>"
            )
        links_html = "<div>" + "".join(chips) + "</div>"

    return (
        f"<div class='tds-memo-box'>"
        f"<div>{escaped_memo}</div>"
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
# 지표별 계산 공식 및 설명 사전 (팝오버 가이드 & 툴팁용)
# =====================================================================
METRIC_DEFINITIONS: Dict[str, Dict[str, str]] = {
    "GPM (%)": {
        "title": "매출총이익률 (GPM)",
        "formula": "(매출총이익 ÷ 매출액) × 100",
        "desc": "원가 경쟁력과 가격 결정력(Pricing Power)을 보여줘요. 최근 수치와 4~5년 평균을 함께 보아 일시적 호황인지 구조적 해자인지 판별합니다.",
    },
    "OPM (%)": {
        "title": "영업이익률 (OPM)",
        "formula": "(영업이익 ÷ 매출액) × 100",
        "desc": "매출에서 원가와 판관비를 모두 빼고 본업에서 남긴 순수 마진율이에요.",
    },
    "ROCE (%)": {
        "title": "사용자본이익률 (ROCE)",
        "formula": "영업이익(EBIT) ÷ 사용자본(총자산 - 유동부채) × 100\n• 듀퐁 분해: EBIT 마진율 × 사용자본회전율",
        "desc": "주주와 채권자가 사업에 묶어둔 자본으로 얼마나 효율적으로 이익을 냈는지 보여주는 퀄리티 투자 핵심 지표예요.",
    },
    "CCR (%)": {
        "title": "현금전환율 (CCR)",
        "formula": "기본(세후 일치): (영업현금흐름 - CapEx) ÷ 당기순이익 × 100\n테리 스미스(세전): (영업현금흐름 + 법인세 - CapEx) ÷ 영업이익 × 100",
        "desc": "장부상 이익이 실제 통장에 꽂히는 잉여현금흐름(FCF)으로 얼마나 전환되는지(이익의 질)를 측정해요.",
    },
    "이자보상배율": {
        "title": "이자보상배율",
        "formula": "영업이익(EBIT) ÷ 이자비용 (배)",
        "desc": "영업이익으로 이자비용을 몇 배나 감당할 수 있는지 보여줘요. 무차입·순현금 흑자 기업은 ∞로 자동 통과됩니다.",
    },
    "정상화 FCF 수익률 (%)": {
        "title": "정상화 FCF 수익률 (최근 vs 당시 시총 평균)",
        "formula": "• 정상화 FCF = 영업현금흐름(OCF) - 감가상각비(D&A)\n• 최근 FCF 수익률 = 최근 정상화 FCF ÷ 현재 시가총액\n• 4~5년 평균 FCF 수익률 = 각 결산연도 (당시 정상화 FCF ÷ 결산 당시 시가총액)의 평균",
        "desc": "과거 4~5년간 시장에서 평균 몇 %의 FCF 수익률(밸류에이션)로 거래되었는지와 오늘의 FCF 수익률을 직접 비교해요.",
    },
    "역DCF 기대성장률 (%)": {
        "title": "역DCF 내포 기대성장률 (영구 vs N년 한정)",
        "formula": "• 영구 역DCF g = 요구수익률(r) - FCF 수익률\n• N년 한정 정밀 역DCF: 향후 N년간 g1으로 성장 후 성숙기(g2, 말기 FCF수익률 = r - g2)로 둔화될 때 현재 시총을 정당화하는 g1 역산",
        "desc": "현재 주가를 정당화하기 위해 앞으로 기업이 매년 달성해야 하는 성장률 허들이에요. 숫자가 낮을수록 안전마진이 높습니다.",
    },
}


def get_metric_tooltip(metric_key: str) -> str:
    info = METRIC_DEFINITIONS.get(metric_key)
    if not info:
        return ""
    return f"[계산 공식]\n{info['formula']}\n\n[해석]\n{info['desc']}"


def render_formula_guide_popover() -> None:
    """우측 상단에 깔끔하게 숨겨진 토스 스타일 [ⓘ 지표 공식 가이드] 팝오버"""
    with st.popover("ⓘ 지표 공식 가이드", use_container_width=True):
        st.markdown("#### 📐 핵심 지표 계산 공식 & 해석 가이드")
        st.caption("모든 지표는 최근 결산 수치와 최근 4~5개년 평균 수치를 함께 산출합니다.")
        for m_key, info in METRIC_DEFINITIONS.items():
            st.markdown(f"**{info['title']}**")
            st.code(info["formula"], language="text")
            st.caption(info["desc"])
            st.markdown("---")


# =====================================================================
# 사이드바: 토스 스타일 클린 설정 패널
# =====================================================================
st.sidebar.markdown("### 🎯 스크리너 설정")

universe_store = de.load_universe_store()
st.sidebar.caption(f"⭐ 유니버스 보관함 · **{len(universe_store)}개** 기업 보관 중")

market_choice = st.sidebar.radio(
    "분석 시장",
    options=["KR (한국)", "US (미국)", "ALL (한·미 통합)"],
    index=0,
    horizontal=True,
)

if market_choice.startswith("KR"):
    selected_market = "KR"
    sub_market_choice = st.sidebar.selectbox(
        "세부 거래소",
        options=["전체 (코스피 + 코스닥)", "KR (KOSPI)", "KR (KOSDAQ)"],
        index=0,
    )
elif market_choice.startswith("US"):
    selected_market = "US"
    sub_market_choice = st.sidebar.selectbox(
        "세부 거래소",
        options=["전체 (나스닥 + NYSE)", "US (NASDAQ)", "US (NYSE)"],
        index=0,
    )
else:
    selected_market = "ALL"
    sub_market_choice = st.sidebar.selectbox(
        "세부 거래소",
        options=["전체 시장", "KR (KOSPI)", "KR (KOSDAQ)", "US (NASDAQ)", "US (NYSE)"],
        index=0,
    )

if st.sidebar.button("⚡ 실시간 주가 · 시총 갱신", use_container_width=True, type="primary"):
    with st.sidebar:
        with st.spinner("최신 주가 및 시가총액 갱신 중..."):
            cnt = de.refresh_prices_and_market_cap(selected_market)
            st.session_state["last_price_refresh"] = datetime.now().strftime("%H:%M:%S")
            st.cache_data.clear()
        st.toast(f"✅ {cnt}개 기업 주가·시총 갱신 완료!")
        st.rerun()

if "last_price_refresh" in st.session_state:
    st.sidebar.caption(f"최근 주가 갱신: `{st.session_state['last_price_refresh']}`")

st.sidebar.markdown("---")
st.sidebar.markdown("#### 🔍 핵심 4대 필터 기준")

# [필터 1] GPM
st.sidebar.markdown("**매출총이익률 (GPM)**", help=get_metric_tooltip("GPM (%)"))
c1, c2, c3 = st.sidebar.columns([1.1, 1.3, 2.0])
use_gpm = c1.checkbox("켜기", value=True, key="chk_gpm")
op_gpm = c2.selectbox("연산", [">=", "<=", ">", "<"], index=0, key="op_gpm", label_visibility="collapsed")
val_gpm = c3.number_input("GPM(%)", value=40.0, step=5.0, key="val_gpm", label_visibility="collapsed")

# [필터 2] ROCE
st.sidebar.markdown("**사용자본이익률 (ROCE)**", help=get_metric_tooltip("ROCE (%)"))
c1, c2, c3 = st.sidebar.columns([1.1, 1.3, 2.0])
use_roce = c1.checkbox("켜기", value=True, key="chk_roce")
op_roce = c2.selectbox("연산", [">=", "<=", ">", "<"], index=0, key="op_roce", label_visibility="collapsed")
val_roce = c3.number_input("ROCE(%)", value=15.0, step=2.5, key="val_roce", label_visibility="collapsed")

# [필터 3] CCR
st.sidebar.markdown("**현금전환율 (CCR)**", help=get_metric_tooltip("CCR (%)"))
c1, c2, c3 = st.sidebar.columns([1.1, 1.3, 2.0])
use_ccr = c1.checkbox("켜기", value=True, key="chk_ccr")
op_ccr = c2.selectbox("연산", [">=", "<=", ">", "<"], index=0, key="op_ccr", label_visibility="collapsed")
val_ccr = c3.number_input("CCR(%)", value=95.0, step=5.0, key="val_ccr", label_visibility="collapsed")

# [필터 4] 이자보상배율
st.sidebar.markdown("**이자보상배율 (배)**", help=get_metric_tooltip("이자보상배율"))
c1, c2, c3 = st.sidebar.columns([1.1, 1.3, 2.0])
use_icr = c1.checkbox("켜기", value=True, key="chk_icr")
op_icr = c2.selectbox("연산", [">=", "<=", ">", "<"], index=0, key="op_icr", label_visibility="collapsed")
val_icr = c3.number_input("이자보상(배)", value=10.0, step=5.0, key="val_icr", label_visibility="collapsed")

st.sidebar.markdown("---")
with st.sidebar.expander("⚙️ 산식 옵션 & 요구수익률(r)", expanded=False):
    required_return_r = st.number_input(
        "요구수익률 · 할인율 r (%)",
        min_value=5.0,
        max_value=25.0,
        value=10.0,
        step=0.5,
        help=get_metric_tooltip("역DCF 기대성장률 (%)"),
    )
    deduct_cash_opt = st.checkbox(
        "사용자본(CE)에서 현금 차감",
        value=False,
        help="체크 시 (총자산 - 유동부채 - 현금성자산)으로 현금 부자 기업의 실질 ROCE를 계산합니다.",
    )
    ccr_denom_label = st.selectbox(
        "CCR 산출 공식",
        options=[
            "권장 A (세후 일치): (OCF - CapEx) / 당기순이익",
            "권장 B (테리 스미스): (OCF + 법인세 - CapEx) / 영업이익",
            "대안 C (단순): (OCF - CapEx) / 영업이익",
            "대안 D (CapEx 미차감): OCF / 영업이익",
        ],
        index=0,
    )
    if "당기순이익" in ccr_denom_label:
        ccr_denom_key = "net_income"
    elif "테리 스미스" in ccr_denom_label:
        ccr_denom_key = "pretax_ebit"
    elif "미차감" in ccr_denom_label:
        ccr_denom_key = "ocf_only"
    else:
        ccr_denom_key = "ebit"

    allow_missing_gpm = st.checkbox(
        "GPM 결측 시 OPM으로 대체",
        value=False,
    )

with st.sidebar.expander("➕ 추가 필터 조건 (선택)", expanded=False):
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
        st.caption(f"추가 조건 #{i}")
        m_sel = st.selectbox(f"지표 #{i}", extra_metrics_avail, index=0, key=f"ext_m_{i}", label_visibility="collapsed")
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

with st.sidebar.expander("🔄 데이터 수집 · 개별 종목 추가", expanded=False):
    fetch_target_mkt = st.selectbox("수집 시장", ["KR", "US"], index=0 if selected_market != "US" else 1)
    if fetch_target_mkt == "KR":
        min_mcap_uk = st.number_input("최소 시가총액 (억 원)", min_value=500, max_value=100000, value=2000, step=500)
        min_mcap_raw = float(min_mcap_uk) * 1e8
    else:
        min_mcap_bil = st.number_input("최소 시가총액 ($B)", min_value=1.0, max_value=500.0, value=10.0, step=1.0)
        min_mcap_raw = float(min_mcap_bil) * 1e9

    max_fetch_cnt = st.slider("최대 수집 기업 수", min_value=30, max_value=300, value=150, step=10)
    pre_gpm_cut = st.number_input("1차 프리필터 최소 GPM (%)", min_value=0, max_value=80, value=25, step=5)

    if st.button("🚀 5개년 재무데이터 새로 수집", use_container_width=True):
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
            prog_bar = st.progress(0, text=f"0 / {len(uni_items)} 기업 수집 중...")

            def _update_prog(done: int, total: int) -> None:
                prog_bar.progress(done / total, text=f"{done} / {total} 기업 5개년 재무 & 당시 시총 파싱 중...")

            new_df = de.fetch_batch_raw_financials(uni_items, max_workers=12, progress_callback=_update_prog)
            de.save_raw_cache(new_df, fetch_target_mkt)
            prog_bar.empty()
            st.success(f"{fetch_target_mkt} 시장 {len(new_df)}개 기업 저장 완료!")
            st.rerun()

    st.markdown("---")
    custom_tickers_input = st.text_input(
        "개별 종목 티커 직접 추가",
        placeholder="예: 058470.KQ, MSFT",
    )
    add_directly_to_universe = st.checkbox("추가와 동시에 ⭐ 유니버스에도 담기", value=True)
    if st.button("종목 추가하기", use_container_width=True) and custom_tickers_input.strip():
        raw_tokens = [t.strip().upper() for t in custom_tickers_input.split(",") if t.strip()]
        krx_map = de.load_krx_name_map()
        kr_add_items, us_add_items = [], []

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
            st.success(f"{added_cnt}개 종목 추가 완료!")
            st.rerun()
        else:
            st.warning("유효한 재무제표를 찾을 수 없습니다.")


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
    st.title("퀄리티 주식 스크리너")
    st.info("아직 로컬 캐시 데이터가 없습니다. 아래 버튼을 눌러 기본 유니버스를 수집하세요.")
    if st.button("⚡ 기본 유니버스(한국/미국 주요 종목) 지금 바로 수집하기", type="primary"):
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
# 🏢 토스증권 스타일 [기업 심층 상세 페이지] 렌더링 함수
# =====================================================================
def render_company_detail_page(symbol: str) -> None:
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

    # 1. 최상단 네비게이션 바
    nav_c1, nav_c2, nav_c3 = st.columns([2.2, 5.0, 2.0])
    with nav_c1:
        ret_label = "⬅️ 유니버스 보관함으로" if st.session_state.get("detail_return_tab") == "universe" else "⬅️ 스크리너 목록으로"
        if st.button(ret_label, type="secondary", use_container_width=True):
            close_company_detail()
            st.rerun()
    with nav_c2:
        all_sym_options = [
            f"{'⭐ ' if r['symbol'] in uni_store else ''}{r['name']} ({r['symbol']}) · {r.get('시가총액_표시', '')}"
            for _, r in all_metrics_df.iterrows()
        ]
        sym_lookup = {opt: r["symbol"] for opt, (_, r) in zip(all_sym_options, all_metrics_df.iterrows())}
        cur_idx = next((i for i, (_, r) in enumerate(all_metrics_df.iterrows()) if r["symbol"] == symbol), 0)
        jumped_opt = st.selectbox(
            "다른 기업 바로 검색",
            options=all_sym_options,
            index=cur_idx,
            label_visibility="collapsed",
        )
        if sym_lookup.get(jumped_opt) and sym_lookup[jumped_opt] != symbol:
            open_company_detail(sym_lookup[jumped_opt], st.session_state.get("detail_return_tab", "screener"))
            st.rerun()
    with nav_c3:
        if in_uni:
            if st.button("⭐ 유니버스 보관중 (해제)", type="secondary", use_container_width=True):
                de.remove_universe_item(symbol)
                st.toast(f"🗑️ {comp_name} 종목을 유니버스에서 제거했습니다.")
                st.rerun()
        else:
            if st.button("⭐ 유니버스에 보관하기", type="primary", use_container_width=True):
                de.upsert_universe_item(symbol=symbol, name=comp_name, market=mkt_code)
                st.toast(f"⭐ {comp_name} 종목을 유니버스 보관함에 담았습니다!")
                st.rerun()

    # 2. 토스증권 스타일 Top Hero Card
    gpm_now, gpm_5y = row_data.get("GPM (%)", np.nan), row_data.get("GPM_5Y (%)", np.nan)
    opm_now, opm_5y = row_data.get("OPM (%)", np.nan), row_data.get("OPM_5Y (%)", np.nan)
    roce_now, roce_5y = row_data.get("ROCE (%)", np.nan), row_data.get("ROCE_5Y (%)", np.nan)
    ccr_now, ccr_5y = row_data.get("CCR (%)", np.nan), row_data.get("CCR_5Y (%)", np.nan)
    fcf_y_now = row_data.get("정상화 FCF 수익률 (%)", np.nan)
    int_cov_str = str(row_data.get("이자보상배율_표시", "N/A"))

    def _f_pct(v: float) -> str:
        return f"{v:.1f}%" if pd.notna(v) else "N/A"

    uni_pill_html = "<span class='tds-badge blue'>⭐ 유니버스 보관 종목</span>" if in_uni else ""
    fcf_growth_pill = f"<span class='tds-badge green'>FCF 성장 {html.escape(fcf_cagr_str)}</span>" if pd.notna(fcf_cagr_num) and fcf_cagr_num > 0 else f"<span class='tds-badge gray'>FCF {html.escape(fcf_cagr_str)}</span>"
    memo_preview_in_hero = render_memo_with_links_html(uni_info.get("memo", "")) if uni_info.get("memo") else ""

    hero_html = f"""
    <div class="tds-hero">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:12px;">
            <div>
                <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
                    <span style="font-size:1.6rem; font-weight:800; color:#191F28;">{html.escape(comp_name)}</span>
                    <span style="font-size:0.95rem; font-weight:600; color:#8B95A1;">{html.escape(symbol)}</span>
                    <span class="tds-badge gray">{html.escape(str(mkt_disp))}</span>
                    {uni_pill_html}
                    {fcf_growth_pill}
                </div>
                <div style="font-size:0.82rem; color:#8B95A1; margin-top:4px;">
                    최근 결산일 {html.escape(str(row_data['fiscal_date']))} · { html.escape(str(row_data.get('CCR 상태 진단', ''))) }
                </div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:0.76rem; font-weight:600; color:#8B95A1;">현재 시가총액</div>
                <div style="font-size:1.45rem; font-weight:800; color:#191F28;">{html.escape(str(row_data['시가총액_표시']))}</div>
            </div>
        </div>
        {memo_preview_in_hero}
        <div class="tds-kpi-strip">
            <div class="tds-kpi-box">
                <div class="tds-m-lbl">매출총이익률 GPM</div>
                <div class="tds-m-val" style="font-size:1.25rem;">{_f_pct(gpm_now)}</div>
                <div class="tds-m-avg">{avg_yr_cnt}년 평균 {_f_pct(gpm_5y)}</div>
            </div>
            <div class="tds-kpi-box">
                <div class="tds-m-lbl">영업이익률 OPM</div>
                <div class="tds-m-val" style="font-size:1.25rem;">{_f_pct(opm_now)}</div>
                <div class="tds-m-avg">{avg_yr_cnt}년 평균 {_f_pct(opm_5y)}</div>
            </div>
            <div class="tds-kpi-box">
                <div class="tds-m-lbl">사용자본이익률 ROCE</div>
                <div class="tds-m-val" style="font-size:1.25rem; color:#3182F6;">{_f_pct(roce_now)}</div>
                <div class="tds-m-avg">{avg_yr_cnt}년 평균 {_f_pct(roce_5y)}</div>
            </div>
            <div class="tds-kpi-box">
                <div class="tds-m-lbl">현금전환율 CCR</div>
                <div class="tds-m-val" style="font-size:1.25rem;">{_f_pct(ccr_now)}</div>
                <div class="tds-m-avg">{avg_yr_cnt}년 평균 {_f_pct(ccr_5y)}</div>
            </div>
            <div class="tds-kpi-box highlight">
                <div class="tds-m-lbl" style="color:#3182F6;">{avg_yr_cnt}개년 FCF 연평균 성장률</div>
                <div class="tds-m-val" style="font-size:1.12rem; color:#1B64DA;">{html.escape(fcf_cagr_str)}</div>
                <div class="tds-m-avg">당시시총 평균 FCF수익률 {_f_pct(hist_fcf_yield_avg)}</div>
            </div>
            <div class="tds-kpi-box">
                <div class="tds-m-lbl">이자보상배율</div>
                <div class="tds-m-val" style="font-size:1.08rem;">{html.escape(int_cov_str)}</div>
                <div class="tds-m-avg">현재 FCF수익률 {_f_pct(fcf_y_now)}</div>
            </div>
        </div>
    </div>
    """
    render_raw_html(hero_html)

    # 3. 토스 스타일 N년 정밀 2단계 역DCF & 내재가치 시뮬레이터 카드
    with st.container(border=True):
        st.markdown("#### 💡 기업별 맞춤 성장기간($N$년) 역DCF & 적정 시가총액 계산기")
        st.caption(
            f"이 기업의 과거 실제 FCF 성장률은 **`{fcf_cagr_str}`**입니다. 경쟁우위가 지속될 기간($N$년)과 예상 성장률을 조절해 현재 주가의 기대치와 비교해 보세요."
        )

        p_col1, p_col2, p_col3, p_col4, p_col5 = st.columns([1.9, 1.4, 1.6, 1.6, 1.8])
        with p_col1:
            fcf_base_choice = st.radio(
                "기준 정상화 FCF",
                options=["최근 결산 FCF", f"{avg_yr_cnt}개년 평균 FCF"],
                index=0,
                key=f"fcf_base_{symbol}",
            )
        with p_col2:
            n_years_input = st.number_input(
                "성장 지속기간 N (년)",
                min_value=1,
                max_value=40,
                value=int(uni_info.get("growth_years", 10)),
                step=1,
                key=f"n_yr_{symbol}",
            )
        with p_col3:
            g1_est_input = st.number_input(
                "성장기간 예상 성장률 g1 (%)",
                min_value=-30.0,
                max_value=100.0,
                value=float(uni_info.get("growth_rate_est", 10.0)),
                step=1.0,
                key=f"g1_est_{symbol}",
            )
        with p_col4:
            g2_term_input = st.number_input(
                "N년 이후 영구성장률 g2 (%)",
                min_value=-10.0,
                max_value=float(required_return_r - 0.5),
                value=float(uni_info.get("terminal_growth_rate", 0.0)),
                step=0.5,
                key=f"g2_term_{symbol}",
            )
        with p_col5:
            st.write("")
            if st.button("💾 유니버스에 이 가정 저장", key=f"save_dcf_params_{symbol}", type="primary", use_container_width=True):
                de.upsert_universe_item(
                    symbol=symbol,
                    name=comp_name,
                    market=mkt_code,
                    growth_years=int(n_years_input),
                    growth_rate_est=float(g1_est_input),
                    terminal_growth_rate=float(g2_term_input),
                )
                st.toast(f"⭐ {comp_name}의 성장기간({n_years_input}년) 가정이 유니버스에 저장되었습니다!")
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
        stage2_g_str = f"{two_stage_implied_g:+.2f}%" if pd.notna(two_stage_implied_g) else "산출불가(FCF≤0)"
        fair_mcap_str = format_currency_amount(fair_mcap, mkt_code) if pd.notna(fair_mcap) else "N/A"
        upside_str = f"{upside_pct:+.1f}%" if pd.notna(upside_pct) else "N/A"
        term_yield_str = f"{term_yield_pct:.1f}%" if pd.notna(term_yield_pct) else "N/A"
        upside_word = "저평가(상승여력)" if (pd.notna(upside_pct) and upside_pct >= 0) else "고평가(프리미엄)"

        conclusion_html = f"""
        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap:12px; margin-top:10px;">
            <div class="tds-conclusion-card blue">
                <div class="tds-conclusion-title" style="color:#3182F6;">시장의 요구치 · {int(n_years_input)}년 한정 정밀 역DCF</div>
                <div class="tds-conclusion-headline">
                    {int(n_years_input)}년 뒤 성장이 {g2_term_input:.1f}%로 둔화된다면,<br>
                    현재 시총을 정당화하기 위해 <b>향후 {int(n_years_input)}년간 매년 <span style="color:#3182F6; font-size:1.25rem;">{stage2_g_str}</span></b> 성장해야 해요.
                </div>
                <div class="tds-conclusion-sub">
                    • 영구성장 가정 시 기대성장률: <b>{perp_g_str}</b> (과거 {avg_yr_cnt}년 당시시총 평균: <b>{hist_g_str}</b>)<br>
                    • {int(n_years_input)}년 뒤 성숙기 적정 FCF 수익률: <b>{term_yield_str}</b> (요구수익률 r={required_return_r:.1f}% 기준)
                </div>
            </div>
            <div class="tds-conclusion-card green">
                <div class="tds-conclusion-title" style="color:#00A84D;">나의 가치평가 · 예상 성장률(연 {g1_est_input:+.1f}%) 달성 시</div>
                <div class="tds-conclusion-headline">
                    향후 {int(n_years_input)}년간 연 <b>{g1_est_input:+.1f}%</b> 성장 시 적정 시총은 <b><span style="color:#00A84D; font-size:1.22rem;">{fair_mcap_str}</span></b>으로,<br>
                    현재 시총 대비 <b>{upside_str} {upside_word}</b> 구간이에요.
                </div>
                <div class="tds-conclusion-sub">
                    • 기준 정상화 FCF: <b>{fcf_str}</b> (현재 FCF수익률 <b>{yield_str}</b> vs 과거 당시시총 평균 <b>{hist_yield_str}</b>)<br>
                    • 1~{int(n_years_input)}년 현금흐름 현가 <b>{format_currency_amount(dcf_res['pv_stage1'], mkt_code)}</b> + {int(n_years_input)}년 뒤 잔존가치 현가 <b>{format_currency_amount(dcf_res['pv_terminal'], mkt_code)}</b>
                </div>
            </div>
        </div>
        """
        render_raw_html(conclusion_html)

    # 4. 하단 심층 분석 3단 탭 (5개년 재무 추이 / ROCE 듀퐁 & CCR 브릿지 / 메모 & 링크 관리)
    d_tab1, d_tab2, d_tab3 = st.tabs([
        f"📈 {avg_yr_cnt}개년 재무 추이 & 차트",
        "🔬 ROCE 듀퐁 & CCR 현금흐름 해부",
        "📝 기업 메모 & 구글독스 링크 편집",
    ])

    with d_tab1:
        if not df_multi.empty:
            with st.container(border=True):
                st.markdown(f"#### 최근 {len(df_multi)}개년 연도별 궤적 및 다개년 평균 · FCF 성장률")
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
                    ("매출총이익률 GPM", [f"{v:.1f}%" if pd.notna(v) else "N/A" for v in df_multi["GPM (%)"]], _mean_str(df_multi["GPM (%)"])),
                    ("영업이익률 OPM", [f"{v:.1f}%" if pd.notna(v) else "N/A" for v in df_multi["OPM (%)"]], _mean_str(df_multi["OPM (%)"])),
                    ("사용자본이익률 ROCE", [f"{v:.1f}%" if pd.notna(v) else "N/A" for v in df_multi["ROCE (%)"]], _mean_str(df_multi["ROCE (%)"])),
                    ("  ↳ EBIT 마진율", [f"{v:.1f}%" if pd.notna(v) else "N/A" for v in df_multi["EBIT Margin (%)"]], _mean_str(df_multi["EBIT Margin (%)"])),
                    ("  ↳ 사용자본회전율", [f"{v:.2f}배" if pd.notna(v) else "N/A" for v in df_multi["사용자본회전율 (배)"]], _mean_str(df_multi["사용자본회전율 (배)"], "{:.2f}배")),
                    ("현금전환율 CCR", [f"{v:.1f}%" if pd.notna(v) else "N/A" for v in df_multi["CCR (%)"]], _mean_str(df_multi["CCR (%)"])),
                    ("  ↳ CapEx / 감가상각비", [f"{v:.0f}%" if pd.notna(v) else "N/A" for v in df_multi["CapEx/감가상각비 (%)"]], _mean_str(df_multi["CapEx/감가상각비 (%)"], "{:.0f}%")),
                    ("  ↳ 운전자본변동 / EBIT", [f"{v:+.1f}%" if pd.notna(v) else "N/A" for v in df_multi["운전자본변동/EBIT (%)"]], _mean_str(df_multi["운전자본변동/EBIT (%)"], "{:+.1f}%")),
                    ("이자보상배율", df_multi["이자보상배율"].tolist(), "-"),
                    ("정상화 FCF (OCF - D&A)", [_fmt_amt(v) for v in df_multi["norm_fcf"]], _mean_amt(df_multi["norm_fcf"])),
                    ("정상화 FCF 성장률 (YoY / CAGR)", [f"{v:+.1f}%" if pd.notna(v) else "-" for v in yoy_col], f"CAGR {fcf_cagr_str}"),
                    ("결산일 당시 시가총액", [_fmt_amt(v) for v in hist_mcap_col], _mean_amt(hist_mcap_col)),
                    ("당시 시총 대비 FCF 수익률", [f"{v:.2f}%" if pd.notna(v) else "N/A" for v in hist_yield_col], _mean_str(hist_yield_col, "{:.2f}%")),
                    ("회계상 FCF (OCF - CapEx)", [_fmt_amt(v) for v in df_multi["fcf"]], _mean_amt(df_multi["fcf"])),
                    ("매출액", [_fmt_amt(v) for v in df_multi["revenue"]], _mean_amt(df_multi["revenue"])),
                    ("영업이익 (EBIT)", [_fmt_amt(v) for v in df_multi["operating_income"]], _mean_amt(df_multi["operating_income"])),
                    ("당기순이익", [_fmt_amt(v) for v in df_multi["net_income"]], _mean_amt(df_multi["net_income"])),
                    ("영업현금흐름 (OCF)", [_fmt_amt(v) for v in df_multi["ocf"]], _mean_amt(df_multi["ocf"])),
                    ("자본적지출 (CapEx)", [_fmt_amt(v) for v in df_multi["capex"]], _mean_amt(df_multi["capex"])),
                    ("감가상각비 (D&A)", [_fmt_amt(v) for v in df_multi["da"]], _mean_amt(df_multi["da"])),
                    ("사용자본 (CE)", [_fmt_amt(v) for v in df_multi["ce"]], _mean_amt(df_multi["ce"])),
                ]

                table_data: Dict[str, List[str]] = {"항목": [r[0] for r in metric_rows]}
                for idx, hdr in enumerate(col_headers):
                    table_data[hdr] = [r[1][idx] for r in metric_rows]
                table_data[f"{len(df_multi)}개년 평균 · CAGR"] = [r[2] for r in metric_rows]

                multi_display_df = pd.DataFrame(table_data)
                st.dataframe(multi_display_df, use_container_width=True, hide_index=True)

            c_chart1, c_chart2 = st.columns(2)
            with c_chart1:
                with st.container(border=True):
                    years_x = [d[:4] for d in col_dates]
                    fig_margin = go.Figure()
                    fig_margin.add_trace(go.Scatter(
                        x=years_x,
                        y=df_multi["GPM (%)"],
                        mode="lines+markers+text",
                        name="GPM (%)",
                        text=[f"{v:.1f}%" if pd.notna(v) else "" for v in df_multi["GPM (%)"]],
                        textposition="top center",
                        line=dict(color="#3182F6", width=3),
                    ))
                    fig_margin.add_trace(go.Scatter(
                        x=years_x,
                        y=df_multi["OPM (%)"],
                        mode="lines+markers+text",
                        name="OPM (%)",
                        text=[f"{v:.1f}%" if pd.notna(v) else "" for v in df_multi["OPM (%)"]],
                        textposition="top center",
                        line=dict(color="#00A84D", width=2, dash="dash"),
                    ))
                    fig_margin.add_trace(go.Scatter(
                        x=years_x,
                        y=df_multi["ROCE (%)"],
                        mode="lines+markers+text",
                        name="ROCE (%)",
                        text=[f"{v:.1f}%" if pd.notna(v) else "" for v in df_multi["ROCE (%)"]],
                        textposition="bottom center",
                        line=dict(color="#F04452", width=3),
                    ))
                    fig_margin.update_layout(
                        title=dict(text=f"마진율 & ROCE {len(df_multi)}개년 추이", font=dict(size=14, color="#191F28")),
                        plot_bgcolor="#FFFFFF",
                        paper_bgcolor="#FFFFFF",
                        xaxis_title="결산연도",
                        yaxis_title="비율 (%)",
                        height=320,
                        margin=dict(l=15, r=15, t=40, b=50),
                        legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5),
                    )
                    st.plotly_chart(fig_margin, use_container_width=True)

            with c_chart2:
                with st.container(border=True):
                    unit_d = 1e8 if mkt_code == "KR" else 1e6
                    u_str = "억 원" if mkt_code == "KR" else "$M"

                    fig_cf = go.Figure()
                    fig_cf.add_trace(go.Bar(
                        x=years_x,
                        y=df_multi["operating_income"] / unit_d,
                        name="영업이익(EBIT)",
                        marker_color="#D1D6DB",
                    ))
                    fig_cf.add_trace(go.Bar(
                        x=years_x,
                        y=df_multi["net_income"] / unit_d,
                        name="당기순이익",
                        marker_color="#E5E8EB",
                    ))
                    fig_cf.add_trace(go.Scatter(
                        x=years_x,
                        y=df_multi["norm_fcf"] / unit_d,
                        mode="lines+markers",
                        name="정상화 FCF (주주이익)",
                        line=dict(color="#3182F6", width=3),
                    ))
                    fig_cf.add_trace(go.Scatter(
                        x=years_x,
                        y=df_multi["fcf"] / unit_d,
                        mode="lines+markers",
                        name="회계상 FCF (OCF-CapEx)",
                        line=dict(color="#F59E0B", width=2, dash="dot"),
                    ))
                    fig_cf.update_layout(
                        title=dict(text=f"이익 vs 현금흐름 ({u_str}) · FCF 성장 {fcf_cagr_str}", font=dict(size=14, color="#191F28")),
                        plot_bgcolor="#FFFFFF",
                        paper_bgcolor="#FFFFFF",
                        barmode="group",
                        xaxis_title="결산연도",
                        yaxis_title=u_str,
                        height=320,
                        margin=dict(l=15, r=15, t=40, b=50),
                        legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5),
                    )
                    st.plotly_chart(fig_cf, use_container_width=True)

    with d_tab2:
        col_left, col_right = st.columns(2)
        with col_left:
            with st.container(border=True):
                st.markdown("#### 📐 ROCE 듀퐁 항등식 분해")
                roce_v = row_data["ROCE (%)"]
                ebit_m_v = row_data["EBIT Margin (%)"]
                turn_v = row_data["사용자본회전율 (배)"]

                st.markdown(
                    f"$$\\text{{ROCE ({roce_v:.1f}\\%)}} = \\text{{EBIT 마진 ({ebit_m_v:.1f}\\%)}} \\times \\text{{자본회전율 ({turn_v:.2f}배)}}$$"
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
                        {"항목": "현금및단기금융상품", "금액": format_currency_amount(cash_v, mkt_code)},
                        {"항목": "현금차감 사용자본 (표준 CE - 현금)", "금액": format_currency_amount(ce_net, mkt_code)},
                        {
                            "항목": "ROCE 비교 (표준 vs 현금차감)",
                            "금액": f"표준 {row_data['ROCE_표준 (%)']:.1f}%  vs  현금차감 {row_data['ROCE_현금차감 (%)']:.1f}%",
                        },
                    ]
                )
                st.dataframe(roce_table, use_container_width=True, hide_index=True)

        with col_right:
            with st.container(border=True):
                st.markdown("#### 🔍 현금전환율 (CCR) 브릿지")
                ccr_v = row_data["CCR (%)"]
                capex_v = row_data["capex"]
                da_v = row_data["da"]
                capex_da_ratio = row_data["CapEx/감가상각비 (%)"]
                chg_wc_v = row_data["chg_wc"]
                ocf_v = row_data["ocf"]
                fcf_v = row_data["fcf"]
                ebit_v = row_data["operating_income"]

                st.caption(f"진단 요약: **{row_data['CCR 상태 진단']}**")

                unit_div = 1e8 if mkt_code == "KR" else 1e6
                unit_label = "억 원" if mkt_code == "KR" else "$M"
                other_ocf_adj = ocf_v - (ebit_v + da_v + (chg_wc_v if pd.notna(chg_wc_v) else 0.0))

                fig = go.Figure(
                    go.Waterfall(
                        name="Cash Conversion Bridge",
                        orientation="v",
                        measure=["absolute", "relative", "relative", "relative", "total", "relative", "total"],
                        x=[
                            "영업이익",
                            "+ 감가상각비",
                            "± 운전자본",
                            "± 세금·기타",
                            "영업현금(OCF)",
                            "- CapEx",
                            "잉여현금(FCF)",
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
                        connector={"line": {"color": "#B0B8C1"}},
                    )
                )
                fig.update_layout(
                    title=dict(text=f"영업이익 ➔ 잉여현금흐름 전환 구조 ({unit_label})", font=dict(size=14, color="#191F28")),
                    plot_bgcolor="#FFFFFF",
                    paper_bgcolor="#FFFFFF",
                    height=330,
                    margin=dict(l=15, r=15, t=40, b=15),
                )
                st.plotly_chart(fig, use_container_width=True)

    with d_tab3:
        with st.container(border=True):
            st.markdown("#### 📝 기업 분석 메모 & 웹 링크 (구글 독스 URL 등)")
            st.caption("메모 안에 `https://docs.google.com/...` 등 웹 주소를 적어두면 상단 히어로 카드와 유니버스 보관함에 원클릭 바로가기 버튼이 자동으로 표시됩니다.")
            cur_memo = uni_info.get("memo", "")
            new_memo = st.text_area(
                "메모 및 분석 문서 URL",
                value=cur_memo,
                height=110,
                placeholder="예: 반도체 테스트 소켓 독점력 & 순현금 재무구조\n분석 리포트: https://docs.google.com/document/d/...",
                key=f"detail_memo_{symbol}",
                label_visibility="collapsed",
            )
            if st.button("💾 메모 저장 (유니버스 자동 보관)", key=f"btn_save_memo_{symbol}", type="primary"):
                de.upsert_universe_item(
                    symbol=symbol,
                    name=comp_name,
                    market=mkt_code,
                    memo=new_memo,
                )
                st.toast(f"✅ {comp_name} 메모 및 링크가 유니버스에 저장되었습니다!")
                st.rerun()


# =====================================================================
# 상세 페이지 활성 시 전체 화면을 상세 페이지로 즉시 라우팅
# =====================================================================
active_detail_sym = st.session_state.get("detail_view_symbol", None)
if active_detail_sym:
    render_company_detail_page(active_detail_sym)
    st.stop()


# =====================================================================
# 메인 화면 헤더 (토스 스타일 클린 헤더 + 우측 공식 가이드 팝오버 & 주가 갱신)
# =====================================================================
hdr_c1, hdr_c2, hdr_c3 = st.columns([6.0, 2.0, 2.0])
with hdr_c1:
    st.title("퀄리티 주식 스크리너")
    mkt_info_str = f"{market_choice} · {sub_market_choice}" if sub_market_choice and not sub_market_choice.startswith("전체") else market_choice
    st.caption(
        f"{mkt_info_str}  |  사용자본: {'현금차감' if deduct_cash_opt else '표준(총자산-유동부채)'}  |  요구수익률 r = {required_return_r:.1f}%"
    )
with hdr_c2:
    st.write("")
    render_formula_guide_popover()
with hdr_c3:
    st.write("")
    if st.button("🔄 현재가 · 시총 실시간 갱신", use_container_width=True):
        with st.spinner("최신 주가 및 시가총액 반영 중..."):
            cnt = de.refresh_prices_and_market_cap(selected_market)
            st.session_state["last_price_refresh"] = datetime.now().strftime("%H:%M:%S")
        st.toast(f"✅ {cnt}개 기업 주가·시가총액 갱신 완료!")
        st.rerun()

# 캐시에 결산 당시 시가총액(`hist_market_cap`)이 아직 없는 경우에만 심플한 원클릭 업데이트 알림 노출
sample_hist_str = ""
if "history_json" in metrics_df.columns and not metrics_df["history_json"].dropna().empty:
    sample_hist_str = str(metrics_df["history_json"].dropna().iloc[0])

if "hist_market_cap" not in sample_hist_str:
    with st.container(border=True):
        bc1, bc2 = st.columns([6.8, 2.2])
        with bc1:
            st.markdown(
                "**💡 과거 결산 당시 시가총액 기준 `4~5년 평균 FCF 수익률` 및 `FCF 성장률` 데이터 업데이트가 필요합니다.**  \n"
                "우측 버튼을 한 번만 누르면 모든 캐시 종목의 과거 결산일 당시 시총이 일괄 반영됩니다."
            )
        with bc2:
            if st.button("⚡ 5개년 당시 시총 일괄 업데이트", type="primary", use_container_width=True):
                prog = st.progress(0, text="결산 당시 시가총액 및 5개년 재무 데이터 업데이트 중...")

                def _bf_prog(d: int, t: int) -> None:
                    prog.progress(d / t, text=f"{d} / {t} 기업 업데이트 중...")

                cnt_bf = de.backfill_multiyear_history_for_cache(selected_market, max_workers=12, progress_callback=_bf_prog, force_all=True)
                prog.empty()
                st.toast(f"✅ {cnt_bf}개 기업 업데이트 완료!")
                st.rerun()


# =====================================================================
# 활성 필터 규칙 계산 (평가 기준은 스크리너 컨트롤 바의 세션 스테이트와 연동)
# =====================================================================
filter_basis_mode = st.session_state.get("filter_basis_mode", "최근 결산 기준")

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
                val_s = f"{actual_val:.1f}" if (pd.notna(actual_val) and actual_val > -900) else "N/A"
                f_list.append(f"{s_name}({val_s})")
        failed_count_per_row.append(len(f_list))
        if len(f_list) == 0:
            failed_labels_per_row.append("통과")
        elif len(f_list) == 1:
            failed_labels_per_row.append(f"1개 미달 · {f_list[0]}")
        else:
            failed_labels_per_row.append(f"{len(f_list)}개 미달 · " + ", ".join(f_list))

    annotated_df["미달_조건수"] = failed_count_per_row
    annotated_df["통과_상태_요약"] = failed_labels_per_row

# 토스 스타일 미니멀 퍼널 스텝 바
if funnel_stats:
    chips_html = []
    for idx, stat in enumerate(funnel_stats):
        st_name = "전체" if idx == 0 else (stat.get("label") or stat.get("stage", ""))
        cnt = stat["remaining"]
        is_last = idx == len(funnel_stats) - 1
        active_cls = "active" if is_last else ""
        chips_html.append(
            f"<div class='tds-funnel-pill {active_cls}'>"
            f"<span>{html.escape(st_name)}</span>"
            f"<span class='cnt'>{cnt}</span>"
            f"</div>"
        )
    funnel_bar_html = "<div class='tds-funnel-bar'>" + "<div class='tds-funnel-sep'>›</div>".join(chips_html) + "</div>"
    render_raw_html(funnel_bar_html)


# =====================================================================
# 2개 메인 탭 구성:
# - TAB 1: 종목 탐색 (통합 스크리너)
# - TAB 2: 나의 유니버스 보관함
# =====================================================================
universe_store = de.load_universe_store()
tab1_label = f"종목 탐색 ({len(passed_df)} / {len(annotated_df)})"
tab2_label = f"⭐ 나의 유니버스 ({len(universe_store)})"

if st.session_state.pop("clear_screener_selection", False):
    st.session_state["df_screener_table"] = {"selection": {"rows": [], "columns": []}}
if st.session_state.pop("clear_universe_selection", False):
    st.session_state["df_universe_table"] = {"selection": {"rows": [], "columns": []}}

tab_screener, tab_universe = st.tabs([tab1_label, tab2_label])


# ---------------------------------------------------------------------
# TAB 1: 종목 탐색 (토스 스타일 컴팩트 컨트롤 바 + 2열 반응형 화이트 카드 그리드)
# ---------------------------------------------------------------------
with tab_screener:
    df_all_pass = annotated_df[annotated_df["미달_조건수"] == 0].copy() if not annotated_df.empty else pd.DataFrame()
    df_near_miss = annotated_df[annotated_df["미달_조건수"] == 1].copy() if not annotated_df.empty else pd.DataFrame()
    df_full = annotated_df.copy()

    opt_all_pass = f"모든 조건 통과 ({len(df_all_pass)})"
    opt_near_miss = f"아깝게 1개 미달 ({len(df_near_miss)})"
    opt_full = f"전체 종목 ({len(df_full)})"

    group_options = [opt_all_pass, opt_near_miss, opt_full]
    group_df_map = {
        opt_all_pass: df_all_pass,
        opt_near_miss: df_near_miss,
        opt_full: df_full,
    }

    # 토스 스타일 상단 컨트롤 카드 (한 박스에 모든 뷰/정렬/기준 컨트롤 집약)
    with st.container(border=True):
        top_ctrl1, top_ctrl2 = st.columns([5.2, 4.8])
        with top_ctrl1:
            selected_group_opt = st.radio(
                "조회 그룹",
                options=group_options,
                index=0,
                horizontal=True,
                key="screener_group_opt",
            )
        with top_ctrl2:
            st.radio(
                "필터 평가 기준 (카드는 최근 수치와 다개년 평균을 항상 함께 표시)",
                options=[
                    "최근 결산 기준",
                    "5개년 평균 기준",
                    "최근 + 5개년 평균 동시 충족",
                ],
                index=0,
                horizontal=True,
                key="filter_basis_mode",
            )

        bot_ctrl1, bot_ctrl2, bot_ctrl3 = st.columns([3.2, 2.2, 3.6])
        with bot_ctrl1:
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
                label_visibility="collapsed",
            )
        with bot_ctrl2:
            default_asc = True if "역DCF" in sort_by_metric else False
            sort_asc = st.checkbox("낮은 순 정렬", value=default_asc)
        with bot_ctrl3:
            view_mode = st.radio(
                "표시 형태",
                options=["카드 뷰 (2열 그리드)", "테이블 뷰"],
                index=0,
                horizontal=True,
                key="screener_view_mode",
                label_visibility="collapsed",
            )

    target_df = group_df_map.get(selected_group_opt, pd.DataFrame())

    if target_df.empty:
        st.info("선택한 그룹에 해당하는 기업이 없습니다. 상단에서 `아깝게 1개 미달` 또는 `전체 종목`을 눌러보세요.")
    else:
        disp_df = target_df.sort_values(
            by=["미달_조건수", sort_by_metric],
            ascending=[True, sort_asc],
        ).reset_index(drop=True)

        if view_mode.startswith("카드"):
            # PC에서는 2열 바둑판 그리드, 모바일에서는 자동 1열 스택
            grid_cols = st.columns(2)
            for c_idx, row in disp_df.iterrows():
                col_container = grid_cols[c_idx % 2]
                with col_container:
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
                        badge_html = f"<span class='tds-badge green'>{html.escape(status_summary)}</span>"
                    elif fail_cnt == 1:
                        badge_html = f"<span class='tds-badge amber'>{html.escape(status_summary)}</span>"
                    else:
                        badge_html = f"<span class='tds-badge red'>{html.escape(status_summary)}</span>"

                    in_uni = sym in universe_store
                    uni_star = "<span class='tds-badge blue' style='margin-left:4px;'>⭐ 보관중</span>" if in_uni else ""
                    box_cls = "tds-card in-universe" if in_uni else "tds-card"

                    # 개별 지표 미달 여부 하이라이트 클래스
                    gpm_miss = "missed" if (f"통과_{gpm_col_target}" in row and not bool(row[f"통과_{gpm_col_target}"])) else ""
                    roce_miss = "missed" if (f"통과_{roce_col_target}" in row and not bool(row[f"통과_{roce_col_target}"])) else ""
                    ccr_miss = "missed" if (f"통과_{ccr_col_target}" in row and not bool(row[f"통과_{ccr_col_target}"])) else ""
                    icr_miss = "missed" if ("통과_이자보상배율 (배)" in row and not bool(row["통과_이자보상배율 (배)"])) else ""

                    g_text = f"연 {g_val:+.1f}%" if pd.notna(g_val) else "N/A"
                    g_5y_text = f"과거 {yr_cnt}년 당시시총 평균 {g_5y:+.1f}%" if pd.notna(g_5y) else ""
                    fcf_text = f"{fcf_y:.1f}%" if pd.notna(fcf_y) else "N/A"
                    fcf_5y_text = f"과거 {yr_cnt}년 평균 {fcf_y_5y:.1f}%" if pd.notna(fcf_y_5y) else ""

                    gpm_str = f"{gpm:.1f}%" if pd.notna(gpm) else "N/A"
                    gpm_5y_str = f"{yr_cnt}년 평균 {gpm_5y:.1f}%" if pd.notna(gpm_5y) else "-"
                    roce_str = f"{roce:.1f}%" if pd.notna(roce) else "N/A"
                    roce_5y_str = f"{yr_cnt}년 평균 {roce_5y:.1f}%" if pd.notna(roce_5y) else "-"
                    ccr_str = f"{ccr:.1f}%" if pd.notna(ccr) else "N/A"
                    ccr_5y_str = f"{yr_cnt}년 평균 {ccr_5y:.1f}%" if pd.notna(ccr_5y) else "-"
                    opm_5y_str = f"OPM {opm:.1f}% ({yr_cnt}년 {opm_5y:.1f}%)" if (pd.notna(opm) and pd.notna(opm_5y)) else ""

                    diag_html = (
                        f"<div class='tds-ccr-caption'>현금흐름 진단 · {html.escape(str(ccr_diag))}</div>"
                        if (ccr_diag and ccr_diag != "-")
                        else ""
                    )

                    memo_preview_html = ""
                    if in_uni and universe_store[sym].get("memo"):
                        memo_preview_html = render_memo_with_links_html(universe_store[sym]["memo"])

                    card_html = f"""
                    <div class="{box_cls}">
                        <div class="tds-card-top">
                            <div>
                                <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                                    <span class="tds-comp-name">{html.escape(name)}</span>
                                    {badge_html}
                                    {uni_star}
                                </div>
                                <div class="tds-comp-sub">{html.escape(sym)} · {html.escape(str(mkt_d))} · 결산 {html.escape(str(fdate))}</div>
                            </div>
                            <div>
                                <div class="tds-mcap-text">{html.escape(str(mcap))}</div>
                            </div>
                        </div>
                        <div class="tds-val-banner blue-tint">
                            <div>
                                <div class="tds-val-lbl">영구 역DCF 기대성장률 (r={required_return_r:.0f}%)</div>
                                <div class="tds-val-main accent">{g_text}</div>
                                <div class="tds-val-sub">{g_5y_text}</div>
                            </div>
                            <div style="text-align:right;">
                                <div class="tds-val-lbl">정상화 FCF 수익률</div>
                                <div class="tds-val-main" style="font-size:1.12rem;">{fcf_text}</div>
                                <div class="tds-val-sub">{fcf_5y_text}</div>
                            </div>
                        </div>
                        <div class="tds-metric-grid">
                            <div class="tds-metric-cell {gpm_miss}">
                                <div class="tds-m-lbl">매출총이익률 GPM</div>
                                <div class="tds-m-val">{gpm_str}</div>
                                <div class="tds-m-avg">{gpm_5y_str}</div>
                            </div>
                            <div class="tds-metric-cell {roce_miss}">
                                <div class="tds-m-lbl">자본이익률 ROCE</div>
                                <div class="tds-m-val">{roce_str}</div>
                                <div class="tds-m-avg">{roce_5y_str}</div>
                            </div>
                            <div class="tds-metric-cell {ccr_miss}">
                                <div class="tds-m-lbl">현금전환율 CCR</div>
                                <div class="tds-m-val">{ccr_str}</div>
                                <div class="tds-m-avg">{ccr_5y_str}</div>
                            </div>
                            <div class="tds-metric-cell {icr_miss}">
                                <div class="tds-m-lbl">이자보상 · OPM</div>
                                <div class="tds-m-val" style="font-size:0.92rem;">{html.escape(str(int_cov))}</div>
                                <div class="tds-m-avg">{html.escape(opm_5y_str)}</div>
                            </div>
                        </div>
                        {diag_html}
                        {memo_preview_html}
                    </div>
                    """
                    render_raw_html(card_html)

                    btn_c1, btn_c2 = st.columns([3.2, 1.3])
                    with btn_c1:
                        if st.button(f"{name} 상세 분석 보기", key=f"btn_detail_{sym}_{c_idx}", type="secondary", use_container_width=True):
                            open_company_detail(sym, return_tab="screener")
                            st.rerun()
                    with btn_c2:
                        if in_uni:
                            if st.button("⭐ 해제", key=f"btn_uni_{sym}_{c_idx}", type="secondary", use_container_width=True):
                                de.remove_universe_item(sym)
                                st.toast(f"🗑️ {name} 유니버스 해제")
                                st.rerun()
                        else:
                            if st.button("⭐ 보관", key=f"btn_uni_{sym}_{c_idx}", type="secondary", use_container_width=True):
                                de.upsert_universe_item(symbol=sym, name=name, market=mkt_code)
                                st.toast(f"⭐ {name} 유니버스 보관 완료!")
                                st.rerun()
        else:
            with st.container(border=True):
                st.caption("👉 **기업 행을 클릭**하면 즉시 해당 기업의 상세 페이지로 이동합니다.")
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
                        "통과_상태_요약": "상태",
                        "정상화 FCF 수익률 (%)": "FCF수익률(최근)",
                        "정상화 FCF 수익률_5Y (%)": "FCF수익률(당시시총 평균)",
                        "역DCF 기대성장률 (%)": f"역DCF g (r={required_return_r:.0f}%)",
                        "GPM (%)": "GPM(최근)",
                        "GPM_5Y (%)": "GPM(평균)",
                        "ROCE (%)": "ROCE(최근)",
                        "ROCE_5Y (%)": "ROCE(평균)",
                        "CCR (%)": "CCR(최근)",
                        "CCR_5Y (%)": "CCR(평균)",
                        "OPM (%)": "OPM(최근)",
                        "OPM_5Y (%)": "OPM(평균)",
                        "이자보상배율_표시": "이자보상배율",
                        "CCR 상태 진단": "현금흐름 진단",
                        "fiscal_date": "결산일",
                    }
                )
                g_col_name = f"역DCF g (r={required_return_r:.0f}%)"

                event_screener = st.dataframe(
                    view_df.style.format(
                        {
                            "FCF수익률(최근)": "{:.2f}%",
                            "FCF수익률(당시시총 평균)": "{:.2f}%",
                            g_col_name: "{:+.2f}%",
                            "GPM(최근)": "{:.1f}%",
                            "GPM(평균)": "{:.1f}%",
                            "ROCE(최근)": "{:.1f}%",
                            "ROCE(평균)": "{:.1f}%",
                            "CCR(최근)": "{:.1f}%",
                            "CCR(평균)": "{:.1f}%",
                            "OPM(최근)": "{:.1f}%",
                            "OPM(평균)": "{:.1f}%",
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
                            open_company_detail(disp_df.iloc[sel_idx]["symbol"], return_tab="screener")
                            st.rerun()

        st.write("")
        export_cols = [
            "symbol", "name", "market_display", "시가총액_표시",
            "통과_조건수", "통과_상태_요약",
            "정상화 FCF 수익률 (%)", "정상화 FCF 수익률_5Y (%)", "역DCF 기대성장률 (%)",
            "GPM (%)", "GPM_5Y (%)", "ROCE (%)", "ROCE_5Y (%)",
            "CCR (%)", "CCR_5Y (%)", "OPM (%)", "OPM_5Y (%)",
            "이자보상배율_표시", "CCR 상태 진단", "fiscal_date",
        ]
        export_df = disp_df[export_cols]
        dl_col1, dl_col2, _ = st.columns([2.2, 2.2, 5.6])
        csv_bytes = export_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        dl_col1.download_button(
            label="📥 CSV 다운로드",
            data=csv_bytes,
            file_name=f"quality_screener_{selected_market}.csv",
            mime="text/csv",
            use_container_width=True,
        )
        excel_bytes = to_excel_bytes(export_df)
        dl_col2.download_button(
            label="📥 Excel (.xlsx) 다운로드",
            data=excel_bytes,
            file_name=f"quality_screener_{selected_market}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )


# ---------------------------------------------------------------------
# TAB 2: ⭐ 나의 유니버스 보관함 (토스 스타일 2열 카드 & 기업별 N년 정밀 역DCF)
# ---------------------------------------------------------------------
with tab_universe:
    with st.container(border=True):
        uc1, uc2, uc3 = st.columns([4.5, 2.0, 2.5])
        with uc1:
            avail_to_add = [
                f"{r['name']} ({r['symbol']}) · {r.get('시가총액_표시', '')}"
                for _, r in all_metrics_df.iterrows()
                if r["symbol"] not in universe_store
            ]
            sym_add_map = {
                f"{r['name']} ({r['symbol']}) · {r.get('시가총액_표시', '')}": (r["symbol"], r["name"], r["market"])
                for _, r in all_metrics_df.iterrows()
                if r["symbol"] not in universe_store
            }
            sel_to_add = st.multiselect(
                "유니버스에 새 종목 추가",
                options=avail_to_add,
                placeholder="보관함에 추가할 기업명 또는 티커 검색...",
                label_visibility="collapsed",
            )
        with uc2:
            if st.button("➕ 선택 기업 보관함에 추가", type="primary", use_container_width=True) and sel_to_add:
                for item_lbl in sel_to_add:
                    s_code, s_name, s_mkt = sym_add_map[item_lbl]
                    de.upsert_universe_item(symbol=s_code, name=s_name, market=s_mkt)
                st.toast(f"⭐ {len(sel_to_add)}개 기업을 유니버스에 추가했습니다!")
                st.rerun()
        with uc3:
            uni_view_mode = st.radio(
                "유니버스 보기 모드",
                options=["카드 뷰 (2열 그리드)", "테이블 뷰"],
                index=0,
                horizontal=True,
                key="uni_view_mode",
                label_visibility="collapsed",
            )

    if not universe_store:
        st.info("아직 유니버스 보관함에 담긴 기업이 없습니다. 종목 탐색 탭에서 `⭐ 보관`을 누르거나 위 검색창에서 종목을 추가해 보세요.")
    else:
        uni_symbols = list(universe_store.keys())
        uni_df = all_metrics_df[all_metrics_df["symbol"].isin(uni_symbols)].copy().reset_index(drop=True)

        if not uni_df.empty:
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

            if uni_view_mode.startswith("카드"):
                u_cols = st.columns(2)
                for u_idx, row in uni_df.iterrows():
                    with u_cols[u_idx % 2]:
                        sym = row["symbol"]
                        name = row["name"]
                        mkt_code = str(row["market"]).upper()
                        mkt_d = row.get("market_display", row["market"])
                        mcap_str = row.get("시가총액_표시", "N/A")
                        yr_cnt = int(row.get("평균_연도수", 1))
                        u_item = universe_store.get(sym, {})

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
                        fcf_cagr_s = str(row.get("FCF_CAGR_표시", "N/A"))

                        def _fp(v: float) -> str:
                            return f"{v:.1f}%" if pd.notna(v) else "N/A"

                        g_inf_s = f"{g_inf:+.1f}%" if pd.notna(g_inf) else "N/A"
                        g_imp_n_s = f"연 {g_imp_n:+.1f}%" if pd.notna(g_imp_n) else "FCF≤0"
                        upside_s = f"{upside_v:+.1f}%" if pd.notna(upside_v) else "N/A"
                        upside_badge_cls = "green" if (pd.notna(upside_v) and upside_v >= 0) else "red"
                        cur_memo_str = u_item.get("memo", "")
                        memo_block_html = render_memo_with_links_html(cur_memo_str)

                        u_card_html = f"""
                        <div class="tds-card in-universe">
                            <div class="tds-card-top">
                                <div>
                                    <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                                        <span class="tds-comp-name">⭐ {html.escape(name)}</span>
                                        <span class="tds-badge blue">성장기간 {n_yr_cur}년</span>
                                        <span class="tds-badge {upside_badge_cls}">적정시총 대비 {upside_s}</span>
                                    </div>
                                    <div class="tds-comp-sub">{html.escape(sym)} · {html.escape(str(mkt_d))} · 과거 FCF 성장 {html.escape(fcf_cagr_s)}</div>
                                </div>
                                <div>
                                    <div class="tds-mcap-text">{html.escape(str(mcap_str))}</div>
                                </div>
                            </div>
                            <div class="tds-val-banner blue-tint">
                                <div>
                                    <div class="tds-val-lbl">{n_yr_cur}년 한정 정밀 역DCF 요구성장률 (이후 {g2_cur:.1f}%)</div>
                                    <div class="tds-val-main accent">{g_imp_n_s} <span style="font-size:0.78rem; font-weight:600; color:#6B7684;">(영구 {g_inf_s})</span></div>
                                    <div class="tds-val-sub">현재 FCF수익률 {_fp(fcf_y_now)} · 당시시총 평균 {_fp(fcf_y_5y)}</div>
                                </div>
                                <div style="text-align:right;">
                                    <div class="tds-val-lbl">내 예상(연 {g1_cur:+.1f}%) 적정 시총</div>
                                    <div class="tds-val-main" style="font-size:1.08rem; color:#00A84D;">{fair_mcap_s}</div>
                                    <div class="tds-val-sub">괴리율 {upside_s}</div>
                                </div>
                            </div>
                            <div class="tds-metric-grid" style="grid-template-columns: repeat(3, 1fr);">
                                <div class="tds-metric-cell">
                                    <div class="tds-m-lbl">매출총이익률 GPM</div>
                                    <div class="tds-m-val">{_fp(gpm_now)}</div>
                                    <div class="tds-m-avg">{yr_cnt}년 평균 {_fp(gpm_5y)}</div>
                                </div>
                                <div class="tds-metric-cell">
                                    <div class="tds-m-lbl">자본이익률 ROCE</div>
                                    <div class="tds-m-val">{_fp(roce_now)}</div>
                                    <div class="tds-m-avg">{yr_cnt}년 평균 {_fp(roce_5y)}</div>
                                </div>
                                <div class="tds-metric-cell">
                                    <div class="tds-m-lbl">현금전환율 CCR</div>
                                    <div class="tds-m-val">{_fp(ccr_now)}</div>
                                    <div class="tds-m-avg">{yr_cnt}년 평균 {_fp(ccr_5y)}</div>
                                </div>
                            </div>
                            {memo_block_html}
                        </div>
                        """
                        render_raw_html(u_card_html)

                        ub1, ub2, ub3 = st.columns([2.4, 1.4, 1.0])
                        with ub1:
                            if st.button(f"{name} 상세 페이지", key=f"uni_open_detail_{sym}", type="primary", use_container_width=True):
                                open_company_detail(sym, return_tab="universe")
                                st.rerun()
                        with ub2:
                            with st.popover("⚙️ 가정 · 메모 수정", use_container_width=True):
                                st.markdown(f"**{name} 성장가정 & 메모**")
                                edit_n = st.number_input("성장 지속기간 N (년)", min_value=1, max_value=40, value=n_yr_cur, step=1, key=f"u_n_{sym}")
                                edit_g1 = st.number_input("성장기간 예상 성장률 g1 (%)", min_value=-30.0, max_value=100.0, value=g1_cur, step=1.0, key=f"u_g1_{sym}")
                                edit_g2 = st.number_input("N년 이후 영구성장률 g2 (%)", min_value=-10.0, max_value=float(required_return_r - 0.5), value=g2_cur, step=0.5, key=f"u_g2_{sym}")
                                edit_memo = st.text_area("메모 & 구글 독스 URL", value=cur_memo_str, height=85, key=f"u_memo_{sym}")
                                if st.button("💾 저장하기", key=f"u_save_{sym}", type="primary", use_container_width=True):
                                    de.upsert_universe_item(
                                        symbol=sym,
                                        name=name,
                                        market=mkt_code,
                                        memo=edit_memo,
                                        growth_years=int(edit_n),
                                        growth_rate_est=float(edit_g1),
                                        terminal_growth_rate=float(edit_g2),
                                    )
                                    st.toast(f"✅ {name} 저장 완료!")
                                    st.rerun()
                        with ub3:
                            if st.button("제거", key=f"uni_del_{sym}", type="secondary", use_container_width=True):
                                de.remove_universe_item(sym)
                                st.toast(f"🗑️ {name} 제거 완료")
                                st.rerun()
            else:
                with st.container(border=True):
                    st.caption("👉 **기업 행을 클릭**하면 해당 기업의 상세 페이지로 즉시 이동합니다.")
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
                            "N년_정밀역DCF_요구성장률(%)": "N년 정밀 역DCF 요구성장률",
                            "예상성장률_g1(%)": "내 예상성장률(g1)",
                            "적정시가총액": "적정 시가총액",
                            "상승여력(%)": "상승여력(%)",
                            "GPM (%)": "GPM(최근)",
                            "GPM_5Y (%)": "GPM(평균)",
                            "ROCE (%)": "ROCE(최근)",
                            "ROCE_5Y (%)": "ROCE(평균)",
                            "CCR (%)": "CCR(최근)",
                            "CCR_5Y (%)": "CCR(평균)",
                            "메모": "메모 & 링크",
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
                                "N년 정밀 역DCF 요구성장률": "{:+.2f}%",
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
