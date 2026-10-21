#!/usr/bin/env python3
"""个人行业资讯采集器。首次运行建立基线；仅在推送被服务商接受后标记已发送。"""
import argparse, concurrent.futures, datetime as dt, fcntl, html, json, os
from pathlib import Path
import re, sqlite3, time
from urllib.parse import urljoin, urlsplit, urlunsplit
import requests
from bs4 import BeautifulSoup
ROOT = Path(__file__).resolve().parent
TZ = dt.timezone(dt.timedelta(hours=8))
SOURCES = [
 ('Fierce Healthcare','https://www.fiercehealthcare.com/',r'^/(payers|providers|health-tech|finance|regulatory)/[^/]+'),
 ('中新经纬','https://www.jwview.com/jr.html',r'/jingwei/html/.*\.shtml$'),
 ('上海证券报','https://www.cnstock.com/channel/10120',r'/commonDetail/\d+'),
 ('雷递网','https://www.leinews.com/',r'/n[^/]+/detail.html'),
 ('亿欧网','https://www.iyiou.com/',r'/analysis/\d+|/news/\d+'),
 ('证券时报','https://www.stcn.com/article/list/finance.html',r'/article/detail/\d+\.html')]
KEYS = {
 '保险': '保险 保费 险企 险资 寿险 财险 再保险 赔付 核保 银保 保险资管 中国平安 中国人寿 新华保险 中国太保 中国人保 泰康 太平 insurance insurer insurers payer payers medicaid medicare aca'.split(),
 '养老': '养老 养老金 年金 长护 老龄 aging retirement pension senior'.split(),
 '医疗': '医疗 医保 医院 医药 健康 healthcare hospital pharmacy patient'.split(),
 '金融': '金融 银行 证券 基金 利率 央行 监管总局 资管 信贷 finance banking bank securities'.split()}
def classify(text):
 text=text.lower()
 for group, words in KEYS.items():
  if any((bool(re.search(r'\b'+re.escape(w)+r'\b',text)) if w.isascii() else w in text) for w in words): return group
 return None

def fetch(source):
 name,url,pattern=source
 s=requests.Session();s.headers['User-Agent']='IndustryNewsMonitor/1.0 (personal news digest)'
 def get(u):
  r=s.get(u,timeout=(10,25));r.raise_for_status();r.encoding=r.apparent_encoding;return r.text
 try:
  if name=='雷递网':
   company=get(url+'Common/XYUIAjax.aspx?method=GetCompanyInfo')
   uid=re.search(r'"U_ID":(\d+)',company).group(1)
   r=s.post(url+'Common/YiAPP.ashx?YiAPP_Method=uNews.PC_SearchNewsInfoList&YiAPP_Action=YiAPP.APP.SHOP&YiAPP_SIKW=true',data={'ShopUser':uid,'ColumnCode':'','page':1,'rows':100},timeout=(10,25));r.raise_for_status()
   data=r.json()
   if int(data.get('status',0))!=200: raise ValueError('动态列表接口失败')
   soup=BeautifulSoup(''.join('<a href="/n'+html.escape(str(x['NewsCode']))+'/detail.html">'+html.escape(x['NewsTitle'])+'</a>' for x in data['data']['data']),'html.parser')
  else: soup=BeautifulSoup(get(url),'html.parser')
  found={}
  for a in soup.select('a[href]'):
   link=urljoin(url,a['href']);parts=urlsplit(link)
   if parts.hostname!=urlsplit(url).hostname or not re.search(pattern,parts.path): continue
   heading=a.select_one('h1,h2,h3,h4,h5')
   title=' '.join((heading or a).get_text(' ',strip=True).split())
   if not 8<=len(title)<=180: continue
   link=urlunsplit((parts.scheme,parts.netloc,parts.path,'',''))
   if link not in found: found[link]={'title':title,'url':link,'source':name,'category':classify(title)}
  if not found: raise ValueError('未解析到文章：访问验证或页面结构变化')
  return list(found.values()),{'source':name,'ok':True,'articles':len(found),'matched':sum(bool(x['category']) for x in found.values())}
 except Exception as e:
  return [],{'source':name,'ok':False,'error':type(e).__name__+': '+str(e)[:160]}

def digest(items,status):
 now=dt.datetime.now(TZ).strftime('%Y-%m-%d %H:%M')
 out=[f'# 行业资讯 · {now}', '保险优先；以下为新发现链接，发现时间不代表发布时间。']
 for category in KEYS:
  rows=[x for x in items if x['category']==category]
  if rows:
   out+=['',f'## {category}']
   for x in rows: out += [f"- [{x['title'].replace('[','（').replace(']','）')}]({x['url']}) · {x['source']}"]
 failed=[x['source'] for x in status if not x['ok']]
 if failed: out+=['','采集异常：'+ '、'.join(failed)+'（本批未覆盖这些来源）。']
 return '\n'.join(out)

