'''Cinemator worker

Regulary get new films and torrent links from cinemate.cc.

Films DB structure:
films: name, href, quality, categories, date, countries, discription
       IMDB_rate, IMDB_count, Kinopoisk_rate, Kinopoisk_count, 
       torrent_urls, added_datetime, to_download, downloaded, to_delete, deleted

'''

# from urllib.request import Request, urlopen
import os
from bs4 import BeautifulSoup
import requests
import pymongo
from pymongo import MongoClient
from datetime import datetime
from pprint import pprint
import locale

### Settings
locale.setlocale(locale.LC_ALL, "")
# locale.setlocale(locale.LC_ALL, 'ru_RU.UTF-8')
login_url = 'http://cinemate.cc/login/'
top_url = 'http://cinemate.cc'
headers = {'User-Agent': 'Mozilla/5.0'}
username = os.environ.get('CINEMATE_USERNAME')
password = os.environ.get('CINEMATE_PASSWORD')
# DB
db_URI = 'mongodb://localhost:27017/'
db_name = 'autocinemator'

### Procedures
# Connect to mongo and return db object
def get_db(URI):
    client = MongoClient(URI)
    db = client[db_name]
    return db

# Login in to login_url (using client_session and HTML headers) and return post output (as BeautifulSoup)
def loginin(url, client_session):
    output = client_session.get(url, headers=headers)   # to get cookies or form with 'cm_token'
    clientcokies = client_session.cookies.get_dict(domain='cinemate.cc')

    # Get cm_token from cinemate.cc
    if 'cm_token' in clientcokies:
        # Founded in cookies
        csrftoken = clientcokies['cm_token']
        print('founded :', csrftoken)
    else:
        # Get token from form
        bsObj = BeautifulSoup(output.content, 'html.parser')
        loginform = bsObj.find(id='login_form')
        csrfmiddlewaretoken = loginform.find('', {'name': 'csrfmiddlewaretoken'})
        csrftoken = csrfmiddlewaretoken.attrs['value']

    headers['Referer'] = url
    params = {'username': username,
              'password': password,
              'csrfmiddlewaretoken': csrftoken}
    print(params)
    # Login in
    output = client_session.post(url, headers=headers, data=params)
    return output

# Get new films + href with current year production and good quality.
# top_category = 'top_sites_24' or 'top_sites_7'
def get_new_films(db, url, top_category):
    filmslist =[]
    films_in_db = db.films
    current_year = datetime.utcnow().year

    r = client.get(url, headers=headers)
    bsObj = BeautifulSoup(r.content, 'html.parser') 
    filmdivs_list = bsObj.find('',{'id': top_category}).find_all('',{'class': 'row delimiter'})

    for filmdiv in filmdivs_list:
        fullname = str(filmdiv.div.a.attrs['title'])
        name = fullname[:-7]    # without year
        href = top_url + str(filmdiv.div.a.attrs['href'])
        newfilm = {'name': name,
                   'href': href}
        
        # Get list of film quality: Rip, HD, DVD, Экранка
        qualitylist = []
        for item in filmdiv.div.findNext('div').find_all('a'):
            qualitylist += item
        print(qualitylist)

        # Get highness quality
        if 'Rip' or 'HD' in qualitylist:
            quality = 'HD' if 'HD' in qualitylist else 'Rip'
            newfilm['quality'] = quality

        # Don't add in list if low quality
        if not ('Rip' or 'HD' in qualitylist): continue

        # Don't add if old year
        filmyear = int(fullname[-5:-1])
        if not filmyear >= (current_year - 1): continue
        
        # Don't add if persist in DB
        if films_in_db.find_one({'name': name}): continue

        print(name, filmyear)
        filmslist.append(newfilm)
    return filmslist


# Get film's info
def get_film_info(film):
    r = client.get(film['href'], headers=headers)
    bsObj = BeautifulSoup(r.content, 'html.parser') 
    film_detail =  bsObj.find('',{'class': 'object_detail'})
    
    film['discription'] = film_detail.find('',{'class': 'description'}).get_text().strip()
    
    categories = []
    for item in film_detail.find('',{'class': 'main'}).find_all('a',{'itemprop': 'genre'}):
        categories += item
    film['categories'] = categories

    ratings = film_detail.find('',{'id': 'ratings'}).li
    film['IMDB_rate'] = float(ratings.span.a.get_text())
    film['IMDB_count'] = int(ratings.small.get_text()[1:-1])
    film['Kinopoisk_rate'] = float(ratings.find_next_sibling('li').span.a.get_text())
    film['Kinopoisk_count'] = int(ratings.find_next_sibling('li').small.get_text()[1:-1])

    film_date = film_detail.find('',{'id': 'releases'}).li.small.get_text()[4:]
    print(film_date)
    # film['date'] = datetime.strptime(film_date, '%d %B %Y')

    # country

# Main
client = requests.session()
r = loginin(login_url, client)

db = get_db(db_URI)

# New films list to add in DB
newfilms = get_new_films(db, top_url, 'top_sites_24')
pprint(newfilms)

get_film_info(newfilms[0])
pprint(newfilms[0])

# films: name, href, quality, categories, date, countries, discription
# IMDB_rate, IMDB_count, Kinopoisk_rate, Kinopoisk_count, 
# torrent_urls, added_datetime, to_download, downloaded, to_delete, deleted
films = db.films
'''newfilm = {'name': 'film1', 
           'added_datetime': datetime.utcnow()}
films.insert_one(newfilm)

films.insert_many(newfilms)
'''
for film in films.find():
    pprint(film)
