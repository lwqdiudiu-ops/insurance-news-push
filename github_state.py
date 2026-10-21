"""将去重库保存在独立分支；恢复失败则停止，不静默重建基线。"""
import base64,json,os,sys
from pathlib import Path
import requests
BRANCH='news-push-state'
PATH='data/state.sqlite3'
ROOT=Path(__file__).resolve().parent

def main(mode):
 if mode=='save' and not (ROOT/'state.sqlite3').exists():
  print('本轮未生成去重库，无需保存');return
 repo=os.environ['GITHUB_REPOSITORY']
 api=f'https://api.github.com/repos/{repo}'
 s=requests.Session()
 s.headers.update({'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
 def call(method,path,allowed=(200,),**kwargs):
  r=s.request(method,api+path,timeout=30,**kwargs)
  if r.status_code not in allowed:raise RuntimeError(f'GitHub 状态存取失败 HTTP {r.status_code}，检查 Actions contents:write 权限')
  return r
 ref=call('GET','/git/ref/heads/'+BRANCH,allowed=(200,404))
 if ref.status_code==404:
  if mode=='restore':
   (ROOT/'state-meta.json').write_text(json.dumps({'sha':None,'new_branch':True}));print('首次部署，将建立资讯基线');return
  default=os.environ.get('DEFAULT_BRANCH','main')
  original=call('GET','/git/ref/heads/'+default).json()
  call('POST','/git/refs',allowed=(201,),json={'ref':'refs/heads/'+BRANCH,'sha':original['object']['sha']})
 r=call('GET','/contents/'+PATH,allowed=(200,404),params={'ref':BRANCH})
 if mode=='restore':
  if r.status_code==404:raise RuntimeError('状态分支存在但去重库缺失，请人工检查，避免重置已发送记录')
  data=r.json();blob=base64.b64decode(data['content'])
  if not blob.startswith(b'SQLite format 3\x00'):raise RuntimeError('去重库格式错误')
  (ROOT/'state.sqlite3').write_bytes(blob)
  (ROOT/'state-meta.json').write_text(json.dumps({'sha':data['sha']}));print('已恢复持久化去重库')
 else:
  f=ROOT/'state.sqlite3'
  if not f.exists():print('本轮未生成去重库，无需保存');return
  payload={'message':'Update news deduplication state','content':base64.b64encode(f.read_bytes()).decode(),'branch':BRANCH}
  if r.status_code==200:payload['sha']=r.json()['sha']
  call('PUT','/contents/'+PATH,allowed=(200,201),json=payload)
  print('去重库已保存至独立状态分支')
if __name__=='__main__':
 try:main(sys.argv[1])
 except Exception as e:print(type(e).__name__+': '+str(e));sys.exit(1)
