'''Cinemator worker

Regulary get new films and torrent links from cinemate.cc.

Films DB structure:
films: name, href, quality, categories, date, countries, discription, img
       IMDB_rate, IMDB_count, Kinopoisk_rate, Kinopoisk_count, 
       added_datetime, torrent_urls, bad_torrent, new (resently added)
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
    # films_in_db = db.films
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
        if ('Rip' in qualitylist) or ('HD' in qualitylist):
            quality = 'HD' if 'HD' in qualitylist else 'Rip'
            newfilm['quality'] = quality

        # Don't add in list if low quality
        if not (('Rip' in qualitylist) or ('HD' in qualitylist)): continue

        # Don't add if old year
        filmyear = int(fullname[-5:-1])
        if not filmyear >= (current_year - 1): continue
        
        # Don't add if persist in DB
        # if films_in_db.find_one({'name': name}): continue

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
           ('IMDB_rate' not in item) or (item['IMDB_rate'] < 6) or \
           ('Kinopoisk_count' not in item) or (item['Kinopoisk_count'] < 1000) or \
           ('Kinopoisk_rate' not in item) or (item['Kinopoisk_rate'] < 5.0):
            removeflag = 1
        
        # If already in DB - don't add in list
        if films.find_one({'name': item['name'], 'date' : item['date']}):
            removeflag = 1
        
        if removeflag is None:
            notfiltred_films.append(item)
    
    return notfiltred_films

# Return trackers list from film
def get_trackers(film, type):
    trackers= []
    r = client.get(film['href']+'links/#tabs', headers=headers)
    bsObj = BeautifulSoup(r.content, 'html.parser') 
    trackers_list = bsObj.find('',{'id': 'site-list'})

    try:
        trackersHD_list = trackers_list.find('',{'id': type}).parent
    except:
        return None

    # Get lang type
    for trackersdiv in trackersHD_list.find_all('',{'class': 'row delimiter'}):
        langs = []
        langs_type ={
            'Профессиональное (полное дублирование)': 'ППД',
            'Оригинальная дорожка': 'Оригинальная'
        }
        for langdiv in trackersdiv.find_all('',{'class': 'blue_span_float'}):
            try:
                langs.append(langs_type[str(langdiv.attrs['title'])])
            except:
                langs.append(str(langdiv.attrs['title']))

        newtracker = {'langs': langs}
        
        # Get tracker type
        try:
            newtracker['tracker'] = trackersdiv.find('div', attrs={'class': 'trackert'}).text.strip()
        except:
            newtracker['tracker'] = None

        # Get size
        try:
            size_text = trackersdiv.find('div', attrs={'style': 'height:1.2em; overflow: hidden;'}).text.strip()
            newtracker['size'] = float(size_text[:size_text.find('.')+2])
        except:
            newtracker['size'] = 0

        try:
            newtracker['sid_count'] = int(trackersdiv.find('div', {'title': 'Число раздающих'}).text.strip())
        except:
            newtracker['sid_count'] = 0

        newtracker['href'] = top_url + str(trackersdiv.find('a', {'class': 'icon_t download-link'}).attrs['href'])

        newtracker['type'] = type

        trackers.append(newtracker)
    
    return trackers

def login_in_rutracker(url):
    params = {'login_username': username,
              'login_password': password}
    print(params)
    # Login in
    output = client.post(url, headers=headers, data=params)
    return output

# Get external (RUTOR, RUTRACKER, KINOZAL) torrent's URL
def get_ext_torrent(url, tracker_type):
    if tracker_type == 'rutracer.org':
        r = login_in_rutracker(url)
    else:
        r = client.get(url)
    bsObj = BeautifulSoup(r.content, 'html.parser') 
    print(bsObj)

    if tracker_type == 'rutor.info':
        download_div = bsObj.find('div', {'id': 'download'}).a
        torrent_url = download_div.find_next_sibling('a').attrs['href']
        return torrent_url
    elif tracker_type == 'rutracer.org':
        download_div = bsObj.find('a', {'id': 'logged-in-username'})
        #download_div = bsObj.find('a', {'class': 'dl-stub'})
        print(download_div)


# Filter trackers' urls by size or by lang's quality
def filter_trackers(trackers):
    filtred_trackers = []
    if trackers:
        for item in trackers:
            remove_flag = 0
            if (item['size'] < 2) or (item['size'] > 10):
                remove_flag = 1

            # not Оригинальная - закадровый многоголосый и 3d !!!
            if not (('ППД' in item['langs']) or ('Оригинальная' in item['langs'])):
                remove_flag = 1

            # filter unknown trackers
            # if not (('rutor.info' in item['tracker']) or ('kinozal.tv' in item['tracker'] or ('rutracker.org' in item['tracker']))):
            if not ('rutracker.org' in item['tracker']):
                remove_flag = 1

            if not remove_flag: 
                filtred_trackers.append(item)
    return filtred_trackers

# Ranging and get best torrent's url
def get_best_torrent_url(film):
    trackers = get_trackers(film, 'hd')
    trackers = filter_trackers(trackers)
    if trackers: 
        trackers.sort(key=lambda x: x['sid_count'], reverse = True)

    rip_trackers = get_trackers(film, 'rip')
    rip_trackers = filter_trackers(rip_trackers)
    if rip_trackers: 
        rip_trackers.sort(key=lambda x: x['sid_count'], reverse = True)

    trackers += rip_trackers
    pprint(trackers)

    #Get torrent's urls cinemate href by

    for item in trackers:
        r = client.get(item['href'])
        bsObj = BeautifulSoup(r.content, 'html.parser') 
        trackers_url = bsObj.find('a', attrs={'rel': 'nofollow'}).attrs['href']
        if trackers_url:
            print(trackers_url)
            torrent_url = get_ext_torrent(trackers_url, item['tracker'])
            return torrent_url
    
    # NEXT - get .torr link on rutor, rutacker, kinozal, etc.

    # Can't get url
    return None

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

torrent_url = get_best_torrent_url(newfilms[2])
print(torrent_url)

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
