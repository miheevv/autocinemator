# -*- coding: utf-8 -*-
'''Cinemator worker

Regulary get new films and torrent links from cinemate.cc.

Films DB structure:
films: name, href, quality, categories, date, countries, discription, img
       IMDB_rate, IMDB_count, Kinopoisk_rate, Kinopoisk_count,
       added_datetime, torrent_url, bad_torrent, new (resently added)
       filmfolder (by default - 'films'), to_download, downloaded,
       to_delete (to delete on server),
       deleted (don't download in future again)
TODO
cinematorgui.py - list new films, mark to download and delete.
cinematorworker.py - on server to add torrent url for download, and delete old films
cinematoralice.py

'''

import datetime
# from pprint import pprint
import locale
import os
import re
# from urllib.request import Request, urlopen
import sys

import pymongo
import requests
from bs4 import BeautifulSoup

''' Settings '''
LOGIN_URL = 'https://beta.cinemate.cc/login/'
TOP_URL = 'https://beta.cinemate.cc'
# dayly
CINEMATE_TOP_CATEGORY = 'top_sites_24'
# or weekly
# CINEMATE_TOP_CATEGORY = 'top_sites_7'


def get_db(host, dbname, user, passw):
    ''' Connect to mongo and return db object '''

    try:
        client = pymongo.MongoClient(host,
                                     username=user,
                                     password=passw,
                                     authSource=dbname)
    # Force connection on a request as the connect=True parameter of MongoClient
    # seems to be useless here
        client.server_info()

    except pymongo.errors.ServerSelectionTimeoutError as err:
        print("Could not connect to server '",
              host, "' with error: ",
              err, file=sys.stderr)
        return None
    except pymongo.errors.OperationFailure as err:
        print("Could not get database '",
              dbname, "' to server '",
              host, "' with error: ",
              err, file=sys.stderr)
        return None
    return client[dbname]


def loginin_cinemate(client_session, user, pwd):
    ''' Login in to cinemate login url (using client_session and HTML headers)
    and return username from cinemate.cc or None if fail '''
    headers = {'User-Agent': 'Mozilla/5.0'}
    # Getting cookies or form with 'cm_token'
    output = client_session.get(LOGIN_URL, headers=headers)
    clientcokies = client_session.cookies.get_dict(domain='cinemate.cc')

    # Get cm_token from cinemate.cc
    if 'cm_token' in clientcokies:
        # Founded in cookies
        csrftoken = clientcokies['cm_token']
    else:
        # Get token from form
        bsObj = BeautifulSoup(output.content, 'html.parser')
        loginform = bsObj.find(id='login_form')
        csrfmiddlewaretoken = loginform.find('', {'name': 'csrfmiddlewaretoken'})
        csrftoken = csrfmiddlewaretoken.attrs['value']

    headers['referer'] = LOGIN_URL
    params = {'username': user,
              'password': pwd,
              'csrfmiddlewaretoken': csrftoken}
    # Login in
    output = client_session.post(LOGIN_URL + '?next=/', headers=headers, data=params)
    bsObj = BeautifulSoup(output.content, 'html.parser')
    # ret_login = bsObj.find('a', {'class', 'username username-link'})- not in beta
    ret_login = bsObj.find('a', {'class', 'username'})
    # if login is success, return username, if else return None
    if ret_login and ret_login.text == user:
        return ret_login.text
    else:
        print('Could not login to cinemate.cc.',
              ' Please, check login and password', file=sys.stderr)


def get_new_films(client, db, current_year=0):
    ''' Get new films + href from cinemate with current year production
        and add in return list if it pass film_quality_checker '''

    filmslist = []
    films_in_db = db.films
    if not current_year:
        current_year = datetime.datetime.utcnow().year

    r = client.get(TOP_URL)
    bsObj = BeautifulSoup(r.content, 'html.parser')
    filmdivs_list = bsObj.find('', {'id': CINEMATE_TOP_CATEGORY}) \
                         .find_all('', {'class': 'row delimiter'})

    # Parsing div
    for filmdiv in filmdivs_list:
        # If can't get important atributes (name of href) than go to next film
        try:
            fullname = str(filmdiv.div.a.attrs['title'])
            name = fullname[:-7]    # without year
            if not name:
                continue
            if str(filmdiv.div.a.attrs['href']):
                href = TOP_URL + str(filmdiv.div.a.attrs['href'])
            else:
                continue
            newfilm = {'name': name,
                       'href': href}
        except AttributeError:
            continue

        # Get list of film quality: Rip, HD, DVD, Экранка
        qualitylist = []
        try:
            for item in filmdiv.div.findNext('div').find_all('a'):
                qualitylist += item
        except AttributeError:
            continue    # Can't find any quality

        # Get highness quality
        if ('Rip' in qualitylist) or ('HD' in qualitylist):
            quality = 'HD' if 'HD' in qualitylist else 'Rip'
            newfilm['quality'] = quality

        # Don't add in list if low quality
        if not (('Rip' in qualitylist) or ('HD' in qualitylist)):
            continue

        # Don't add if no year or old year (< current_year - 1)
        try:
            filmyear = int(fullname[-5:-1])
        except ValueError:
            continue
        else:
            if not filmyear >= (current_year - 1):
                continue

        # Don't add if persist in DB
        if films_in_db.find_one({'name': name}):
            continue

        filmslist.append(newfilm)
    return filmslist


