#!/usr/bin/env python3
"""Measure which candidate macro-news sources a GitHub runner can reach; save raw bodies.

Diagnostic only: nothing here is published. Usage: python scripts/probe_news_sources.py OUTDIR
"""
import json, sys, time, urllib.parse, urllib.request
from pathlib import Path
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129 Safari/537.36","Accept-Language":"zh-CN,zh;q=0.9"}
Q=urllib.parse.quote
CANDIDATES={
 # official, tier T1
 "mof_news":"https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/",
 "mofcom_news":"https://www.mofcom.gov.cn/xwfb/index.html",
 "mofcom_spokes":"https://www.mofcom.gov.cn/xwfb/xwfyrth/index.html",
 "customs_news":"http://www.customs.gov.cn/customs/xwfb34/302425/index.html",
 "safe_news":"https://www.safe.gov.cn/safe/whxw/index.html",
 "nfra_api":"https://www.nfra.gov.cn/cbircweb/DocInfo/SelectDocByItemIdAndChild?itemId=915&pageSize=18&pageIndex=1",
 "csrc_news":"http://www.csrc.gov.cn/csrc/c100028/common_xq_list.shtml",
 "govcn_yaowen":"https://www.gov.cn/yaowen/liebiao/home.htm",
 "govcn_zhengce":"https://www.gov.cn/zhengce/zuixin/home.htm",
 "pbc_news":"https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html",
 "nbs_rss":"https://www.stats.gov.cn/sj/zxfb/rss.xml",
 "nbs_sjjd":"https://www.stats.gov.cn/sj/sjjd/",
 "ndrc_news":"https://www.ndrc.gov.cn/xwdt/xwfb/",
 # media, tier T2
 "wallstreetcn":"https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit=100",
 "cls_telegraph":"https://www.cls.cn/nodeapi/telegraphList?rn=50",
 "sina_7x24":"https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=50&zhibo_id=152",
 "eastmoney_724":"https://np-weblist.eastmoney.com/comm/web/getFastNewsList?client=web&biz=web_724&fastColumn=102&sortEnd=&pageSize=50&req_trace=1",
 "yicai_news":"https://www.yicai.com/api/ajax/getjuhelist?action=news&page=1&pagesize=25",
 "chinanews_finance_rss":"https://www.chinanews.com.cn/rss/finance.xml",
 "people_finance_rss":"http://www.people.com.cn/rss/finance.xml",
 "xinhua_fortune":"http://www.news.cn/fortune/",
 "jiemian_macro":"https://www.jiemian.com/lists/174.html",
 "caixin_economy":"https://economy.caixin.com/",
 "stcn_kuaixun":"https://www.stcn.com/article/list/kx.html",
 # WeChat collection candidates (zero cost, no persistent crawler)
 "wechat2rss_index":"https://wechat2rss.xlab.app/list/all/",
 "rsshub_wechat_sogou":"https://rsshub.app/wechat/sogou/"+Q("华泰宏观"),
 "sogou_weixin_search":"https://weixin.sogou.com/weixin?type=1&query="+Q("华泰宏观"),
 "sogou_weixin_articles":"https://weixin.sogou.com/weixin?type=2&query="+Q("宏观 CPI PPI 点评"),
 "rsshub_app_root":"https://rsshub.app/",
 "nbs_xwfbh":"https://www.stats.gov.cn/xw/tjxw/tzgg/",
}
WECHAT_TEAMS=["华泰宏观","中金宏观","招商宏观","广发宏观","申万宏源宏观"]

def wechat(out):
    """Zero-cost WeChat test: Sogou article search per broker macro team (last month), resolve one link."""
    import re
    rep={}
    variants=[(t,"https://weixin.sogou.com/weixin?type=2&ie=utf8&query="+Q(t)) for t in WECHAT_TEAMS]
    variants+=[(WECHAT_TEAMS[0]+"|tsn1","https://weixin.sogou.com/weixin?type=2&ie=utf8&tsn=1&query="+Q(WECHAT_TEAMS[0])),
               (WECHAT_TEAMS[0]+"|10月CPI","https://weixin.sogou.com/weixin?type=2&ie=utf8&query="+Q("10月CPI PPI 点评 宏观"))]
    for team,url in variants:
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=25) as r:body=r.read().decode("utf-8","ignore")
            (out/("wechat-"+str(len(rep))+".html")).write_text(body)
            titles=[re.sub("<[^>]+>","",t).strip() for t in re.findall(r"<h3>(.*?)</h3>",body,re.S)]
            accounts=re.findall(r'class="all-time-y2">([^<]+)<',body)
            times=re.findall(r"timeConvert\('(\d+)'\)",body)
            links=re.findall(r'href="(/link\?url=[^"]+)"',body)
            rep[team]={"ok":True,"antispider":"antispider" in body or "seccode" in body,"n":len(titles),"rows":[{"title":t,"account":a,"ts":int(ts)} for t,a,ts in zip(titles,accounts,times)][:10],"links":len(links)}
            if links and team==WECHAT_TEAMS[0]:
                try:
                    with urllib.request.urlopen(urllib.request.Request("https://weixin.sogou.com"+links[0].replace("&amp;","&"),headers={**UA,"Referer":url}),timeout=25) as r2:
                        b2=r2.read().decode("utf-8","ignore");rep[team]["resolve"]={"status":r2.status,"final":r2.geturl()[:120],"has_mp_url":"mp.weixin.qq.com" in b2,"antispider":"antispider" in b2,"bytes":len(b2)}
                except Exception as e:rep[team]["resolve"]={"error":str(e)[:200]}
        except Exception as e:
            rep[team]={"ok":False,"error":str(e)[:200]}
        time.sleep(3)
    (out/"wechat.json").write_text(json.dumps(rep,ensure_ascii=False,indent=1))

def main(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);report={}
    for name,url in CANDIDATES.items():
        t=time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=25) as r:
                body=r.read(250_000);report[name]={"url":url,"ok":True,"status":r.status,"final_url":r.geturl(),"bytes":len(body),"ctype":r.headers.get("Content-Type"),"ms":int((time.time()-t)*1000)}
                (out/f"{name}.body").write_bytes(body)
        except Exception as e:
            report[name]={"url":url,"ok":False,"error":f"{type(e).__name__}: {e}"[:300],"ms":int((time.time()-t)*1000)}
        print(name,report[name].get("status"),report[name].get("bytes"),report[name].get("error",""))
    (out/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
    wechat(out)
if __name__=="__main__":main(sys.argv[1] if len(sys.argv)>1 else "news-probe")
