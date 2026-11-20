# -*- coding: utf-8 -*-
"""
한·미 주식 퀄리티 스크리너 데이터 수집 및 지표 산출 엔진
- 한국(KR) 및 미국(US) 상장사 유니버스 조회 (yfinance EquityQuery + KRX 한글 종목명 매핑)
- 재무제표(손익계산서, 재무상태표, 현금흐름표) 최근 5개년(가용 전체 연도) 병렬 수집 및 로컬 Parquet 캐싱
- 최근 결산 지표 및 5개년 평균 지표 동시 산출 (GPM, OPM, ROCE, EBIT Margin, 회전율, CCR, 이자보상배율, 정상화 FCF)
- 정밀 2단계(Two-Stage) 역DCF 및 DCF 내재가치 산출 엔진 (성장기간 N년, 성장기간 성장률 g1, 이후 영구성장률 g2)
- 유니버스(Universe) 영구 보관함 및 기업별 메모/URL·성장가정 저장 관리 (data/universe_store.json)
"""

from __future__ import annotations

import io
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
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
UNIVERSE_STORE_PATH = DATA_DIR / "universe_store.json"


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
    """
    region = "kr" if market.upper() == "KR" else "us"
    operands = [
        yf.EquityQuery("eq", ["region", region]),
        yf.EquityQuery("gt", ["intradaymarketcap", float(min_market_cap)]),
    ]
    if market.upper() == "US":
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
# 3. 개별 종목 재무제표 원천 데이터 추출 (최신 결산 + 최근 5개년 히스토리 동시 수집)
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


def _extract_year_record(
    col_name: Any,
    is_df: pd.DataFrame,
    bs_df: pd.DataFrame,
    cf_df: pd.DataFrame,
) -> Dict[str, Any]:
    """단일 결산연도 컬럼에서 원천 재무 계정들을 추출합니다."""
    is_col = is_df[col_name]
    bs_col = bs_df[col_name] if col_name in bs_df.columns else (bs_df.iloc[:, 0] if not bs_df.empty else pd.Series(dtype=float))
    cf_col = cf_df[col_name] if col_name in cf_df.columns else (cf_df.iloc[:, 0] if not cf_df.empty else pd.Series(dtype=float))

    fiscal_date = str(col_name)[:10] if col_name is not None else ""

    # 1) 손익계산서
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
            "Net Income Continuous Operations",
        ],
    )
    interest_expense = _get_first_valid(
        is_col, ["Interest Expense", "Interest Expense Non Operating"]
    )
    if pd.notna(interest_expense):
        interest_expense = abs(interest_expense)
    tax_provision = _get_first_valid(is_col, ["Tax Provision", "Income Tax Expense"])

    # 2) 재무상태표
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

    # 3) 현금흐름표
    ocf = _get_first_valid(
        cf_col, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"]
    )
    raw_capex = _get_first_valid(
        cf_col, ["Capital Expenditure", "Capital Expenditure Reported", "Purchase Of PPE", "Net PPE Purchase And Sale"]
    )
    if pd.notna(raw_capex):
        capex = abs(raw_capex) if raw_capex < 0 else raw_capex
    else:
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

    chg_wc = _get_first_valid(cf_col, ["Change In Working Capital", "Changes In Working Capital"])
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

    return {
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


def _clean_for_json(val: Any) -> Any:
    if isinstance(val, (float, np.floating)):
        if np.isnan(val) or np.isinf(val):
            return None
        return float(val)
    if isinstance(val, (int, np.integer)):
        return int(val)
    return val


def fetch_single_stock_raw(item: Dict[str, Any], max_years: int = 5) -> Optional[Dict[str, Any]]:
    """
    단일 종목의 연간 재무제표(IS, BS, CF)에서 최신 결산 데이터와 최근 5개년(가용 연도) 히스토리를 한 번에 추출합니다.
    """
    sym = item["symbol"]
    try:
        tk = yf.Ticker(sym)
        is_df = tk.income_stmt
        bs_df = tk.balance_sheet
        cf_df = tk.cashflow

        if is_df is None or is_df.empty or bs_df is None or bs_df.empty or cf_df is None or cf_df.empty:
            return None

        # 매출액이 유효한 결산연도 컬럼들을 최신순으로 최대 max_years개 추출
        valid_cols = []
        for col_name in is_df.columns:
            cand = is_df[col_name]
            rev_test = _get_first_valid(cand, ["Total Revenue", "Operating Revenue"])
            if pd.notna(rev_test) and rev_test > 0:
                valid_cols.append(col_name)
            if len(valid_cols) >= max_years:
                break

        if not valid_cols:
            return None

        yearly_records = []
        for col_name in valid_cols:
            rec = _extract_year_record(col_name, is_df, bs_df, cf_df)
            yearly_records.append(rec)

        latest = yearly_records[0]

        exch_val = item.get("exchange")
        if not exch_val:
            if str(item.get("market")).upper() == "KR" or sym.endswith(".KS") or sym.endswith(".KQ"):
                exch_val = "KOSDAQ" if sym.endswith(".KQ") else "KOSPI"
            else:
                try:
                    exch_val = str(tk.fast_info.get("exchange", ""))
                except Exception:
                    exch_val = ""

        mcap_val = item.get("market_cap", np.nan)
        price_val = item.get("price", np.nan)
        if pd.isna(mcap_val) or pd.isna(price_val):
            try:
                fi = tk.fast_info
                if pd.isna(price_val):
                    price_val = fi.get("lastPrice", np.nan)
                if pd.isna(mcap_val):
                    mcap_val = fi.get("marketCap", np.nan)
            except Exception:
                pass

        clean_history = [
            {k: _clean_for_json(v) for k, v in yr_rec.items()}
            for yr_rec in yearly_records
        ]

        out = {
            "symbol": sym,
            "name": item.get("name", sym),
            "market": item.get("market", "KR"),
            "exchange": exch_val,
            "sector": item.get("sector", ""),
            "currency": item.get("currency", "KRW"),
            "market_cap": mcap_val,
            "price": price_val,
            **latest,
            "history_years_cnt": len(yearly_records),
            "history_json": json.dumps(clean_history, ensure_ascii=False),
        }
        return out
    except Exception:
        return None


def fetch_batch_raw_financials(
    items: List[Dict[str, Any]],
    max_workers: int = 10,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> pd.DataFrame:
    """
    멀티스레딩으로 여러 기업의 원천 재무 데이터(최신 + 5개년 히스토리)를 병렬 수집하여 DataFrame으로 반환합니다.
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
    if "market_cap" in df.columns:
        df = df.sort_values(by="market_cap", ascending=False).reset_index(drop=True)
    return df


