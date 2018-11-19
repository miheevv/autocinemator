# from urllib.request import Request, urlopen
from bs4 import BeautifulSoup
import requests

loginurl = 'http://cinemate.cc/login/'
headers = {'User-Agent': 'Mozilla/5.0'}

client = requests.session()
r = client.get(loginurl, headers=headers)

cinematecokies = client.cookies.get_dict(domain='cinemate.cc')

# get cm_token from cinemate.cc
if 'cm_token' in cinematecokies:
    # founded in cookies
    csrftoken = cinematecokies['cm_token']
    print('founded :', csrftoken)
else:
    # get token from form
    bsObj = BeautifulSoup(r.content) 
    loginform = bsObj.find(id='login_form')
    csrfmiddlewaretoken = loginform.find('', {'name': 'csrfmiddlewaretoken'})
    csrftoken = csrfmiddlewaretoken.attrs['value']

headers['Referer'] = loginurl
params = {'username': 'miheevv', 'password': '123', 'csrfmiddlewaretoken': csrftoken}

r = client.post(loginurl, headers=headers, data=params)
bsObj = BeautifulSoup(r.content) 
print(bsObj.title)
# print(r.text)
