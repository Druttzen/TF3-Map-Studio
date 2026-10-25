import base64,io,json,sys,threading
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import Mock
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from data_access import test_lantmateriet_access as check_access
from job import Job,Cancelled


ROW={'provider':'Lantmäteriet','assets':[{'url':'https://dl1.lantmateriet.se/ground.tif'}]}
class Response(io.BytesIO):
 status=200
 headers={'Content-Type':'image/tiff'}

def test_access_uses_scoped_basic_credentials_and_does_not_return_secrets():
 opener=Mock(return_value=Response(b''));result=check_access(ROW,('api-user','private-password'),opener=opener)
 request=opener.call_args.args[0]
 assert request.get_method()=='HEAD'
 assert request.get_header('Authorization')=='Basic '+base64.b64encode(b'api-user:private-password').decode()
 assert result['ok'] and 'private-password' not in json.dumps(result) and 'api-user' not in json.dumps(result)

def test_head_fallback_reads_only_tiff_header():
 response=Response(b'II*\x00'+b'x'*100);read=Mock(wraps=response.read);response.read=read
 opener=Mock(side_effect=[HTTPError(ROW['assets'][0]['url'],405,'No HEAD',{},None),response])
 assert check_access(ROW,('u','p'),opener=opener)['ok']
 request=opener.call_args.args[0];assert request.get_method()=='GET' and request.get_header('Range')=='bytes=0-3'
 read.assert_called_once_with(4)

@pytest.mark.parametrize('code',[401,403])
def test_denied_access_is_actionable(code):
 opener=Mock(side_effect=HTTPError(ROW['assets'][0]['url'],code,'Denied',{},None))
 result=check_access(ROW,('u','p'),opener=opener)
 assert not result['ok'] and 'permission' in result['message']

def test_unexpected_host_never_receives_credentials():
 opener=Mock()
 with pytest.raises(ValueError,match='not sent'):check_access({'provider':'Lantmäteriet','assets':[{'url':'https://other.example.org/ground.tif'}]},('u','p'),opener=opener)
 opener.assert_not_called()

def test_html_response_is_not_mistaken_for_verified_access():
 response=Response(b'<html>login</html>');response.headers={'Content-Type':'text/html'}
 opener=Mock(side_effect=[response,Response(b'<html>login</html>')])
 with pytest.raises(ValueError,match='non-TIFF'):check_access(ROW,('u','p'),opener=opener)

def test_cancelled_access_sends_nothing():
 event=threading.Event();event.set();opener=Mock()
 with pytest.raises(Cancelled):check_access(ROW,('u','p'),Job(cancel=event),opener)
 opener.assert_not_called()