def datestr_to_date(datestr):
    ''' Convert formated '%day %month_str %year' string into datetime '''

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
    year = int(re.search(r'\d+$', datestr).group(0))

    try:
        month = month_to_int[month_str]
    except KeyError as e:
        raise ValueError('Undefined unit: {}'.format(e.args[0]))
    return datetime.datetime(year, month, day)


def get_film_info(client, film):
    film_info = {}
    headers = {'User-Agent': 'Mozilla/5.0'}
    r = client.get(film['href'], headers=headers)
    bsObj = BeautifulSoup(r.content, 'html.parser')
    film_detail = bsObj.find('', {'class': 'object_detail'})

    film_info['discription'] = film_detail.find('', {'class': 'description'}).get_text().strip()

    categories = []
    for item in film_detail.find('', {'class': 'main'}).find_all('a', {'itemprop': 'genre'}):
        categories += item
    film_info['categories'] = categories

    countries = []
    for item in film_detail.find('', {'class': 'main'}) \
                           .find(text='|') \
                           .parent.find_next_siblings('a'):
        countries += item
    film_info['countries'] = countries

    ratings = film_detail.find('', {'id': 'ratings'}).li
    try:
        film_info['IMDB_rate'] = float(ratings.span.a.get_text())
        film_info['IMDB_count'] = int(ratings.small.get_text()[1:-1])
    except AttributeError:
        film_info['IMDB_rate'] = 0
        film_info['IMDB_count'] = 0
    try:
        film_info['Kinopoisk_rate'] = float(ratings.find_next_sibling('li').span.a.get_text())
        film_info['Kinopoisk_count'] = int(ratings.find_next_sibling('li').small.get_text()[1:-1])
    except AttributeError:
        film_info['Kinopoisk_rate'] = 0
        film_info['Kinopoisk_count'] = 0

    film_date_nostrip = film_detail.find('', {'id': 'releases'}).find('li').get_text()
    if film_date_nostrip[:3] == 'РФ:':  # One country - Russia
        film_date = film_date_nostrip[4:]
    else:
        film_date = re.search(r'.+\n', film_date_nostrip).group(0).strip()
    film_info['date'] = datestr_to_date(film_date)

    film_info['img'] = 'http:' + bsObj.find('', {'class': 'posterbig'}).img.attrs['src']

    return film_info


def filter_films(newfilms):
    ''' Filter new films and return list to add (with autoset filmfolders, etc. params) '''
    notfiltred_films = []
    for item in newfilms:
        removeflag = None
        if ('IMDB_count' not in item) or (item['IMDB_count'] < 5000) or \
           ('IMDB_rate' not in item) or (item['IMDB_rate'] < 6.0) or \
           ('Kinopoisk_count' not in item) or (item['Kinopoisk_count'] < 1000) or \
           ('Kinopoisk_rate' not in item) or (item['Kinopoisk_rate'] < 5.0):
            removeflag = 1

        if removeflag is None:
            notfiltred_films.append(item)

    return notfiltred_films