def run(preview=False):
 now=dt.datetime.now(TZ).isoformat()
 results=list(concurrent.futures.ThreadPoolExecutor(max_workers=6).map(fetch,SOURCES))
 articles=[a for rows,_ in results for a in rows];status=[s for _,s in results]
 (ROOT/'status.json').write_text(json.dumps({'checked_at':now,'sources':status},ensure_ascii=False,indent=2))
 if not any(x['ok'] for x in status):raise RuntimeError('所有来源采集失败')
 if preview:
  items=[x for x in articles if x['category']];body=digest(items,status)
  (ROOT/'preview.md').write_text(body);print(json.dumps(status,ensure_ascii=False,indent=2));return
 db=sqlite3.connect(ROOT/'state.sqlite3')
 try:
  db.execute('CREATE TABLE IF NOT EXISTS articles (url TEXT PRIMARY KEY,title TEXT,source TEXT,category TEXT,first_seen TEXT,sent INTEGER DEFAULT 0)')
  db.execute('CREATE TABLE IF NOT EXISTS sources (name TEXT PRIMARY KEY)')
  for rows,st in results:
   if not st['ok']:continue
   baseline=db.execute('SELECT 1 FROM sources WHERE name=?',(st['source'],)).fetchone() is None
   for a in rows:
    db.execute('INSERT OR IGNORE INTO articles VALUES (?,?,?,?,?,?)',(a['url'],a['title'],a['source'],a['category'],now,int(baseline or not a['category'])))
   db.execute('INSERT OR IGNORE INTO sources VALUES (?)',(st['source'],))
  db.commit()
  pending=[dict(zip(['url','title','source','category'],r)) for r in db.execute("SELECT url,title,source,category FROM articles WHERE sent=0 ORDER BY CASE category WHEN '保险' THEN 0 WHEN '养老' THEN 1 WHEN '医疗' THEN 2 ELSE 3 END, first_seen LIMIT 30")]
  # 相同标题的转载合并；不同标题报道保留，避免误删。
  unique={}
  for a in pending:unique.setdefault(re.sub(r'\W','',a['title']).lower(),a)
  items=list(unique.values());items.sort(key=lambda a:list(KEYS).index(a['category']))
  body=digest(items,status)
  (ROOT/'latest.md').write_text(body)
  if items:
   key=os.environ.get('SERVERCHAN_SENDKEY','').strip()
   env=ROOT/'.env'
   if not key and env.exists():
    for line in env.read_text().splitlines():
     if line.startswith('SERVERCHAN_SENDKEY='):key=line.split('=',1)[1].strip()
   if not re.fullmatch(r'SCT[A-Za-z0-9]+',key):raise RuntimeError('请在 .env 配置 Server酱 Turbo 的 SCT SendKey；待推送资讯已保留')
   r=requests.post(f'https://sctapi.ftqq.com/{key}.send',data={'title':f'保险行业资讯｜新增{len(items)}条','desp':body},timeout=(10,30))
   # 不输出响应异常 URL，避免泄露 SendKey。
   if r.status_code!=200:raise RuntimeError(f'推送服务 HTTP {r.status_code}；未标记发送')
   response=r.json()
   if response.get('code')!=0:raise RuntimeError('推送服务未接受消息，请检查账号通道与额度；未标记发送')
   (ROOT/'delivery.json').write_text(json.dumps({'accepted_at':dt.datetime.now(TZ).isoformat(),'items':len(items),'status':'accepted_by_serverchan'},ensure_ascii=False,indent=2))
   db.executemany('UPDATE articles SET sent=1 WHERE url=?',[(a['url'],) for a in pending]);db.commit()
  print(now, '采集',len(articles),'新增待推送',len(items),'失败来源',sum(not x['ok'] for x in status),flush=True)
 finally:
  db.close()

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--preview',action='store_true');p.add_argument('--daemon',action='store_true');args=p.parse_args()
 lock=(ROOT/'run.lock').open('w')
 try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:raise SystemExit('已有实例运行')
 while True:
  try:run(args.preview)
  except Exception as e:
   print(dt.datetime.now(TZ).isoformat(),type(e).__name__,'本轮失败，请检查配置、联网和推送通道',flush=True)
   if not args.daemon:raise SystemExit(1)
  if not args.daemon:break
  deadline=time.time()+7200
  print('下次检查时间：',dt.datetime.fromtimestamp(deadline,TZ).strftime('%Y-%m-%d %H:%M:%S'),'（休眠后唤醒将补查）',flush=True)
  while time.time()<deadline:
   time.sleep(min(30,max(0,deadline-time.time())))
