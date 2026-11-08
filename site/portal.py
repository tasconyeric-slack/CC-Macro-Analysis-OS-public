"""Portal navigation from the public chart inventory; no new observations or judgment."""

CATEGORY_METRICS = {
    "growth": ("cn_ngdp_q", "cn_rgdp_yoy", "cn_retail_sales_yoy", "cn_ip_yoy", "cn_property_sales_area_ytd_yoy", "cn_ind_profit_ytd_yoy"),
    "prices": ("cn_cpi_yoy", "cn_core_cpi_yoy", "cn_ppi_yoy", "cn_ppi_mom", "cn_ppi_producer_yoy", "cn_ppi_consumer_yoy"),
    "pmi": ("cn_pmi_mfg", "cn_pmi_output_price", "cn_pmi_new_orders", "cn_pmi_new_export_orders"),
    "trade": ("cn_exports_usd_yoy", "cn_exports_us_ytd_yoy"),
    "credit": ("cn_m1_yoy", "cn_loans_hh_mlt_ytd", "cn_loans_corp_mlt_ytd", "cn_tsf_stock_yoy", "cn_cgb10y"),
    "fiscal": ("cn_tsf_govbond_flow", "cn_budget_exp_ytd_yoy", "cn_gov_fund_rev_ytd_yoy"),
    "external": ("gl_brent_usd", "gl_copper_usd", "gl_usdcny", "gl_ust10y"),
}


def portal_context(model, v):
    charts = {ch["m"].metric_id: ch for ch in model["charts"]}
    categories = []
    for cid, mids in CATEGORY_METRICS.items():
        available = [charts[mid] for mid in mids if mid in charts and charts[mid]["pts"]]
        releases = [str(ch["latest_release"]) for ch in available if ch["latest_release"]]
        categories.append({
            "id": cid, "title": v.t(f"portal.category.{cid}.title"),
            "kicker": v.t(f"portal.category.{cid}.kicker"),
            "description": v.t(f"portal.category.{cid}.description"),
            "metric_count": len(available), "latest_release": max(releases, default=None),
            "url": f"data-{cid}.html", "metric_ids": [ch["m"].metric_id for ch in available],
        })
    return {"categories": categories, "latest_refresh": model["refreshes"][-1] if model["refreshes"] else None,
            "metric_count": len({mid for c in categories for mid in c["metric_ids"]})}