def get_trackers(client, film, type):
    ''' Return trackers list from film '''
    trackers = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    r = client.get(film['href'] + 'links/#tabs', headers=headers)
    bsObj = BeautifulSoup(r.content, 'html.parser')
    trackers_list = bsObj.find('', {'id': 'site-list'})

    try:
        trackersHD_list = trackers_list.find('', {'id': type}).parent
    except AttributeError:
        return None

    langs_type = {
        'Профессиональное (полное дублирование)': 'ППД',
        'Профессиональное (многоголосый закадровый)': 'ПМЗ',
        'Оригинальная дорожка': 'Оригинальная'
    }
    # Get lang type
    for trackersdiv in trackersHD_list.find_all('', {'class': 'row delimiter'}):
        langs = []

        for langdiv in trackersdiv.find_all('', {'class': 'blue_span_float'}):
            try:
                langs.append(langs_type[str(langdiv.attrs['title'])])
            except KeyError:
                if not str(langdiv.attrs['title']) == 'Субтитры':
                    langs.append(str(langdiv.attrs['title']))

        newtracker = {'langs': langs}

        # Get tracker type
        try:
            newtracker['tracker'] = trackersdiv.find('div', attrs={'class': 'trackert'}) \
                                               .text.strip()
        except AttributeError:
            newtracker['tracker'] = None

        # Get size
        try:
            size_text = trackersdiv.find('div',
                                         attrs={'style': 'height:1.2em; overflow: hidden;'}) \
                                   .text.strip()
            newtracker['size'] = float(size_text[:size_text.find('.') + 2])
        except AttributeError:
            newtracker['size'] = 0
        except ValueError:
            newtracker['size'] = 0

        try:
            sid_count = int(trackersdiv.find('div', {'title': 'Число раздающих'}).text.strip())
            newtracker['sid_count'] = sid_count
        except AttributeError:
            newtracker['sid_count'] = 0

        try:
            tracker_href = trackersdiv.find('a', {'class': 'icon_t download-link'}).attrs['href']
            newtracker['href'] = TOP_URL + tracker_href
        except AttributeError:
            newtracker['href'] = None

        newtracker['type'] = type
        newtracker['countries'] = film['countries']

        if (not newtracker['href']) or (not newtracker['tracker']) or (not newtracker['size']):
            pass
        else:
            trackers.append(newtracker)

    return trackers


def login_in_tracker(client, tracker_type, url, usr, pwd):
    ''' Login in kinozal, rutracker and return client '''
    headers = {'User-Agent': 'Mozilla/5.0'}
    if tracker_type == 'rutracker.org':
        r = client.get(url)
        bsObj = BeautifulSoup(r.content, 'html.parser')
        try:
            if bsObj.find('a', {'id': 'logged-in-username'}).text == usr:
                return client    # Logined yet
        except AttributeError:
            params = {'login_username': usr,
                      'login_password': pwd,
                      'login': u'%E2%F5%EE%E4'}
            url = 'http://rutracker.org/forum/login.php'
            # Login in
            r = client.post(url, headers=headers, data=params)
            bsObj = BeautifulSoup(r.content, 'html.parser')
            if bsObj.find('input', {'name': 'cap_sid'}):
                return  # captcha needed
            else:
                return client

    if tracker_type == 'kinozal.tv':
        r = client.get(url)
        bsObj = BeautifulSoup(r.content, 'html.parser')
        try:
            if bsObj.find('li', {'class': 'tp2 center b'}).a.text == usr:
                return client    # Logined yet
        except AttributeError:
            params = {'username': usr,
                      'password': pwd}
            url = 'http://kinozal.tv/takelogin.php'
            # Login in
            client.post(url, headers=headers, data=params)
            return client


def get_ext_torrent(client, url, tracker_type, usr, pwd):
    ''' Get external (RUTOR, RUTRACKER, KINOZAL) torrent file's URL '''
    # Login in torrent
    if (tracker_type == 'rutracker.org') or (tracker_type == 'kinozal.tv'):
        if login_in_tracker(client, tracker_type, url, usr, pwd) is None:
            return

    # Getting torrent url
    try:
        r = client.get(url)
        bsObj = BeautifulSoup(r.content, 'html.parser')
        if tracker_type == 'rutor.info':
            download_div = bsObj.find('div', {'id': 'download'}).a
            torrent_url = download_div.find_next_sibling('a').attrs['href']
            return torrent_url
        if tracker_type == 'rutracker.org':
            torrent_url = 'https://rutracker.org/forum/' \
                          + bsObj.find('a', {'class': 'dl-stub dl-link dl-topic'}).attrs['href']
            return torrent_url
        if tracker_type == 'kinozal.tv':
            torrent_url = 'https:' + bsObj.find('img', {'src': '/pic/dwn_torrent.gif'}) \
                                          .parent.attrs['href']
            if torrent_url[:12] != 'https:/login':
                return torrent_url
            else:
                return  # login to kinozal.tv failed
    except AttributeError:
        return