def backfill_multiyear_history_for_cache(
    market: str = "ALL",
    max_workers: int = 12,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> int:
    """
    기존 로컬 캐시에 `history_json` (5개년 데이터)이 없는 종목들만 골라 다개년 재무제표를 보강 저장합니다.
    """
    target_markets = ["KR", "US"] if market.upper() == "ALL" else [market.upper()]
    updated_count = 0

    for mkt in target_markets:
        df = load_raw_cache(mkt)
        if df is None or df.empty:
            continue

        needs_backfill = False
        if "history_json" not in df.columns:
            needs_backfill = True
        else:
            missing_mask = df["history_json"].isna() | (df["history_json"].astype(str).str.len() < 10)
            if missing_mask.any():
                needs_backfill = True

        if not needs_backfill:
            continue

        items = df.to_dict(orient="records")
        new_df = fetch_batch_raw_financials(items, max_workers=max_workers, progress_callback=progress_callback)
        if not new_df.empty:
            save_raw_cache(new_df, mkt)
            updated_count += len(new_df)

    return updated_count


def _compute_single_year_metrics_dict(
    rec: Dict[str, Any],
    ccr_denominator: str = "net_income",
    deduct_cash_from_ce: bool = False,
    allow_missing_gpm_as_opm: bool = False,
) -> Dict[str, Any]:
    """단일 연도 원천 딕셔너리에서 비율 지표들을 계산합니다."""
    revenue = rec.get("revenue", np.nan)
    revenue = float(revenue) if revenue is not None and pd.notna(revenue) else np.nan
    gross_profit = rec.get("gross_profit", np.nan)
    gross_profit = float(gross_profit) if gross_profit is not None and pd.notna(gross_profit) else np.nan
    operating_income = rec.get("operating_income", np.nan)
    operating_income = float(operating_income) if operating_income is not None and pd.notna(operating_income) else np.nan
    ebit_reported = rec.get("ebit_reported", np.nan)
    ebit_reported = float(ebit_reported) if ebit_reported is not None and pd.notna(ebit_reported) else np.nan

    ebit = operating_income if pd.notna(operating_income) else ebit_reported
    if pd.isna(gross_profit) and allow_missing_gpm_as_opm:
        gross_profit = ebit

    net_income = rec.get("net_income", np.nan)
    net_income = float(net_income) if net_income is not None and pd.notna(net_income) else np.nan
    interest_expense = rec.get("interest_expense", 0.0)
    interest_expense = float(interest_expense) if interest_expense is not None and pd.notna(interest_expense) else 0.0
    tax_provision = rec.get("tax_provision", 0.0)
    tax_provision = float(tax_provision) if tax_provision is not None and pd.notna(tax_provision) else 0.0

    total_assets = rec.get("total_assets", np.nan)
    total_assets = float(total_assets) if total_assets is not None and pd.notna(total_assets) else np.nan
    current_liabilities = rec.get("current_liabilities", 0.0)
    current_liabilities = float(current_liabilities) if current_liabilities is not None and pd.notna(current_liabilities) else 0.0
    cash_and_sti = rec.get("cash_and_sti", 0.0)
    cash_and_sti = float(cash_and_sti) if cash_and_sti is not None and pd.notna(cash_and_sti) else 0.0

    ce_standard = total_assets - current_liabilities if pd.notna(total_assets) else np.nan
    if deduct_cash_from_ce and pd.notna(ce_standard):
        min_ce = total_assets * 0.05 if pd.notna(total_assets) else 0.0
        ce_val = max(ce_standard - cash_and_sti, min_ce)
    else:
        ce_val = ce_standard

    ocf = rec.get("ocf", np.nan)
    ocf = float(ocf) if ocf is not None and pd.notna(ocf) else np.nan
    capex = rec.get("capex", 0.0)
    capex = abs(float(capex)) if capex is not None and pd.notna(capex) else 0.0
    da = rec.get("da", 0.0)
    da = float(da) if da is not None and pd.notna(da) else 0.0
    chg_wc = rec.get("chg_wc", np.nan)
    chg_wc = float(chg_wc) if chg_wc is not None and pd.notna(chg_wc) else np.nan

    gpm = (gross_profit / revenue * 100.0) if (pd.notna(revenue) and revenue > 0 and pd.notna(gross_profit)) else np.nan
    opm = (ebit / revenue * 100.0) if (pd.notna(revenue) and revenue > 0 and pd.notna(ebit)) else np.nan
    ebit_margin = opm
    turnover = (revenue / ce_val) if (pd.notna(revenue) and pd.notna(ce_val) and ce_val > 0) else np.nan
    roce = (ebit / ce_val * 100.0) if (pd.notna(ebit) and pd.notna(ce_val) and ce_val > 0) else np.nan

    fcf = ocf - capex if pd.notna(ocf) else np.nan
    norm_fcf = ocf - da if pd.notna(ocf) else np.nan

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

    return {
        "fiscal_date": str(rec.get("fiscal_date", ""))[:10],
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
    }


def fetch_stock_multiyear_data(
    symbol: str,
    market: str = "KR",
    ccr_denominator: str = "net_income",
    deduct_cash_from_ce: bool = False,
    allow_missing_gpm_as_opm: bool = False,
    max_years: int = 5,
    cached_history_json: Optional[str] = None,
) -> pd.DataFrame:
    """
    개별 기업의 최근 4~5개년 연간 재무제표를 바탕으로 연도별 지표 추이를 반환합니다.
    로컬 캐시에 `history_json`이 있으면 네트워크 호출 없이 0초 만에 즉시 변환합니다.
    """
    if cached_history_json and isinstance(cached_history_json, str) and len(cached_history_json) > 10:
        try:
            raw_list = json.loads(cached_history_json)
            if isinstance(raw_list, list) and len(raw_list) > 0:
                records = [
                    _compute_single_year_metrics_dict(
                        rec,
                        ccr_denominator=ccr_denominator,
                        deduct_cash_from_ce=deduct_cash_from_ce,
                        allow_missing_gpm_as_opm=allow_missing_gpm_as_opm,
                    )
                    for rec in raw_list[:max_years]
                ]
                df_out = pd.DataFrame(records)
                if not df_out.empty and "fiscal_date" in df_out.columns:
                    df_out = df_out.sort_values(by="fiscal_date", ascending=True).reset_index(drop=True)
                return df_out
        except Exception:
            pass

    try:
        tk = yf.Ticker(symbol)
        is_df = tk.income_stmt
        bs_df = tk.balance_sheet
        cf_df = tk.cashflow

        if is_df is None or is_df.empty or bs_df is None or bs_df.empty or cf_df is None or cf_df.empty:
            return pd.DataFrame()

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
            raw_rec = _extract_year_record(col_name, is_df, bs_df, cf_df)
            metrics_rec = _compute_single_year_metrics_dict(
                raw_rec,
                ccr_denominator=ccr_denominator,
                deduct_cash_from_ce=deduct_cash_from_ce,
                allow_missing_gpm_as_opm=allow_missing_gpm_as_opm,
            )
            records.append(metrics_rec)

        df_out = pd.DataFrame(records)
        if not df_out.empty and "fiscal_date" in df_out.columns:
            df_out = df_out.sort_values(by="fiscal_date", ascending=True).reset_index(drop=True)
        return df_out
    except Exception:
        return pd.DataFrame()


# =====================================================================
# 4. 로컬 캐시 저장 및 로드 & 유니버스 보관함(Universe Store) 영구 저장소
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


def load_universe_store() -> Dict[str, Dict[str, Any]]:
    """
    유니버스 보관함(`data/universe_store.json`)을 로드합니다.
    반환 형태: {symbol: {"symbol": ..., "name": ..., "market": ..., "memo": ..., "growth_years": 10, "growth_rate_est": 10.0, "terminal_growth_rate": 0.0, "added_at": ...}}
    """
    if UNIVERSE_STORE_PATH.exists():
        try:
            with open(UNIVERSE_STORE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def save_universe_store(store: Dict[str, Dict[str, Any]]) -> None:
    """유니버스 보관함 딕셔너리를 JSON 파일로 영구 저장합니다."""
    with open(UNIVERSE_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def upsert_universe_item(
    symbol: str,
    name: str,
    market: str = "KR",
    memo: Optional[str] = None,
    growth_years: Optional[int] = None,
    growth_rate_est: Optional[float] = None,
    terminal_growth_rate: Optional[float] = None,
) -> Dict[str, Any]:
    """유니버스에 기업을 추가하거나 메모/성장기간 파라미터를 업데이트합니다."""
    store = load_universe_store()
    existing = store.get(symbol, {})
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    item = {
        "symbol": symbol,
        "name": name or existing.get("name", symbol),
        "market": market or existing.get("market", "KR"),
        "memo": memo if memo is not None else existing.get("memo", ""),
        "growth_years": int(growth_years) if growth_years is not None else int(existing.get("growth_years", 10)),
        "growth_rate_est": float(growth_rate_est) if growth_rate_est is not None else float(existing.get("growth_rate_est", 10.0)),
        "terminal_growth_rate": float(terminal_growth_rate) if terminal_growth_rate is not None else float(existing.get("terminal_growth_rate", 0.0)),
        "added_at": existing.get("added_at", now_str),
        "updated_at": now_str,
    }
    store[symbol] = item
    save_universe_store(store)
    return item


def remove_universe_item(symbol: str) -> None:
    """유니버스에서 특정 기업을 제거합니다."""
    store = load_universe_store()
    if symbol in store:
        del store[symbol]
        save_universe_store(store)


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

        missing_syms = [s for s in df["symbol"].tolist() if s not in quote_map]
        for sym in missing_syms[:35]:
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
# 5. 정밀 2단계(Two-Stage) DCF 내재가치 & 역DCF 기대성장률 계산 엔진
# =====================================================================
def calc_two_stage_dcf_value(
    fcf0: float,
    r_pct: float,
    n_years: int,
    g1_pct: float,
    g2_pct: float = 0.0,
) -> Dict[str, float]:
    """
    [정밀 2단계 DCF 내재가치 계산]
    - fcf0: 기준 정상화 FCF (= OCF - D&A)
    - r_pct: 요구수익률(할인율) r (%)
    - n_years: 1단계 성장 지속기간 N (년)
    - g1_pct: 1단계(1~N년) 연평균 성장률 g1 (%)
    - g2_pct: 2단계(N년 이후) 영구성장률 g2 (%) (기본 0%)

    수식:
      PV_1 (1~N년 현금흐름 현가합) = sum_{t=1..N} FCF0 * (1 + g1)^t / (1 + r)^t
      TV_N (N년 시점 영구가치)    = FCF0 * (1 + g1)^N * (1 + g2) / (r - g2)
      PV_2 (영구가치의 현재가치)  = TV_N / (1 + r)^N
      총 내재가치(적정 시가총액)  = PV_1 + PV_2
    """
    if pd.isna(fcf0) or fcf0 <= 0 or pd.isna(r_pct) or r_pct <= g2_pct:
        return {
            "intrinsic_value": np.nan,
            "pv_stage1": np.nan,
            "pv_terminal": np.nan,
            "terminal_fcf_yield_pct": np.nan,
            "fcf_n": np.nan,
        }

    r = float(r_pct) / 100.0
    g1 = float(g1_pct) / 100.0
    g2 = float(g2_pct) / 100.0
    n = max(1, int(n_years))

    pv_stage1 = 0.0
    for t in range(1, n + 1):
        pv_stage1 += fcf0 * ((1.0 + g1) ** t) / ((1.0 + r) ** t)

    fcf_n = fcf0 * ((1.0 + g1) ** n)
    tv_n = fcf_n * (1.0 + g2) / (r - g2)
    pv_terminal = tv_n / ((1.0 + r) ** n)
    intrinsic_val = pv_stage1 + pv_terminal
    terminal_fcf_yield_pct = (r - g2) * 100.0

    return {
        "intrinsic_value": intrinsic_val,
        "pv_stage1": pv_stage1,
        "pv_terminal": pv_terminal,
        "terminal_fcf_yield_pct": terminal_fcf_yield_pct,
        "fcf_n": fcf_n,
    }


def solve_two_stage_implied_growth(
    fcf0: float,
    market_cap: float,
    r_pct: float,
    n_years: int,
    g2_pct: float = 0.0,
) -> float:
    """
    [정밀 2단계 역DCF 내포 기대성장률(g1) 역산]
    현재 시가총액(market_cap)과 정상화 FCF(fcf0)가 주어졌을 때,
    향후 n_years년 동안 매년 몇 %(g1)로 성장하고 이후 g2_pct(%)로 영구 성장해야
    현재 시가총액이 정확히 정당화되는지 이진 탐색(Bisection)으로 정밀 역산합니다.
    """
    if pd.isna(fcf0) or fcf0 <= 0 or pd.isna(market_cap) or market_cap <= 0:
        return np.nan
    if pd.isna(r_pct) or r_pct <= g2_pct:
        return np.nan

    low = -95.0
    high = 300.0

    for _ in range(65):
        mid = (low + high) / 2.0
        res = calc_two_stage_dcf_value(fcf0, r_pct, n_years, mid, g2_pct)
        val = res["intrinsic_value"]
        if pd.isna(val):
            return np.nan
        if val < market_cap:
            low = mid
        else:
            high = mid

    return (low + high) / 2.0


# =====================================================================
# 6. 지표 계산 및 CCR / ROCE 해석 엔진 (최근 지표 + 5개년 평균 지표 동시 산출)
# =====================================================================
def _diagnose_ccr_row(row: pd.Series) -> str:
    """
    CCR 수치 및 현금흐름 구성을 바탕으로 100% 미만/이상 원인을 자동 진단합니다.
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
        if pd.notna(chg_wc) and chg_wc < 0:
            reasons.append("① 운전자본 증가(현금묶임)")
        if da > 0 and capex > da:
            ratio_str = f"{capex_to_da:.0f}%" if pd.notna(capex_to_da) else ""
            reasons.append(f"② CapEx > 감가상각비({ratio_str})")
        elif da == 0 and capex > 0:
            reasons.append("② CapEx 지출 발생")

        if not reasons:
            reasons.append("법인세·이자 현금유출 등 기타")
        return "[100% 미만] " + " / ".join(reasons)

    else:
        if da > capex:
            ratio_str = f"{capex_to_da:.0f}%" if pd.notna(capex_to_da) else ""
            reasons.append(f"② 감가상각비 > CapEx(CapEx/D&A {ratio_str})")
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


def _compute_5y_averages_from_history(
    row: pd.Series,
    ccr_denominator: str,
    deduct_cash_from_ce: bool,
    allow_missing_gpm_as_opm: bool,
) -> Dict[str, Any]:
    """
    행의 `history_json`을 파싱하여 현재 옵션(현금차감 여부, CCR 산식 등)에 맞는 5개년(가용 연도) 평균 지표를 산출합니다.
    만약 `history_json`이 없는 구버전 캐시라면 최신 결산 수치로 폴백합니다.
    """
    hist_str = row.get("history_json", None)
    if hist_str and isinstance(hist_str, str) and len(hist_str) > 10:
        try:
            raw_list = json.loads(hist_str)
            if isinstance(raw_list, list) and len(raw_list) > 0:
                yr_metrics = [
                    _compute_single_year_metrics_dict(
                        rec,
                        ccr_denominator=ccr_denominator,
                        deduct_cash_from_ce=deduct_cash_from_ce,
                        allow_missing_gpm_as_opm=allow_missing_gpm_as_opm,
                    )
                    for rec in raw_list
                ]
                mdf = pd.DataFrame(yr_metrics)
                return {
                    "평균_연도수": len(mdf),
                    "GPM_5Y (%)": mdf["GPM (%)"].mean(skipna=True),
                    "OPM_5Y (%)": mdf["OPM (%)"].mean(skipna=True),
                    "ROCE_5Y (%)": mdf["ROCE (%)"].mean(skipna=True),
                    "EBIT Margin_5Y (%)": mdf["EBIT Margin (%)"].mean(skipna=True),
                    "사용자본회전율_5Y (배)": mdf["사용자본회전율 (배)"].mean(skipna=True),
                    "CCR_5Y (%)": mdf["CCR (%)"].mean(skipna=True),
                    "CapEx/감가상각비_5Y (%)": mdf["CapEx/감가상각비 (%)"].mean(skipna=True),
                    "norm_fcf_5y": mdf["norm_fcf"].mean(skipna=True),
                }
        except Exception:
            pass

    return {
        "평균_연도수": 1,
        "GPM_5Y (%)": row.get("GPM (%)", np.nan),
        "OPM_5Y (%)": row.get("OPM (%)", np.nan),
        "ROCE_5Y (%)": row.get("ROCE (%)", np.nan),
        "EBIT Margin_5Y (%)": row.get("EBIT Margin (%)", np.nan),
        "사용자본회전율_5Y (배)": row.get("사용자본회전율 (배)", np.nan),
        "CCR_5Y (%)": row.get("CCR (%)", np.nan),
        "CapEx/감가상각비_5Y (%)": row.get("CapEx/감가상각비 (%)", np.nan),
        "norm_fcf_5y": row.get("norm_fcf", np.nan),
    }


def compute_quality_metrics(
    raw_df: pd.DataFrame,
    deduct_cash_from_ce: bool = False,
    ccr_denominator: str = "ebit",
    allow_missing_gpm_as_opm: bool = False,
    required_return_pct: float = 10.0,
) -> pd.DataFrame:
    """
    원천 재무제표 DataFrame으로부터 최신 결산 지표 및 5개년 평균 지표, 역DCF 지표를 일괄 계산합니다.
    """
    if raw_df is None or raw_df.empty:
        return pd.DataFrame()

    df = raw_df.copy()

    # 1. 기준 영업이익(EBIT) 설정
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
        min_ce = df["total_assets"] * 0.05
        ce = np.where(ce_cash_deducted > min_ce, ce_cash_deducted, min_ce)
        ce = pd.Series(ce, index=df.index)
    else:
        ce = ce_standard

    ce_valid = ce.where(ce > 0, np.nan)

    df["EBIT Margin (%)"] = (ebit / rev) * 100.0
    df["사용자본회전율 (배)"] = rev / ce_valid
    df["ROCE (%)"] = (ebit / ce_valid) * 100.0

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
        denom = df["net_income"].where(df["net_income"] > 0, np.nan)
        df["CCR (%)"] = (fcf / denom) * 100.0
    elif ccr_denominator == "pretax_ebit":
        denom = ebit.where(ebit > 0, np.nan)
        df["CCR (%)"] = ((fcf + tax_positive) / denom) * 100.0
    elif ccr_denominator == "ocf_only":
        denom = ebit.where(ebit > 0, np.nan)
        df["CCR (%)"] = (df["ocf"] / denom) * 100.0
    else:
        denom = ebit.where(ebit > 0, np.nan)
        df["CCR (%)"] = (fcf / denom) * 100.0

    da_valid = df["da"].where(df["da"] > 0, np.nan)
    df["CapEx/감가상각비 (%)"] = (df["capex"].fillna(0.0) / da_valid) * 100.0
    df["운전자본변동/EBIT (%)"] = (df["chg_wc"] / ebit.where(ebit > 0, np.nan)) * 100.0

    # 5. 이자보상배율 (배)
    int_exp = df["interest_expense"].fillna(0.0)
    icr_numeric = []
    icr_display = []

    for e_val, i_val in zip(ebit, int_exp):
        if pd.isna(e_val):
            icr_numeric.append(np.nan)
            icr_display.append("N/A")
        elif e_val <= 0:
            val = (e_val / i_val) if i_val > 0 else -999.0
            icr_numeric.append(val)
            icr_display.append(f"{val:.1f}배 (적자)")
        else:
            if i_val <= 0 or (e_val / i_val) >= 999.0:
                icr_numeric.append(9999.0)
                icr_display.append("∞ (무차입/순현금)")
            else:
                ratio = e_val / i_val
                icr_numeric.append(ratio)
                icr_display.append(f"{ratio:.1f}배")

    df["이자보상배율 (배)"] = icr_numeric
    df["이자보상배율_표시"] = icr_display

    # 6. 시가총액 단위 변환
    mcap_display = []
    mcap_unit_num = []
    for mkt, mcap in zip(df["market"], df["market_cap"]):
        if pd.isna(mcap) or mcap <= 0:
            mcap_display.append("N/A")
            mcap_unit_num.append(np.nan)
        elif str(mkt).upper() == "KR":
            uk = mcap / 1e8
            mcap_unit_num.append(uk)
            if uk >= 10000:
                mcap_display.append(f"{uk / 10000:.2f}조 원")
            else:
                mcap_display.append(f"{uk:,.0f}억 원")
        else:
            bil = mcap / 1e9
            mcap_unit_num.append(bil)
            mcap_display.append(f"${bil:,.2f}B")

    df["시가총액_표시"] = mcap_display
    df["시가총액_단위수치"] = mcap_unit_num

    # 7. 정상화 FCF (OCF - 감가상각비) 기반 FCF 수익률 및 영구 역DCF 기대성장률
    norm_fcf = df["ocf"] - df["da"].fillna(0.0)
    df["norm_fcf"] = norm_fcf
    mcap_valid = df["market_cap"].where(df["market_cap"] > 0, np.nan)
    df["정상화 FCF 수익률 (%)"] = (norm_fcf / mcap_valid) * 100.0
    df["역DCF 기대성장률 (%)"] = float(required_return_pct) - df["정상화 FCF 수익률 (%)"]

    # 8. 5개년(가용 연도) 평균 지표 일괄 산출
    avg_rows = [
        _compute_5y_averages_from_history(
            row,
            ccr_denominator=ccr_denominator,
            deduct_cash_from_ce=deduct_cash_from_ce,
            allow_missing_gpm_as_opm=allow_missing_gpm_as_opm,
        )
        for _, row in df.iterrows()
    ]
    avg_df = pd.DataFrame(avg_rows, index=df.index)
    for col in avg_df.columns:
        df[col] = avg_df[col]

    df["정상화 FCF 수익률_5Y (%)"] = (df["norm_fcf_5y"] / mcap_valid) * 100.0
    df["역DCF 기대성장률_5Y (%)"] = float(required_return_pct) - df["정상화 FCF 수익률_5Y (%)"]

    # 9. CCR 자동 진단 코멘트 생성
    df["CCR 상태 진단"] = df.apply(_diagnose_ccr_row, axis=1)

    # 10. 시장 세부 거래소 구분
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
# 7. 조건식 평가 엔진 (Filter Rule Evaluator)
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
