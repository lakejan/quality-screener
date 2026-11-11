# -*- coding: utf-8 -*-
"""
한·미 주식 퀄리티 스크리너 데이터 수집 및 지표 산출 엔진
- 한국(KR) 및 미국(US) 상장사 유니버스 조회 (yfinance EquityQuery + KRX 한글 종목명 매핑)
- 재무제표(손익계산서, 재무상태표, 현금흐름표) 병렬 수집 및 로컬 Parquet/CSV 캐싱
- GPM, OPM, ROCE(EBIT Margin × 사용자본회전율), CCR(현금전환율 및 원인 진단), 이자보상배율 계산
"""

from __future__ import annotations

import io
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import yfinance as yf

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

KRX_NAME_CACHE_PATH = DATA_DIR / "krx_names.csv"
RAW_CACHE_KR_PATH = DATA_DIR / "raw_financials_KR.parquet"
RAW_CACHE_US_PATH = DATA_DIR / "raw_financials_US.parquet"


# =====================================================================
# 1. 한국 상장사 한글 종목명 매핑 (KIND KRX)
# =====================================================================
def load_krx_name_map(force_refresh: bool = False) -> Dict[str, Dict[str, str]]:
    """
    KRX 상장법인 목록에서 {6자리 종목코드: {'name': 한글명, 'sector': 업종}} 딕셔너리를 반환합니다.
    """
    if KRX_NAME_CACHE_PATH.exists() and not force_refresh:
        try:
            df = pd.read_csv(KRX_NAME_CACHE_PATH, dtype=str, encoding="utf-8-sig")
            return {
                row["code"]: {"name": row["name"], "sector": str(row.get("sector", ""))}
                for _, row in df.iterrows()
            }
        except Exception:
            pass

    try:
        url = "http://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
        resp = requests.get(url, timeout=10)
        html_text = resp.content.decode("euc-kr", errors="ignore")
        dfs = pd.read_html(io.StringIO(html_text))
        if dfs:
            raw_df = dfs[0]
            # 컬럼명 자동 탐색 (회사명, 종목코드, 업종)
            cols = list(raw_df.columns)
            name_col = next((c for c in cols if "회사명" in str(c)), cols[0])
            code_col = next((c for c in cols if "종목코드" in str(c)), cols[2] if len(cols) > 2 else cols[1])
            sector_col = next((c for c in cols if "업종" in str(c)), cols[3] if len(cols) > 3 else None)

            out_rows = []
            for _, r in raw_df.iterrows():
                code = str(r[code_col]).strip().zfill(6)
                name = str(r[name_col]).strip()
                sector = str(r[sector_col]).strip() if sector_col else ""
                out_rows.append({"code": code, "name": name, "sector": sector})

            clean_df = pd.DataFrame(out_rows).drop_duplicates(subset=["code"])
            clean_df.to_csv(KRX_NAME_CACHE_PATH, index=False, encoding="utf-8-sig")
            return {
                row["code"]: {"name": row["name"], "sector": row["sector"]}
                for _, row in clean_df.iterrows()
            }
    except Exception:
        pass

    return {}