def filter_trackers(trackers):
    ''' Filter trackers' urls by size or by lang's quality '''
    filtred_trackers = []
    if trackers:
        for item in trackers:
            remove_flag = 0
            if (item['size'] < 5) or (item['size'] > 20):
                remove_flag = 1

            # 'Оригинальная' only for russian films
            if item['langs'] == ['Оригинальная']:
                if not ('Россия' in item['countries']):
                    remove_flag = 1
            # not 'ППД', 'закадровый многоголосый' и '3d' !!!
            elif not (('ППД' in item['langs']) or ('ПМЗ' in item['langs'])):
                remove_flag = 1

            # filter unknown trackers
            if not (('rutor.info' in item['tracker']) or
               ('kinozal.tv' in item['tracker'] or
               ('rutracker.org' in item['tracker']))):
                remove_flag = 1

            if not remove_flag:
                filtred_trackers.append(item)
    return filtred_trackers


def get_best_torrent_url(client, film, usr, pwd):
    '''
    Ranging and getting best torrent's url - first hd, next -rip, then sort by sid count
    '''
    trackers = filter_trackers(get_trackers(client, film, 'hd'))
    if trackers:
        trackers.sort(key=lambda x: x['sid_count'], reverse=True)

    rip_trackers = get_trackers(client, film, 'rip')
    rip_trackers = filter_trackers(rip_trackers)
    if rip_trackers:
        rip_trackers.sort(key=lambda x: x['sid_count'], reverse=True)

    trackers += rip_trackers

    # Get torrent's urls cinemate href by
    for item in trackers:
        r = client.get(item['href'])
        bsObj = BeautifulSoup(r.content, 'html.parser')
        trackers_url = bsObj.find('a', attrs={'rel': 'nofollow'}).attrs['href']
        if trackers_url:
            print("Fouded best tracker's url: ", trackers_url)
            torrent_url = get_ext_torrent(client, trackers_url, item['tracker'], usr, pwd)
            if torrent_url:
                return torrent_url
            else:
                print('Bad link, try to found next...')


def add_torrurl_and_mark(client, films, usr, pwd):
    ''' Add torrent url and mark it for download if right catagory '''
    ret_films = []
    for i in range(len(films)):
        film_to_add = films[i]
        url = get_best_torrent_url(client, film_to_add, usr, pwd)
        if not url:
            continue    # Don't add if hasn't torrent url
        film_to_add['torrent_url'] = url
        film_to_add['filmfolder'] = 'films'
        if 'мультфильм' in film_to_add['categories']:
            film_to_add['filmfolder'] = 'mults'
            film_to_add['to_download'] = 1
        if ('боевик' in film_to_add['categories']) or ('фантастика' in film_to_add['categories']):
            film_to_add['to_download'] = 1
        film_to_add['added_datetime'] = datetime.datetime.utcnow()
        ret_films.append(film_to_add)
    return ret_films


def main():
    ''' Return number of added films of None if error '''
    locale.setlocale(locale.LC_ALL, '')
    cinemate_user = os.environ.get('CINEMATE_USERNAME')
    cinemate_password = os.environ.get('CINEMATE_PASSWORD')
    # DB
    DB_HOST = 'srvm'
    DB_NAME = 'autocinemator'
    db_user = os.environ.get('CINEMATE_DB_USERNAME')
    db_password = os.environ.get('CINEMATE_DB_PASSWORD')

    # Prelogin to cinemate and into DB
    client = requests.session()
    if not loginin_cinemate(client, cinemate_user, cinemate_password):
        return
    db = get_db(DB_HOST, DB_NAME, db_user, db_password)
    if not db:
        return

    # Get new films (if not persist in db) from cinemate.cc
    newfilms = get_new_films(client, db)
    # Get film's info for every film
    for item in newfilms:
        film_info = get_film_info(client, item)
        item.update(film_info)
    newfilms = filter_films(newfilms)
    newfilms = add_torrurl_and_mark(client, newfilms, cinemate_user, cinemate_password)
    if not newfilms:
        print('Can\'t find new films')
        return 0
    # pprint(newfilms)

    # Add new films to db
    films = db.get_collection('films')
    if films and db and newfilms:
        result = films.insert_many(newfilms)
    if not result.inserted_ids:
        print('Can\'t added any new films to DB')
        return

    print('New films added into DB:')
    for film in newfilms:
        print(film['name'], film['date'].strftime('(%d %b %Y)'), ', '.join(film['categories']))
    return len(result.inserted_ids)


if __name__ == '__main__':
    main()
