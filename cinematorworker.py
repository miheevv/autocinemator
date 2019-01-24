'''Cinemator worker

Regulary get new films and torrent links from cinemate.cc.

Films DB structure:
films: name, href, quality, categories, date, countries, discription, img
       IMDB_rate, IMDB_count, Kinopoisk_rate, Kinopoisk_count, 
       added_datetime, torrent_urls, bad_torrent, 
       filmfolder (by default - 'films'), to_download, downloaded, to_delete (to delete on server), deleted (don't download in future again)

'''

# from urllib.request import Request, urlopen
import os
from bs4 import BeautifulSoup
import requests
import pymongo
from pymongo import MongoClient
import datetime
from pprint import pprint
import locale
import re

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
    current_year = datetime.datetime.utcnow().year

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

        filmslist.append(newfilm)
    return filmslist

# Convert string in format '%day %month_str %year' into datetime
def datestr_to_date(datestr):
    month_to_int = {
        'января': 1,
        'февраля': 2,
        'марта': 3,
        'апреля': 4,
        'мая': 5,
        'июня': 6,
        'июля': 7,
        'августа': 8,
        'сентября': 9,
        'октября': 10,
        'ноября': 11,
        'декабря': 12
    }
    day = int(re.search(r'^\d+', datestr).group(0))
    month_str = re.search(r'\s\w+\s', datestr).group(0).strip().lower()
    year = int (re.search(r'\d+$', datestr).group(0))

    try:
        month = month_to_int[month_str]
    except KeyError as e:
        raise ValueError('Undefined unit: {}'.format(e.args[0]))
    return datetime.datetime(year, month, day)

# Get film's info
def get_film_info(film):
    r = client.get(film['href'], headers=headers)
    bsObj = BeautifulSoup(r.content, 'html.parser') 
    film_detail =  bsObj.find('',{'class': 'object_detail'})
    
    # Description
    film['discription'] = film_detail.find('',{'class': 'description'}).get_text().strip()
    
    # Categories
    categories = []
    for item in film_detail.find('',{'class': 'main'}).find_all('a',{'itemprop': 'genre'}):
        categories += item
    film['categories'] = categories
    
    # Countries
    countries = []
    for item in film_detail.find('',{'class': 'main'}).find(text='|').parent.find_next_siblings('a'):
        countries += item
    film['countries'] = countries

    # Rate
    ratings = film_detail.find('',{'id': 'ratings'}).li
    film['IMDB_rate'] = float(ratings.span.a.get_text())
    film['IMDB_count'] = int(ratings.small.get_text()[1:-1])
    film['Kinopoisk_rate'] = float(ratings.find_next_sibling('li').span.a.get_text())
    film['Kinopoisk_count'] = int(ratings.find_next_sibling('li').small.get_text()[1:-1])

    # Date
    try:
        film_date = film_detail.find('',{'id': 'releases'}).li.small.get_text().strip()[4:]
        film['date'] = datestr_to_date(film_date)
    except:
        film['date'] = None

    # Img
    film['img'] = 'http:' + bsObj.find('',{'class': 'posterbig'}).img.attrs['src']

# Filter new films and return list to add (with autoset filmfolders, etc. params)
def filter_films(newfilms, films):
    notfiltred_films = []
    for item in newfilms:
        removeflag = None
        if ('IMDB_count' not in item) or (item['IMDB_count'] < 5000) or \
           ('IMDB_rate' not in item) or (item['IMDB_rate'] < 5.5) or \
           ('Kinopoisk_count' not in item) or (item['Kinopoisk_count'] < 1000) or \
           ('Kinopoisk_rate' not in item) or (item['Kinopoisk_rate'] < 5.0):
            removeflag = 1
        
        # If already in DB - don't add in list
        if films.find_one({'name': item['name'], 'date' : item['date']}):
            removeflag = 1
        
        if removeflag is None:
            notfiltred_films.append(item)
    
    return notfiltred_films

# Main
client = requests.session()
r = loginin(login_url, client)

db = get_db(db_URI)

# New films list to add in DB
newfilms = get_new_films(db, top_url, 'top_sites_24')

# Get film's info for every film
for item in newfilms:
    get_film_info(item)

# Get films from DB
films = db.films

newfilms = filter_films(newfilms, films)

pprint(newfilms)


# get torrent_urls
# if bad torrent - get other url

# add to db

# - next - rename cinematorworker.py to cinematorparser.py (worker - on server to add torrent url for download, and delete old films)  
# - cinematorgui.py - list new films, mark to download and delete.

films = db.films
'''newfilm = {'name': 'film1', 
           'added_datetime': datetime.utcnow()}
films.insert_one(newfilm)

films.insert_many(newfilms)
'''
for film in films.find():
    pprint(film)