# =====================================================================
# 2. 서버사이드 1차 유니버스 추출 (yfinance EquityQuery)
# =====================================================================
def fetch_universe_symbols(
    market: str = "KR",
    min_market_cap: float = 300_000_000_000,
    max_count: int = 150,
    only_profitable: bool = True,
    pre_filter_gpm: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    yfinance EquityQuery를 이용해 한국(KR) 또는 미국(US) 시가총액 상위 종목 리스트를 빠르게 가져옵니다.
    - market: 'KR' 또는 'US'
    - min_market_cap: KR은 원화(예: 3,000억 = 3e11), US는 달러(예: 20억불 = 2e9)
    - max_count: 가져올 최대 기업 수
    """
    region = "kr" if market.upper() == "KR" else "us"
    operands = [
        yf.EquityQuery("eq", ["region", region]),
        yf.EquityQuery("gt", ["intradaymarketcap", float(min_market_cap)]),
    ]
    if market.upper() == "US":
        # OTC 장외 중복 티커(PNK 등) 제외, 정규 거래소(NYSE, NASDAQ)만 조회
        operands.append(
            yf.EquityQuery(
                "or",
                [
                    yf.EquityQuery("eq", ["exchange", "NMS"]),
                    yf.EquityQuery("eq", ["exchange", "NYQ"]),
                    yf.EquityQuery("eq", ["exchange", "NGM"]),
                ],
            )
        )
    if only_profitable:
        operands.append(yf.EquityQuery("gt", ["operatingincome.lasttwelvemonths", 0]))
    if pre_filter_gpm is not None and pre_filter_gpm > 0:
        operands.append(
            yf.EquityQuery("gt", ["grossprofitmargin.lasttwelvemonths", float(pre_filter_gpm)])
        )

    query = yf.EquityQuery("and", operands)
    krx_map = load_krx_name_map() if market.upper() == "KR" else {}

    collected: List[Dict[str, Any]] = []
    seen_symbols = set()
    offset = 0
    page_size = min(250, max(50, max_count))

    while len(collected) < max_count and offset < 1000:
        try:
            res = yf.screen(
                query,
                offset=offset,
                size=page_size,
                sortField="intradaymarketcap",
                sortAsc=False,
            )
        except Exception:
            break

        quotes = res.get("quotes", [])
        if not quotes:
            break

        for q in quotes:
            sym = q.get("symbol", "")
            if not sym or sym in seen_symbols:
                continue

            # 한국 시장인 경우 우선주(종목코드 6자리가 숫자가 아니거나 끝자리가 0이 아닌 경우) 제외
            if market.upper() == "KR":
                base_code = sym.split(".")[0]
                if len(base_code) == 6 and base_code.isdigit():
                    if not base_code.endswith("0"):
                        continue
                else:
                    continue
                kr_info = krx_map.get(base_code, {})
                display_name = kr_info.get("name") or q.get("shortName") or q.get("longName") or sym
                sector_name = kr_info.get("sector") or ""
            else:
                # 미국 시장: 같은 기업의 중복 티커(GOOGL/GOOG 등)는 모두 허용하되 ADR/특수티커 정제
                display_name = q.get("shortName") or q.get("longName") or sym
                sector_name = ""

            seen_symbols.add(sym)
            if market.upper() == "KR":
                exch_code = "KOSDAQ" if sym.endswith(".KQ") else ("KONEX" if sym.endswith(".KN") else "KOSPI")
            else:
                exch_code = str(q.get("exchange", ""))

            collected.append(
                {
                    "symbol": sym,
                    "name": display_name,
                    "market": market.upper(),
                    "exchange": exch_code,
                    "sector": sector_name,
                    "market_cap": q.get("marketCap"),
                    "price": q.get("regularMarketPrice"),
                    "currency": q.get("financialCurrency") or q.get("currency") or ("KRW" if market.upper() == "KR" else "USD"),
                }
            )
            if len(collected) >= max_count:
                break

        total_avail = res.get("total", 0)
        offset += len(quotes)
        if offset >= total_avail:
            break

    return collected


# =====================================================================
# 3. 개별 종목 재무제표 원천 데이터 추출
# =====================================================================
def _get_first_valid(series: pd.Series, keys: List[str]) -> float:
    """Series에서 후보 키 목록 중 처음으로 존재하는 유효 숫자를 반환합니다."""
    if series is None or series.empty:
        return np.nan
    for k in keys:
        if k in series.index:
            val = series[k]
            if pd.notna(val):
                try:
                    return float(val)
                except (ValueError, TypeError):
                    continue
    return np.nan


def fetch_single_stock_raw(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    단일 종목의 최신 연간 재무제표(IS, BS, CF)에서 원천 계정과목을 추출합니다.
    """
    sym = item["symbol"]
    try:
        tk = yf.Ticker(sym)
        is_df = tk.income_stmt
        bs_df = tk.balance_sheet
        cf_df = tk.cashflow

        if is_df is None or is_df.empty or bs_df is None or bs_df.empty or cf_df is None or cf_df.empty:
            return None

        # 가장 최신 결산연도 컬럼 선택 (매출액이 NaN이 아닌 첫 번째 컬럼)
        is_col = is_df.iloc[:, 0]
        for col_idx in range(min(3, is_df.shape[1])):
            cand = is_df.iloc[:, col_idx]
            rev_test = _get_first_valid(cand, ["Total Revenue", "Operating Revenue"])
            if pd.notna(rev_test) and rev_test > 0:
                is_col = cand
                break

        fiscal_date = str(is_col.name)[:10] if hasattr(is_col, "name") else ""

        # 동일 결산일 또는 가장 최신 BS, CF 컬럼 매칭
        bs_col = bs_df[is_col.name] if is_col.name in bs_df.columns else bs_df.iloc[:, 0]
        cf_col = cf_df[is_col.name] if is_col.name in cf_df.columns else cf_df.iloc[:, 0]

        # 1) 손익계산서 (Income Statement)
        revenue = _get_first_valid(is_col, ["Total Revenue", "Operating Revenue"])
        gross_profit = _get_first_valid(is_col, ["Gross Profit"])
        cost_of_revenue = _get_first_valid(is_col, ["Cost Of Revenue", "Reconciled Cost Of Revenue"])
        if pd.isna(gross_profit) and pd.notna(revenue) and pd.notna(cost_of_revenue):
            gross_profit = revenue - cost_of_revenue

        operating_income = _get_first_valid(
            is_col, ["Operating Income", "Total Operating Income As Reported", "EBIT"]
        )
        ebit_reported = _get_first_valid(is_col, ["EBIT", "Operating Income"])
        net_income = _get_first_valid(
            is_col,
            [
                "Net Income",
                "Net Income Common Stockholders",
                "Net Income From Continuing Operation Net Minority Interest",
            ],
        )
        interest_expense = _get_first_valid(
            is_col, ["Interest Expense", "Interest Expense Non Operating"]
        )
        if pd.notna(interest_expense):
            interest_expense = abs(interest_expense)
        tax_provision = _get_first_valid(is_col, ["Tax Provision"])

        # 2) 재무상태표 (Balance Sheet)
        total_assets = _get_first_valid(bs_col, ["Total Assets"])
        current_liabilities = _get_first_valid(bs_col, ["Current Liabilities", "Total Current Liabilities"])
        cash_and_sti = _get_first_valid(
            bs_col,
            [
                "Cash Cash Equivalents And Short Term Investments",
                "Cash And Cash Equivalents",
                "Cash Financial",
            ],
        )
        if pd.isna(cash_and_sti):
            cash_and_sti = 0.0

        total_equity = _get_first_valid(
            bs_col, ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"]
        )
        total_debt = _get_first_valid(bs_col, ["Total Debt"])

        # 3) 현금흐름표 (Cash Flow Statement)
        ocf = _get_first_valid(
            cf_col, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"]
        )
        raw_capex = _get_first_valid(
            cf_col, ["Capital Expenditure", "Purchase Of PPE", "Net PPE Purchase And Sale"]
        )
        # CapEx를 양수(지출액 크기)로 정규화 (일반적으로 현금흐름표에 음수로 표기됨)
        if pd.notna(raw_capex):
            capex = abs(raw_capex) if raw_capex < 0 else raw_capex
        else:
            # Free Cash Flow가 있으면 역산
            fcf_reported = _get_first_valid(cf_col, ["Free Cash Flow"])
            if pd.notna(ocf) and pd.notna(fcf_reported):
                capex = max(0.0, ocf - fcf_reported)
            else:
                capex = 0.0

        da = _get_first_valid(
            cf_col,
            [
                "Depreciation And Amortization",
                "Depreciation Amortization Depletion",
                "Depreciation",
            ],
        )
        if pd.isna(da):
            da = _get_first_valid(is_col, ["Reconciled Depreciation"])
        if pd.isna(da):
            da = 0.0

        chg_wc = _get_first_valid(cf_col, ["Change In Working Capital"])
        chg_payables = _get_first_valid(
            cf_col,
            [
                "Change In Payables And Accrued Expense",
                "Change In Payable",
                "Change In Account Payable",
            ],
        )
        chg_receivables = _get_first_valid(
            cf_col, ["Change In Receivables", "Changes In Account Receivables"]
        )
        chg_inventory = _get_first_valid(cf_col, ["Change In Inventory"])
        chg_deferred = _get_first_valid(
            cf_col, ["Change In Other Current Liabilities", "Change In Other Working Capital"]
        )

        exch_val = item.get("exchange")
        if not exch_val:
            if str(item.get("market")).upper() == "KR" or sym.endswith(".KS") or sym.endswith(".KQ"):
                exch_val = "KOSDAQ" if sym.endswith(".KQ") else "KOSPI"
            else:
                try:
                    exch_val = str(tk.fast_info.get("exchange", ""))
                except Exception:
                    exch_val = ""

        return {
            "symbol": sym,
            "name": item.get("name", sym),
            "market": item.get("market", "KR"),
            "exchange": exch_val,
            "sector": item.get("sector", ""),
            "currency": item.get("currency", "KRW"),
            "market_cap": item.get("market_cap", np.nan),
            "price": item.get("price", np.nan),
            "fiscal_date": fiscal_date,
            "revenue": revenue,
            "gross_profit": gross_profit,
            "operating_income": operating_income,
            "ebit_reported": ebit_reported,
            "net_income": net_income,
            "interest_expense": interest_expense,
            "tax_provision": tax_provision,
            "total_assets": total_assets,
            "current_liabilities": current_liabilities,
            "cash_and_sti": cash_and_sti,
            "total_equity": total_equity,
            "total_debt": total_debt,
            "ocf": ocf,
            "capex": capex,
            "da": da,
            "chg_wc": chg_wc,
            "chg_payables": chg_payables,
            "chg_receivables": chg_receivables,
            "chg_inventory": chg_inventory,
            "chg_deferred": chg_deferred,
        }
    except Exception:
        return None


def fetch_batch_raw_financials(
    items: List[Dict[str, Any]],
    max_workers: int = 10,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> pd.DataFrame:
    """
    멀티스레딩으로 여러 기업의 원천 재무 데이터를 병렬 수집하여 DataFrame으로 반환합니다.
    """
    results: List[Dict[str, Any]] = []
    total = len(items)
    if total == 0:
        return pd.DataFrame()

    completed_count = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_item = {executor.submit(fetch_single_stock_raw, item): item for item in items}
        for future in as_completed(future_to_item):
            completed_count += 1
            if progress_callback:
                progress_callback(completed_count, total)
            res = future.result()
            if res is not None:
                results.append(res)

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    # 시가총액 내림차순 정렬
    if "market_cap" in df.columns:
        df = df.sort_values(by="market_cap", ascending=False).reset_index(drop=True)
    return df


def fetch_stock_multiyear_data(
    symbol: str,
    market: str = "KR",
    ccr_denominator: str = "net_income",
    deduct_cash_from_ce: bool = False,
    max_years: int = 4,
) -> pd.DataFrame:
    """
    개별 기업의 최근 N개년(기본 3~4개년) 연간 재무제표를 바탕으로
    연도별 손익, 자본, 현금흐름 및 퀄리티 지표(GPM, OPM, ROCE, CCR 등) 추이를 계산합니다.
    """
    try:
        tk = yf.Ticker(symbol)
        is_df = tk.income_stmt
        bs_df = tk.balance_sheet
        cf_df = tk.cashflow

        if is_df is None or is_df.empty or bs_df is None or bs_df.empty or cf_df is None or cf_df.empty:
            return pd.DataFrame()

        # 유효한 결산일 컬럼들 탐색 (최근 max_years개년)
        valid_cols = []
        for c in is_df.columns:
            rev_chk = _get_first_valid(is_df[c], ["Total Revenue", "Operating Revenue"])
            if pd.notna(rev_chk) and rev_chk > 0:
                valid_cols.append(c)
            if len(valid_cols) >= max_years:
                break

        if not valid_cols:
            return pd.DataFrame()

        records = []
        for col_name in valid_cols:
            is_col = is_df[col_name]
            bs_col = bs_df[col_name] if col_name in bs_df.columns else (bs_df.iloc[:, 0] if not bs_df.empty else pd.Series(dtype=float))
            cf_col = cf_df[col_name] if col_name in cf_df.columns else (cf_df.iloc[:, 0] if not cf_df.empty else pd.Series(dtype=float))

            fiscal_date = str(col_name)[:10]

            # 1. 손익
            revenue = _get_first_valid(is_col, ["Total Revenue", "Operating Revenue"])
            gross_profit = _get_first_valid(is_col, ["Gross Profit"])
            cost_of_revenue = _get_first_valid(is_col, ["Cost Of Revenue", "Reconciled Cost Of Revenue"])
            if pd.isna(gross_profit) and pd.notna(revenue) and pd.notna(cost_of_revenue):
                gross_profit = revenue - cost_of_revenue

            operating_income = _get_first_valid(is_col, ["Operating Income", "Total Operating Income As Reported", "EBIT"])
            ebit_reported = _get_first_valid(is_col, ["EBIT", "Operating Income"])
            ebit = operating_income if pd.notna(operating_income) else ebit_reported
            net_income = _get_first_valid(is_col, ["Net Income", "Net Income Common Stockholders", "Net Income Continuous Operations"])
            interest_expense = _get_first_valid(is_col, ["Interest Expense", "Interest Expense Non Operating"]) or 0.0
            tax_provision = _get_first_valid(is_col, ["Tax Provision", "Income Tax Expense"]) or 0.0

            # 2. 대차대조표 (자본)
            total_assets = _get_first_valid(bs_col, ["Total Assets"])
            current_liabilities = _get_first_valid(bs_col, ["Current Liabilities", "Total Current Liabilities"]) or 0.0
            cash_and_sti = _get_first_valid(bs_col, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"]) or 0.0
            total_equity = _get_first_valid(bs_col, ["Stockholders Equity", "Total Equity Gross Minority Interest"])

            ce_standard = total_assets - current_liabilities if pd.notna(total_assets) else np.nan
            if deduct_cash_from_ce and pd.notna(ce_standard):
                min_ce = total_assets * 0.05 if pd.notna(total_assets) else 0.0
                ce_val = max(ce_standard - cash_and_sti, min_ce)
            else:
                ce_val = ce_standard

            # 3. 현금흐름
            ocf = _get_first_valid(cf_col, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"])
            capex_raw = _get_first_valid(cf_col, ["Capital Expenditure", "Capital Expenditure Reported"])
            capex = abs(capex_raw) if pd.notna(capex_raw) else 0.0
            da = _get_first_valid(cf_col, ["Depreciation And Amortization", "Depreciation Amortization Depletion"]) or 0.0
            chg_wc = _get_first_valid(cf_col, ["Change In Working Capital", "Changes In Working Capital"])

            # 4. 비율 지표 계산
            gpm = (gross_profit / revenue * 100.0) if (pd.notna(revenue) and revenue > 0 and pd.notna(gross_profit)) else np.nan
            opm = (ebit / revenue * 100.0) if (pd.notna(revenue) and revenue > 0 and pd.notna(ebit)) else np.nan
            ebit_margin = opm

            turnover = (revenue / ce_val) if (pd.notna(revenue) and pd.notna(ce_val) and ce_val > 0) else np.nan
            roce = (ebit / ce_val * 100.0) if (pd.notna(ebit) and pd.notna(ce_val) and ce_val > 0) else np.nan

            fcf = ocf - capex if pd.notna(ocf) else np.nan
            norm_fcf = ocf - da if pd.notna(ocf) else np.nan

            # CCR
            if ccr_denominator == "net_income":
                ccr = (fcf / net_income * 100.0) if (pd.notna(fcf) and pd.notna(net_income) and net_income > 0) else np.nan
            elif ccr_denominator == "pretax_ebit":
                ccr = ((fcf + max(tax_provision, 0.0)) / ebit * 100.0) if (pd.notna(fcf) and pd.notna(ebit) and ebit > 0) else np.nan
            elif ccr_denominator == "ocf_only":
                ccr = (ocf / ebit * 100.0) if (pd.notna(ocf) and pd.notna(ebit) and ebit > 0) else np.nan
            else:
                ccr = (fcf / ebit * 100.0) if (pd.notna(fcf) and pd.notna(ebit) and ebit > 0) else np.nan

            capex_to_da = (capex / da * 100.0) if (da > 0) else np.nan
            wc_to_ebit = (chg_wc / ebit * 100.0) if (pd.notna(chg_wc) and pd.notna(ebit) and ebit > 0) else np.nan

            # 이자보상배율
            if pd.isna(ebit):
                icr_display = "N/A"
                icr_val = np.nan
            elif ebit <= 0:
                icr_display = f"{(ebit / interest_expense):.1f}배 (적자)" if interest_expense > 0 else "적자"
                icr_val = (ebit / interest_expense) if interest_expense > 0 else -999.0
            else:
                if interest_expense <= 0 or (ebit / interest_expense) >= 999.0:
                    icr_display = "∞ (무차입/순현금)"
                    icr_val = 9999.0
                else:
                    ratio = ebit / interest_expense
                    icr_display = f"{ratio:.1f}배"
                    icr_val = ratio

            records.append({
                "fiscal_date": fiscal_date,
                "revenue": revenue,
                "gross_profit": gross_profit,
                "operating_income": ebit,
                "net_income": net_income,
                "total_assets": total_assets,
                "ce": ce_val,
                "cash_and_sti": cash_and_sti,
                "ocf": ocf,
                "capex": capex,
                "da": da,
                "fcf": fcf,
                "norm_fcf": norm_fcf,
                "chg_wc": chg_wc,
                "GPM (%)": gpm,
                "OPM (%)": opm,
                "ROCE (%)": roce,
                "EBIT Margin (%)": ebit_margin,
                "사용자본회전율 (배)": turnover,
                "CCR (%)": ccr,
                "CapEx/감가상각비 (%)": capex_to_da,
                "운전자본변동/EBIT (%)": wc_to_ebit,
                "이자보상배율_수치": icr_val,
                "이자보상배율": icr_display,
            })

        df_out = pd.DataFrame(records)
        # 시간순 정렬 (과거 -> 최신)
        if not df_out.empty and "fiscal_date" in df_out.columns:
            df_out = df_out.sort_values(by="fiscal_date", ascending=True).reset_index(drop=True)
        return df_out
    except Exception:
        return pd.DataFrame()


# =====================================================================
# 4. 로컬 캐시 저장 및 로드
# =====================================================================
def get_cache_path(market: str) -> Path:
    return RAW_CACHE_KR_PATH if market.upper() == "KR" else RAW_CACHE_US_PATH


def save_raw_cache(df: pd.DataFrame, market: str) -> None:
    if df is None or df.empty:
        return
    path = get_cache_path(market)
    df.to_parquet(path, index=False)


def load_raw_cache(market: str) -> pd.DataFrame:
    path = get_cache_path(market)
    if path.exists():
        try:
            df = pd.read_parquet(path)
            if market.upper() == "KR":
                krx_map = load_krx_name_map()
                if krx_map:
                    def _map_kr_name(row: pd.Series) -> str:
                        code = str(row["symbol"]).split(".")[0]
                        return krx_map.get(code, {}).get("name", row["name"])
                    df["name"] = df.apply(_map_kr_name, axis=1)
            return df
        except Exception:
            pass
    return pd.DataFrame()


def refresh_prices_and_market_cap(market: str = "ALL") -> int:
    """
    재무제표 전체를 다시 받지 않고, 로컬 캐시에 저장된 종목들의 현재가(price)와 시가총액(market_cap)만
    초고속(1~2초)으로 최신화하여 역DCF 기대성장률을 즉시 갱신합니다.
    """
    target_markets = ["KR", "US"] if market.upper() == "ALL" else [market.upper()]
    updated_total = 0

    for mkt in target_markets:
        df = load_raw_cache(mkt)
        if df is None or df.empty:
            continue

        region = "kr" if mkt == "KR" else "us"
        min_cap = 50_000_000_000 if mkt == "KR" else 500_000_000
        q = yf.EquityQuery(
            "and",
            [
                yf.EquityQuery("eq", ["region", region]),
                yf.EquityQuery("gt", ["intradaymarketcap", float(min_cap)]),
            ],
        )

        quote_map: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
        for offset in [0, 250, 500]:
            try:
                res = yf.screen(
                    q,
                    offset=offset,
                    size=250,
                    sortField="intradaymarketcap",
                    sortAsc=False,
                )
                quotes = res.get("quotes", [])
                if not quotes:
                    break
                for item in quotes:
                    sym = item.get("symbol")
                    if sym:
                        quote_map[sym] = (item.get("regularMarketPrice"), item.get("marketCap"))
                if offset + len(quotes) >= res.get("total", 0):
                    break
            except Exception:
                break

        # screen 결과에 없는 개별 종목은 순차적으로 fast_info 조회 (SQLite lock 방지 위해 단일 스레드)
        missing_syms = [s for s in df["symbol"].tolist() if s not in quote_map]
        for sym in missing_syms[:30]:
            try:
                fi = yf.Ticker(sym).fast_info
                p = fi.get("lastPrice")
                mc = fi.get("marketCap")
                if p is not None or mc is not None:
                    quote_map[sym] = (p, mc)
            except Exception:
                continue

        new_prices = []
        new_mcaps = []
        for _, row in df.iterrows():
            sym = row["symbol"]
            old_p = row.get("price", np.nan)
            old_mc = row.get("market_cap", np.nan)
            if sym in quote_map:
                p_val, mc_val = quote_map[sym]
                new_p = float(p_val) if p_val is not None and pd.notna(p_val) else old_p
                new_mc = float(mc_val) if mc_val is not None and pd.notna(mc_val) else old_mc
                new_prices.append(new_p)
                new_mcaps.append(new_mc)
                updated_total += 1
            else:
                new_prices.append(old_p)
                new_mcaps.append(old_mc)

        df["price"] = new_prices
        df["market_cap"] = new_mcaps
        save_raw_cache(df, mkt)

    return updated_total


# =====================================================================
# 5. 지표 계산 및 CCR / ROCE 해석 엔진 (권장 설정안 반영)
# =====================================================================
def _diagnose_ccr_row(row: pd.Series) -> str:
    """
    CCR 수치 및 현금흐름 구성을 바탕으로 100% 미만/이상 원인을 자동 진단합니다.
    - 100% 미만 원인: 1. 운전자본 증가(현금유출), 2. 감가상각비보다 큰 CapEx 지출
    - 100% 이상 원인: 1. 선수금/운전자본 유입, 2. 감가상각비가 CapEx보다 큼, 3. 매입채무 활용
    """
    ccr = row.get("CCR (%)")
    if pd.isna(ccr):
        return "산출 불가 (적자 또는 데이터 결측)"

    capex = row.get("capex", 0.0) or 0.0
    da = row.get("da", 0.0) or 0.0
    chg_wc = row.get("chg_wc", np.nan)
    chg_payables = row.get("chg_payables", np.nan)
    capex_to_da = row.get("CapEx/감가상각비 (%)", np.nan)

    reasons: List[str] = []

    if ccr < 100.0:
        # 1. 운전자본 증가 (현금흐름표상 chg_wc < 0 이면 운전자본 증가로 현금 유출)
        if pd.notna(chg_wc) and chg_wc < 0:
            reasons.append("① 운전자본 증가(현금묶임)")
        # 2. 감가상각보다 더 큰 CapEx 지출
        if da > 0 and capex > da:
            ratio_str = f"{capex_to_da:.0f}%" if pd.notna(capex_to_da) else ""
            reasons.append(f"② CapEx > 감가상각비({ratio_str})")
        elif da == 0 and capex > 0:
            reasons.append("② CapEx 지출 발생")

        if not reasons:
            reasons.append("법인세·이자 현금유출 등 기타")
        return "[100% 미만] " + " / ".join(reasons)

    else:
        # CCR >= 100%인 상황
        # 2. 감가상각비가 CapEx보다 더 큼
        if da > capex:
            ratio_str = f"{capex_to_da:.0f}%" if pd.notna(capex_to_da) else ""
            reasons.append(f"② 감가상각비 > CapEx(CapEx/D&A {ratio_str})")
        # 1 & 3. 운전자본 유입 (선수금 / 매입채무 활용)
        if pd.notna(chg_wc) and chg_wc > 0:
            if pd.notna(chg_payables) and chg_payables > 0:
                reasons.append("③ 매입채무 활용 및 ① 선수금·운전자본 유입")
            else:
                reasons.append("① 선수금(구독료 등)·운전자본 현금유입")
        elif pd.notna(chg_payables) and chg_payables > 0:
            reasons.append("③ 매입채무 증가(현금유입)")

        if not reasons:
            reasons.append("비현금비용 가산 / 기타 영업현금 유입")
        return "[100% 이상] " + " / ".join(reasons)


def compute_quality_metrics(
    raw_df: pd.DataFrame,
    deduct_cash_from_ce: bool = False,
    ccr_denominator: str = "ebit",  # "ebit" (영업이익), "net_income" (순이익), "ocf_only" (OCF/영업이익)
    allow_missing_gpm_as_opm: bool = False,
    required_return_pct: float = 10.0,
) -> pd.DataFrame:
    """
    원천 재무제표 DataFrame으로부터 필터 지표 및 참고 지표를 계산합니다.
    """
    if raw_df is None or raw_df.empty:
        return pd.DataFrame()

    df = raw_df.copy()

    # 1. 기준 영업이익(EBIT) 설정: K-IFRS 및 표준 영업이익(Operating Income) 우선
    ebit = df["operating_income"].fillna(df["ebit_reported"])
    rev = df["revenue"].replace(0, np.nan)

    # 2. GPM (%) 및 참고 지표 OPM (%)
    gp = df["gross_profit"].copy()
    if allow_missing_gpm_as_opm:
        gp = gp.fillna(ebit)

    df["GPM (%)"] = (gp / rev) * 100.0
    df["OPM (%)"] = (ebit / rev) * 100.0

    # 3. 사용자본(Capital Employed) 및 ROCE (%), EBIT Margin (%), 사용자본회전율 (배)
    ce_standard = df["total_assets"] - df["current_liabilities"]
    if deduct_cash_from_ce:
        cash = df["cash_and_sti"].fillna(0.0)
        ce_cash_deducted = ce_standard - cash
        # 현금이 너무 많아 CE가 0 이하가 되는 경우 최소 총자산의 5%로 하한 방어
        min_ce = df["total_assets"] * 0.05
        ce = np.where(ce_cash_deducted > min_ce, ce_cash_deducted, min_ce)
        ce = pd.Series(ce, index=df.index)
    else:
        ce = ce_standard

    ce_valid = ce.where(ce > 0, np.nan)

    df["EBIT Margin (%)"] = (ebit / rev) * 100.0
    df["사용자본회전율 (배)"] = rev / ce_valid
    df["ROCE (%)"] = (ebit / ce_valid) * 100.0

    # 비교 참고용으로 표준 ROCE와 현금차감 ROCE를 모두 내부 컬럼으로 보관
    ce_std_valid = ce_standard.where(ce_standard > 0, np.nan)
    ce_net_raw = ce_standard - df["cash_and_sti"].fillna(0.0)
    ce_net_valid = pd.Series(
        np.where(ce_net_raw > (df["total_assets"] * 0.05), ce_net_raw, df["total_assets"] * 0.05),
        index=df.index,
    ).where(lambda s: s > 0, np.nan)
    df["ROCE_표준 (%)"] = (ebit / ce_std_valid) * 100.0
    df["ROCE_현금차감 (%)"] = (ebit / ce_net_valid) * 100.0

    # 4. CCR (현금전환율, %) 및 원인 분석 보조 지표
    fcf = df["ocf"] - df["capex"].fillna(0.0)
    df["fcf"] = fcf
    tax_col = df["tax_provision"].fillna(0.0) if "tax_provision" in df.columns else pd.Series(0.0, index=df.index)
    tax_positive = tax_col.where(tax_col > 0, 0.0)

    if ccr_denominator == "net_income":
        # 세후 FCF / 세후 당기순이익 (D&A == CapEx, 운전자본변동 == 0 일 때 정확히 100%)
        denom = df["net_income"].where(df["net_income"] > 0, np.nan)
        df["CCR (%)"] = (fcf / denom) * 100.0
    elif ccr_denominator == "pretax_ebit":
        # 테리 스미스 정석 근사: 세전 영업현금흐름(OCF + 법인세 - CapEx) / 세전 영업이익(EBIT)
        denom = ebit.where(ebit > 0, np.nan)
        df["CCR (%)"] = ((fcf + tax_positive) / denom) * 100.0
    elif ccr_denominator == "ocf_only":
        denom = ebit.where(ebit > 0, np.nan)
        df["CCR (%)"] = (df["ocf"] / denom) * 100.0
    else:
        # 단순 (OCF - CapEx) / 영업이익(EBIT)
        denom = ebit.where(ebit > 0, np.nan)
        df["CCR (%)"] = (fcf / denom) * 100.0

    da_valid = df["da"].where(df["da"] > 0, np.nan)
    df["CapEx/감가상각비 (%)"] = (df["capex"].fillna(0.0) / da_valid) * 100.0
    df["운전자본변동/EBIT (%)"] = (df["chg_wc"] / ebit.where(ebit > 0, np.nan)) * 100.0

    # 5. 이자보상배율 (배) - 무차입(이자비용 0 또는 결측) 흑자 기업 예외 처리
    int_exp = df["interest_expense"].fillna(0.0)
    icr_numeric = []
    icr_display = []

    for e_val, i_val in zip(ebit, int_exp):
        if pd.isna(e_val):
            icr_numeric.append(np.nan)
            icr_display.append("N/A")
        elif e_val <= 0:
            # 영업적자 기업
            val = (e_val / i_val) if i_val > 0 else -999.0
            icr_numeric.append(val)
            icr_display.append(f"{val:.1f}배 (적자)")
        else:
            # 영업흑자 기업 중 이자비용이 0 이하(무차입)이거나 극미한 경우
            if i_val <= 0 or (e_val / i_val) >= 999.0:
                icr_numeric.append(9999.0)
                icr_display.append("∞ (무차입/순현금)")
            else:
                ratio = e_val / i_val
                icr_numeric.append(ratio)
                icr_display.append(f"{ratio:.1f}배")

    df["이자보상배율 (배)"] = icr_numeric
    df["이자보상배율_표시"] = icr_display

    # 6. 시가총액 단위 변환 (한국: 조/억 원, 미국: $B)
    mcap_display = []
    mcap_unit_num = []
    for mkt, mcap in zip(df["market"], df["market_cap"]):
        if pd.isna(mcap) or mcap <= 0:
            mcap_display.append("N/A")
            mcap_unit_num.append(np.nan)
        elif str(mkt).upper() == "KR":
            uk = mcap / 1e8  # 억원
            mcap_unit_num.append(uk)
            if uk >= 10000:
                mcap_display.append(f"{uk / 10000:.2f}조 원")
            else:
                mcap_display.append(f"{uk:,.0f}억 원")
        else:
            bil = mcap / 1e9  # Billion USD
            mcap_unit_num.append(bil)
            mcap_display.append(f"${bil:,.2f}B")

    df["시가총액_표시"] = mcap_display
    df["시가총액_단위수치"] = mcap_unit_num  # KR: 억원, US: $B

    # 7. 정상화 FCF (OCF - 감가상각비) 기반 FCF 수익률 및 역DCF 기대성장률 (g = r - FCF Yield)
    #    유지보수 CapEx를 감가상각비(D&A)로 근사하여 성장 CapEx로 인한 왜곡을 제거한 주주이익 기준
    norm_fcf = df["ocf"] - df["da"].fillna(0.0)
    df["norm_fcf"] = norm_fcf
    mcap_valid = df["market_cap"].where(df["market_cap"] > 0, np.nan)
    df["정상화 FCF 수익률 (%)"] = (norm_fcf / mcap_valid) * 100.0
    df["역DCF 기대성장률 (%)"] = float(required_return_pct) - df["정상화 FCF 수익률 (%)"]

    # 8. CCR 자동 진단 코멘트 생성
    df["CCR 상태 진단"] = df.apply(_diagnose_ccr_row, axis=1)

    # 9. 시장 세부 거래소 구분 (KR (KOSPI), KR (KOSDAQ), US (NASDAQ), US (NYSE) 등)
    def _format_market_detail(row: pd.Series) -> str:
        sym = str(row.get("symbol", "")).strip().upper()
        mkt = str(row.get("market", "")).strip().upper()
        exch = str(row.get("exchange", "")).strip().upper()

        if mkt == "KR" or sym.endswith(".KS") or sym.endswith(".KQ") or sym.endswith(".KN"):
            if sym.endswith(".KQ") or exch == "KOSDAQ":
                return "KR (KOSDAQ)"
            elif sym.endswith(".KN") or exch == "KONEX":
                return "KR (KONEX)"
            else:
                return "KR (KOSPI)"
        elif mkt == "US":
            if exch in ["NMS", "NGM", "NCM", "NASDAQ"] or "NASDAQ" in exch:
                return "US (NASDAQ)"
            elif exch in ["NYQ", "NYSE"] or "NYSE" in exch:
                return "US (NYSE)"
            elif exch in ["ASE", "AMX", "AMEX"]:
                return "US (AMEX)"
            elif exch and exch not in ["NAN", "NONE", ""]:
                return f"US ({exch})"
            else:
                return "US"
        return mkt

    df["market_display"] = df.apply(_format_market_detail, axis=1)

    return df


# =====================================================================
# 6. 조건식 평가 엔진 (Filter Rule Evaluator)
# =====================================================================
OPERATORS = {
    ">=": lambda s, v: s >= v,
    "<=": lambda s, v: s <= v,
    ">": lambda s, v: s > v,
    "<": lambda s, v: s < v,
    "==": lambda s, v: s == v,
}


def apply_filter_rules(
    df: pd.DataFrame,
    rules: List[Dict[str, Any]],
) -> Tuple[pd.DataFrame, pd.DataFrame, List[Dict[str, Any]]]:
    """
    규칙 리스트를 받아:
    1) 모든 활성 규칙을 통과한 최종 DataFrame (`filtered_df`)
    2) 각 규칙별 통과 여부 컬럼이 추가된 전체 DataFrame (`annotated_df`)
    3) 단계별 퍼널 통계 (`funnel_stats`)
    를 반환합니다.

    rule 예시:
    {"metric": "GPM (%)", "operator": ">=", "value": 40.0, "enabled": True, "label": "GPM >= 40%"}
    """
    if df is None or df.empty:
        return pd.DataFrame(), pd.DataFrame(), []

    annotated = df.copy()
    cumulative_mask = pd.Series(True, index=annotated.index)
    funnel_stats: List[Dict[str, Any]] = [
        {"stage": "전체 분석 대상", "remaining": int(len(annotated)), "single_pass": int(len(annotated))}
    ]

    pass_count_series = pd.Series(0, index=annotated.index)
    active_rule_count = 0

    for idx, rule in enumerate(rules):
        if not rule.get("enabled", True):
            continue

        metric = rule["metric"]
        op_str = rule.get("operator", ">=")
        val = float(rule["value"])
        label = rule.get("label") or f"{metric} {op_str} {val}"

        if metric not in annotated.columns or op_str not in OPERATORS:
            continue

        active_rule_count += 1
        col_series = pd.to_numeric(annotated[metric], errors="coerce")
        op_func = OPERATORS[op_str]
        single_mask = op_func(col_series, val).fillna(False)

        col_pass_name = f"통과_{metric}"
        annotated[col_pass_name] = single_mask
        pass_count_series += single_mask.astype(int)
        cumulative_mask = cumulative_mask & single_mask

        funnel_stats.append(
            {
                "stage": label,
                "remaining": int(cumulative_mask.sum()),
                "single_pass": int(single_mask.sum()),
            }
        )

    annotated["통과_조건수"] = f"{0}/{active_rule_count}"
    if active_rule_count > 0:
        annotated["통과_조건수"] = pass_count_series.astype(str) + f" / {active_rule_count}"
    annotated["최종_통과"] = cumulative_mask

    filtered_df = annotated[cumulative_mask].copy().reset_index(drop=True)
    return filtered_df, annotated, funnel_stats
