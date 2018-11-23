# from urllib.request import Request, urlopen
import os
from bs4 import BeautifulSoup
import requests

# settings
login_url = 'http://cinemate.cc/login/'
cinemate_url = 'http://cinemate.cc/'
headers = {'User-Agent': 'Mozilla/5.0'}
username = os.environ.get('CINEMATE_USERNAME')
password = os.environ.get('CINEMATE_PASSWORD')

client = requests.session()
r = client.get(login_url, headers=headers)

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

headers['Referer'] = login_url
params = {'username': username, 'password': password, 'csrfmiddlewaretoken': csrftoken}

print(params)
r = client.post(login_url, headers=headers, data=params)
bsObj = BeautifulSoup(r.content) 
print(bsObj.find('',{'class':'username'}))
print(client.cookies.get_dict(domain='cinemate.cc'))

# print(r.text)

r = client.get(cinemate_url, headers=headers)
bsObj = BeautifulSoup(r.content) 
print(bsObj.find('',{'class':'username'}))

# print(r.text)

