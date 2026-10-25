"""Provider access guidance and a bounded, credential-scoped file-access test."""
import base64
import ssl
from urllib.error import HTTPError,URLError
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,HTTPSHandler
import certifi
from providers import ScopedRedirect
from job import Job

GEOTORGET='https://geotorget.lantmateriet.se/'
LM_PRODUCT='https://geotorget.lantmateriet.se/geodataprodukter/markhojdmodell-nedladdning-api'
LM_LASER='https://geotorget.lantmateriet.se/geodataprodukter/laserdata-nedladdning-skog-api'
LM_API_PORTAL='https://apimanager.lantmateriet.se/devportal/'
OT_ACCOUNT='https://portal.opentopography.org/'
OT_KEYS='https://opentopography.org/developers'

GUIDE='''LANTMÄTERIET
1. Sign in to Geotorget with your own account.
2. Confirm that Markhöjdmodell nedladdning API is ordered and approved.
   Laserdata Nedladdning, skog is a separate product permission.
3. Enter the API-approved username and password here. Private-account and
   organization/system-account rules differ; follow your approved order.
4. Search your map, select Lantmäteriet and test access before downloading.

There is no universal key for all providers. Lantmäteriet's API portal can
issue OAuth ConsumerKey/Secret credentials after you subscribe to the API.
Those are not interchangeable with a Basic file-download username/password.
This app tests Basic access to the selected ground-model file. It does not
claim automatic OAuth access to every data download.

OPENTOPOGRAPHY
Create or sign in to your own account and request an API key through its
developer portal. Access and quotas depend on the dataset and account.
Paste that key in the masked OpenTopography field; it is shared with Elevation.

USGS AND OPEN CATALOGS
Supported USGS downloads and public catalog searches need no account.
Local files need no API key. No account or product order is created silently.
Credentials stay in this app session and are not put in projects or reports.'''


def test_lantmateriet_access(selection,credentials,job=None,opener=None):
    job=job or Job();job.check()
    if not credentials or len(credentials)!=2 or not all(credentials):
        raise ValueError('Enter your API-approved Lantmäteriet username and password in Access setup.')
    if selection.get('provider')!='Lantmäteriet' or not selection.get('assets'):
        raise ValueError('Search the map and select a Lantmäteriet ground-model result first.')
    url=selection['assets'][0]['url'];parts=urlsplit(url)
    if parts.scheme!='https' or parts.hostname not in {'dl1.lantmateriet.se','dl2.lantmateriet.se'} or parts.port not in (None,443) or parts.username or parts.password or parts.fragment:
        raise ValueError('Unexpected Lantmäteriet file address; credentials were not sent.')
    authorization='Basic '+base64.b64encode((credentials[0]+':'+credentials[1]).encode()).decode()
    if opener is None:
        opener=build_opener(HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())),ScopedRedirect()).open
    job.update(10,'Testing provider access','Lantmäteriet selected ground-model file')
    for method in ('HEAD','GET'):
        job.check()
        headers={'Authorization':authorization,'User-Agent':'TF3-Heightmap-Studio/0.11'}
        if method=='GET':headers['Range']='bytes=0-3'
        try:
            with opener(Request(url,method=method,headers=headers),timeout=15) as response:
                job.check();status=getattr(response,'status',200)
                content_type=response.headers.get('Content-Type','').lower()
                if status not in (200,206):raise ValueError('The data server did not accept the access test.')
                if method=='HEAD' and ('tiff' in content_type or 'octet-stream' in content_type):
                    return {'ok':True,'provider':'Lantmäteriet','message':'API access accepted for the selected ground-model file.'}
                if method=='GET':
                    magic=response.read(4);job.check()
                    if magic not in (b'II*\x00',b'MM\x00*',b'II+\x00',b'MM\x00+'):
                        raise ValueError('The server returned a login page or other non-TIFF response. Check API credentials and product approval.')
                    return {'ok':True,'provider':'Lantmäteriet','message':'API access accepted; the selected file has a TIFF header.'}
        except HTTPError as exc:
            code=exc.code;exc.close()
            job.check()
            if method=='HEAD' and code in (405,501):continue
            if code in (401,403):return {'ok':False,'provider':'Lantmäteriet','message':'Access denied. Check the API-approved credentials and permission for Markhöjdmodell nedladdning API.'}
            raise ValueError(f'Lantmäteriet access test failed (HTTP {code}). Try again later.') from None
        except (URLError,TimeoutError):
            raise ValueError('Lantmäteriet could not be reached. Check the connection and try again.') from None
    raise ValueError('Provider access could not be confirmed.')
