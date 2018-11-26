# from urllib.request import Request, urlopen
import os
from bs4 import BeautifulSoup
import requests
import pymongo
from pymongo import MongoClient
from datetime import datetime
from pprint import pprint

# settings
login_url = 'http://cinemate.cc/login/'
top_url = 'http://cinemate.cc/#top_sites_7'
headers = {'User-Agent': 'Mozilla/5.0'}
username = os.environ.get('CINEMATE_USERNAME')
password = os.environ.get('CINEMATE_PASSWORD')
# DB
db_URI = 'mongodb://localhost:27017/'
db_name = 'autocinemator'

# Get db
def get_db():
    client = MongoClient(db_URI)
    db = client[db_name]
    return db


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
    bsObj = BeautifulSoup(r.content, "html.parser") 
    loginform = bsObj.find(id='login_form')
    csrfmiddlewaretoken = loginform.find('', {'name': 'csrfmiddlewaretoken'})
    csrftoken = csrfmiddlewaretoken.attrs['value']

headers['Referer'] = login_url
params = {'username': username, 'password': password, 'csrfmiddlewaretoken': csrftoken}

print(params)
r = client.post(login_url, headers=headers, data=params)
'''
bsObj = BeautifulSoup(r.content, "html.parser") 
print(bsObj.find('',{'class': 'username'}))
print(client.cookies.get_dict(domain='cinemate.cc'))
# print(r.text)
'''

r = client.get(top_url, headers=headers)
bsObj = BeautifulSoup(r.content, "html.parser") 
filmdivs_list = bsObj.find('',{'id': 'top_sites_24'}).find_all('',{'class': 'row delimiter'})
for filmdiv in filmdivs_list:
    newfilms = {"name": filmdiv.div.a.attrs['title'],
                "href": filmdiv.div.a.attrs['href']}
    print(newfilms)
#                "quality": filmdiv.next_siblings.a.get_text()}
# print(r.text)
# pprint(newfilms)

db = get_db()
films = db.films
'''newfilm = {"name": "film1", 
           "added_datetime": datetime.utcnow()}
films.insert_one(newfilm)
'''
for film in films.find():
    pprint(film)