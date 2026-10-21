import unittest,tempfile,sqlite3
from pathlib import Path
from unittest.mock import patch,Mock
import news_push as n
class Tests(unittest.TestCase):
 def test_classification(self):
  self.assertEqual(n.classify('险资加强养老医疗投资'),'保险')
  self.assertEqual(n.classify('Insurers expand Medicare coverage'),'保险')
  self.assertIsNone(n.classify('播放器发布新版本'))
 def test_baseline_failure_retry_and_dedup(self):
  with tempfile.TemporaryDirectory() as d,patch.object(n,'ROOT',Path(d)),patch.object(n,'SOURCES',[n.SOURCES[1]]):
   a={'url':'https://example.org/1','title':'保险市场动态','source':'中新经纬','category':'保险'}
   status={'source':'中新经纬','ok':True}
   with patch.object(n,'fetch',return_value=([a],status)),patch.object(n.requests,'post') as post:
    n.run();post.assert_not_called()
   a2={**a,'url':'https://example.org/2','title':'保险新规发布'}
   with patch.object(n,'fetch',return_value=([a,a2],status)),patch.dict(n.os.environ,{'SERVERCHAN_SENDKEY':'SCTtest'}):
    with patch.object(n.requests,'post',return_value=Mock(status_code=200,json=lambda:{'code':1})):
     with self.assertRaises(RuntimeError):n.run()
    db=sqlite3.connect(Path(d)/'state.sqlite3')
    self.assertEqual(db.execute('select count(*) from articles where sent=0').fetchone()[0],1)
    with patch.object(n.requests,'post',return_value=Mock(status_code=200,json=lambda:{'code':0})) as post:
     n.run();self.assertEqual(post.call_count,1)
     n.run();self.assertEqual(post.call_count,1)
    db.close()
if __name__=='__main__':unittest.main()
