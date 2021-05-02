# -*- coding: utf-8 -*-
import os

import pymongo
import mongomock
import pytest
import pytest_mock
import requests
import requests_mock
import codecs
import datetime
from bs4 import BeautifulSoup

from autocinemator.cinematorprobe import get_db, loginin_cinemate, get_new_films, main
from autocinemator.cinematorprobe import datestr_to_date, get_film_info, filter_films
from autocinemator.cinematorprobe import get_trackers, login_in_tracker, get_ext_torrent
from autocinemator.cinematorprobe import filter_trackers, get_best_torrent_url, add_torrurl_and_mark

db_host = os.environ.get('CINEMATE_DB_HOST')
DB_NAME = 'autocinemator'
cinemate_user = os.environ.get('CINEMATE_USERNAME')
cinemate_password = os.environ.get('CINEMATE_PASSWORD')
db_user = os.environ.get('CINEMATE_DB_USERNAME')
db_password = os.environ.get('CINEMATE_DB_PASSWORD')
LOGIN_URL = 'https://beta.cinemate.cc/login/'
TOP_URL = 'https://beta.cinemate.cc'


@pytest.fixture()
def dbconnection():
    pymongo_client = pymongo.MongoClient(db_host,
                                         username=db_user,
                                         password=db_password,
                                         authSource=DB_NAME)

    yield pymongo_client

    pymongo_client.close()


@pytest.fixture()
def prelogin_rutracker():
    client = login_in_tracker(requests.session(), 'rutracker.org',
                              'https://rutracker.org/forum/viewtopic.php?t=6034131',
                              cinemate_user, cinemate_password)
    return client


@pytest.fixture()
def prelogin_kinozal():
    client = login_in_tracker(requests.session(), 'kinozal.tv',
                              'http://kinozal.tv/details.php?id=1837692',
                              cinemate_user, cinemate_password)
    return client


def test_get_db_pass(dbconnection):
    ''' Testing returned db object, insert and delete object '''
    assert get_db(db_host, DB_NAME, db_user, db_password) == dbconnection[DB_NAME]
    # create and remove object in db
    inserted_id = dbconnection[DB_NAME].test.insert_one({"test": "test"}).inserted_id
    assert dbconnection[DB_NAME].test.delete_one({'_id': inserted_id})


def test_get_db_fail():
    assert get_db('incorrect dbname', DB_NAME, db_user, db_password) is None
    assert get_db(db_host, DB_NAME, 'bad_user', db_password) is None
    assert get_db(db_host, DB_NAME, db_user, 'bad_password') is None


def test_loginin_cinemate_pass():
    client = requests.session()
    assert db_user == loginin_cinemate(client, cinemate_user, cinemate_password)


def test_loginin_cinemate_fail():
    client = requests.session()
    assert loginin_cinemate(client, 'bad_user', cinemate_password) is None
    assert loginin_cinemate(client, cinemate_user, 'bad_password') is None


def test_get_new_films_from_site(dbconnection):
    ''' Testing geting all films with right atributes '''
    client = requests.session()
    loginin_cinemate(client, cinemate_user, cinemate_password)
    filmslist = get_new_films(client, dbconnection[DB_NAME], 1000)
    for film in filmslist:
        assert film['href']
        assert film['name']
        assert film['quality']


def test_get_new_films_pass(requests_mock):
    films = [{'href': 'https://beta.cinemate.cc/movie/163089/',
              'name': 'Годзилла против Конга', 'quality': 'HD'},
             {'href': 'https://beta.cinemate.cc/movie/354070/',
              'name': 'Оборотень', 'quality': 'HD'},
             {'href': 'https://beta.cinemate.cc/movie/361002/',
              'name': 'День курка', 'quality': 'HD'},
             {'href': 'https://beta.cinemate.cc/movie/220708/',
              'name': 'Поступь хаоса', 'quality': 'HD'},
             {'href': 'https://beta.cinemate.cc/movie/354078/',
              'name': 'Ая и ведьма', 'quality': 'HD'}]
    requests_mock.get(TOP_URL, text=codecs.open('tests/top24.html', 'r', 'utf-8').read())
    db = mongomock.MongoClient().db.collection
    assert get_new_films(requests.session(), db, 2021) == films

    film = {'href': 'https://beta.cinemate.cc/movie/163089/',
            'name': 'Годзилла против Конга', 'quality': 'HD'}
    db.films.insert_one(film)   # If persist in db
    del films[0]
    assert get_new_films(requests.session(), db, 2021) == films


def test_get_new_films_fail(requests_mock):
    requests_mock.get(TOP_URL, text=codecs.open('tests/get_new_films_fail.html', 'r', 'utf-8')
                                          .read())
    db = mongomock.MongoClient().db.collection
    assert not get_new_films(requests.session(), db, 2021)


@pytest.mark.parametrize(('date, expected'), [
    ('1 апреля 2016', datetime.datetime(2016, 4, 1)),
    ('12 декабря 2050', datetime.datetime(2050, 12, 12)),
    ('02 мая 130', datetime.datetime(130, 5, 2))
])
def test_datestr_to_date_pass(date, expected):
    assert datestr_to_date(date) == expected


def test_datestr_to_date_fail():
    with pytest.raises(ValueError):
        datestr_to_date('1 мартобря 2016')
    with pytest.raises(AttributeError):
        datestr_to_date('восьмого марта 2025')
    with pytest.raises(ValueError):
        datestr_to_date('31 февраля 2025')
    with pytest.raises(ValueError):
        datestr_to_date('2015 февраля 13')
    with pytest.raises(AttributeError):
        datestr_to_date('12.12.2012')
    with pytest.raises(AttributeError):
        datestr_to_date('февраля 2025')
    with pytest.raises(AttributeError):
        datestr_to_date('1 мая')


@pytest.mark.parametrize(('film, film_info'), [
    (
        {'href': 'https://beta.cinemate.cc/movie/352717/',
         'name': 'Дорогие товарищи!',
         'quality': 'HD'},
        {'categories': ['история', 'драма'], 'countries': ['Россия'],
         'date': datetime.datetime(2020, 9, 7, 0, 0),
         'discription': '1962 год, в советском Новочеркасске',
         'img': 'http://p.cinemate.cc/media/m/7/1/352717/0.big.jpg'}
    ),
    (
        {'href': 'https://beta.cinemate.cc/movie/356714/',
         'name': 'Мавританец',
         'quality': 'HD'},
        {'categories': ['триллер', 'драма'],
         'countries': ['Великобритания', 'США'],
         'date': datetime.datetime(2021, 2, 12, 0, 0),
         'discription': 'Реальная история заключенного в Гуантанамо',
         'img': 'http://p.cinemate.cc/media/m/4/1/356714/0_hCRQ2u5.big.jpg'}
    )
])
def test_get_film_info_from_site(film, film_info):
    client = requests.session()
    loginin_cinemate(client, cinemate_user, cinemate_password)
    return_info = get_film_info(client, film)
    assert int(return_info['IMDB_count']) and float(return_info['IMDB_rate'])
    assert int(return_info['Kinopoisk_count']) and float(return_info['Kinopoisk_rate'])
    del return_info['IMDB_count']
    del return_info['IMDB_rate']
    del return_info['Kinopoisk_count']
    del return_info['Kinopoisk_rate']
    return_info['discription'] = return_info['discription'][:len(film_info['discription'])]
    assert return_info == film_info


def test_get_film_info_fail(requests_mock):
    film = {'href': 'https://beta.cinemate.cc/movie/356714/',
            'name': 'Мавританец',
            'quality': 'HD'}
    requests_mock.get(film['href'], text=codecs.open('tests/get_film_info_fail.html', 'r', 'utf-8')
                                               .read())
    return_info = get_film_info(requests.session(), film)
    assert return_info['discription']
    assert not return_info['categories']
    assert not return_info['countries']
    assert return_info['date']
    assert not return_info['IMDB_count']
    assert not return_info['IMDB_rate']
    assert not return_info['Kinopoisk_count']
    assert not return_info['Kinopoisk_rate']
    assert return_info['img']


def test_get_film_info_raise(requests_mock):
    film = {'href': 'https://beta.cinemate.cc/movie/356714/',
            'name': 'Мавританец',
            'quality': 'HD'}
    requests_mock.get(film['href'], text='test')
    with pytest.raises(AttributeError):
        get_film_info(requests.session(), film)


@pytest.mark.parametrize(('film'), [
    [{'IMDB_count': 5000, 'IMDB_rate': 6.0, 'Kinopoisk_count': 1000, 'Kinopoisk_rate': 5.0},
     {'IMDB_count': 105000, 'IMDB_rate': 10.0, 'Kinopoisk_count': 1000, 'Kinopoisk_rate': 5.0},
     {'IMDB_count': 5000, 'IMDB_rate': 6.0, 'Kinopoisk_count': 101000, 'Kinopoisk_rate': 10.0}],
    [{'IMDB_count': 5000, 'IMDB_rate': 6.0, 'Kinopoisk_count': 1000, 'Kinopoisk_rate': 5.0}]
])
def test_filter_films_good(film):
    assert film == filter_films(film)


@pytest.mark.parametrize(('film'), [
    [{'IMDB_count': 4999, 'IMDB_rate': 5.9, 'Kinopoisk_count': 999, 'Kinopoisk_rate': 4.9},
     {'IMDB_count': 4999, 'IMDB_rate': 5.9, 'Kinopoisk_count': 1000, 'Kinopoisk_rate': 5.0},
     {'IMDB_count': 5000, 'IMDB_rate': 6.0, 'Kinopoisk_count': 999, 'Kinopoisk_rate': 4.9},
     {'IMDB_count': 0, 'IMDB_rate': 0.0, 'Kinopoisk_count': 1000, 'Kinopoisk_rate': 5.0},
     {'IMDB_count': 5000, 'IMDB_rate': 6.0, 'Kinopoisk_count': 0, 'Kinopoisk_rate': 0.0}],
    [{'IMDB_count': 1000, 'IMDB_rate': 1.0, 'Kinopoisk_count': 500, 'Kinopoisk_rate': 4.0}],
    [{'IMDB_count': 4999, 'IMDB_rate': 6.0, 'Kinopoisk_count': 1000, 'Kinopoisk_rate': 5.0}],
    [{'IMDB_count': 5000, 'IMDB_rate': 5.9, 'Kinopoisk_count': 1000, 'Kinopoisk_rate': 5.0}],
    [{'IMDB_count': 5000, 'IMDB_rate': 6.0, 'Kinopoisk_count': 999, 'Kinopoisk_rate': 5.0}],
    [{'IMDB_count': 5000, 'IMDB_rate': 6.0, 'Kinopoisk_count': 1000, 'Kinopoisk_rate': 4.9}]
])
def test_filter_films_bad(film):
    assert not filter_films(film)


def test_get_trackers_pass(requests_mock):
    film = {'countries': ['США'],
            'href': 'https://beta.cinemate.cc/movie/361002/'}
    trackers = [
        {'countries': ['США'], 'href': 'https://beta.cinemate.cc/go/s/2668138',
         'langs': ['ПМЗ', 'Авторский (одноголосый)', 'Оригинальная'],
         'sid_count': 54, 'size': 15.3, 'tracker': 'rutracker.org', 'type': 'hd'},
        {'countries': ['США'], 'href': 'https://beta.cinemate.cc/go/s/2667001',
         'langs': ['ППД', 'Оригинальная'], 'sid_count': 92, 'size': 9.9,
         'tracker': 'kinozal.tv', 'type': 'hd'},
        {'countries': ['США'], 'href': 'https://beta.cinemate.cc/go/s/2666999',
         'langs': ['ППД', 'ПМЗ', 'Оригинальная'], 'sid_count': 26, 'size': 7.0,
         'tracker': 'kinozal.tv', 'type': 'hd'},
        {'countries': ['США'], 'href': 'https://beta.cinemate.cc/go/s/2666997',
         'langs': ['ППД', 'ПМЗ', 'Оригинальная'], 'sid_count': 63, 'size': 26.4,
         'tracker': 'kinozal.tv', 'type': 'hd'},
        {'countries': ['США'], 'href': 'https://beta.cinemate.cc/go/s/2666993',
         'langs': ['ППД', 'ПМЗ', 'Оригинальная'], 'sid_count': 19, 'size': 12.9,
         'tracker': 'kinozal.tv', 'type': 'hd'},
        {'countries': ['США'], 'href': 'https://beta.cinemate.cc/go/s/2591239',
         'langs': ['ПМЗ', 'Оригинальная'], 'sid_count': 9, 'size': 4.2,
         'tracker': 'kinozal.tv', 'type': 'hd'},
        {'countries': ['США'], 'href': 'https://beta.cinemate.cc/go/s/2659291',
         'langs': ['Любительский (многоголосый)', 'Оригинальная'], 'sid_count': 44,
         'size': 10.5, 'tracker': 'rutracker.org', 'type': 'hd'},
        {'countries': ['США'], 'href': 'https://beta.cinemate.cc/go/s/2656155',
         'langs': ['ПМЗ', 'Авторский (одноголосый)', 'Оригинальная'], 'sid_count': 32,
         'size': 28.0, 'tracker': 'rutracker.org', 'type': 'hd'}
    ]
    requests_mock.get(film['href'] + 'links/#tabs',
                      text=codecs.open('tests/get_trackers_pass.html', 'r', 'utf-8').read())
    assert get_trackers(requests.session(), film, 'hd') == trackers


def test_get_trackers_from_site():
    film = {'countries': ['США'],
            'href': 'https://beta.cinemate.cc/movie/361002/'}
    client = requests.session()
    loginin_cinemate(client, cinemate_user, cinemate_password)
    trackers = get_trackers(client, film, 'hd')
    assert 'countries' in trackers[0]
    assert 'href' in trackers[0]
    assert 'langs' in trackers[0]
    assert 'sid_count' in trackers[0]
    assert 'size' in trackers[0]
    assert 'countries' in trackers[0]
    assert 'tracker' in trackers[0]
    assert 'type' in trackers[0]


def test_get_trackers_fail(requests_mock):
    film = {'countries': ['США'],
            'href': 'https://beta.cinemate.cc/movie/361002/'}
    requests_mock.get(film['href'] + 'links/#tabs',
                      text=codecs.open('tests/get_trackers_fail.html', 'r', 'utf-8').read())
    assert not get_trackers(requests.session(), film, 'hd')


def test_login_in_tracker_kinozal_pass(prelogin_kinozal):
    r = prelogin_kinozal.get('http://kinozal.tv/details.php?id=1837692')
    bsObj = BeautifulSoup(r.content, 'html.parser')
    assert bsObj.find('li', {'class': 'tp2 center b'}).a.text == cinemate_user


def test_login_in_tracker_kinozal_fail():
    client = login_in_tracker(requests.session(), 'kinozal.tv',
                              'http://kinozal.tv/details.php?id=1837692',
                              cinemate_user, 'bad_password')
    r = client.get('http://kinozal.tv/details.php?id=1837692')
    bsObj = BeautifulSoup(r.content, 'html.parser')
    with pytest.raises(AttributeError):
        bsObj.find('li', {'class': 'tp2 center b'}).a.text


'''
def test_login_in_tracker_rutracker_pass(prelogin_rutracker):
    r = prelogin_rutracker.get('https://rutracker.org/forum/viewtopic.php?t=6034131')
    bsObj = BeautifulSoup(r.content, 'html.parser')
    assert bsObj.find('a', {'id': 'logged-in-username'}).text == cinemate_user


def test_login_in_tracker_rutracker_fail():
    client = login_in_tracker(requests.session(),'rutracker.org',
                              'https://rutracker.org/forum/viewtopic.php?t=6034131',
                              cinemate_user, 'bad_password')
    r = client.get('https://rutracker.org/forum/viewtopic.php?t=6034131')
    bsObj = BeautifulSoup(r.content, 'html.parser')
    with pytest.raises(AttributeError):
        bsObj.find('a', {'id': 'logged-in-username'}).text
'''


def test_get_ext_torrent_fail():
    assert not get_ext_torrent(requests.session(), 'https://ru.org/forum/viewtopic.php?t=6034131',
                               'rutracker.org', cinemate_user, 'bad_password')
    '''
    assert not get_ext_torrent(requests.session(),
                               'https://rutracker.org/forum/viewtopic.php?t=6034131',
                               'rutracker.org', cinemate_user, 'bad_password')
    '''
    assert not get_ext_torrent(requests.session(), 'http://kinozal.tv/details.php?id=1837692',
                               'kinozal.tv', cinemate_user, 'bad_password')
    assert not get_ext_torrent(requests.session(), 'http://rutor.info/torrent/8002000s',
                               'rutor.info', cinemate_user, cinemate_user)
    assert not get_ext_torrent(requests.session(), 'http://rutor.info/torrent/800200',
                               'ru.info', cinemate_user, cinemate_user)


def test_get_ext_torrent_pass(prelogin_rutracker, prelogin_kinozal):
    torr_url = get_ext_torrent(prelogin_kinozal, 'http://kinozal.tv/details.php?id=1837692',
                               'kinozal.tv', cinemate_user, cinemate_password)
    assert torr_url == 'https://dl.kinozal.tv/download.php?id=1837692'
    torr_url = get_ext_torrent(requests.session(), 'http://rutor.info/torrent/805515',
                               'rutor.info', cinemate_user, cinemate_user)
    assert torr_url == 'http://d.rutor.info/download/805515'
    '''
    torr_url = get_ext_torrent(prelogin_rutracker,
                               'https://rutracker.org/forum/viewtopic.php?t=6034131',
                               'rutracker.org', cinemate_user, cinemate_password)
    assert torr_url == 'https://rutracker.org/forum/dl.php?t=6034131'
    '''


@pytest.mark.parametrize(('films'), [
    [
        {'countries': ['США'], 'langs': ['ПМЗ', 'Любительский (многоголосый)', 'Оригинальная'],
         'size': 5.0, 'tracker': 'kinozal.tv'},
        {'countries': ['Канада'], 'langs': ['ППД', 'Оригинальная'],
         'size': 20.0, 'tracker': 'rutracker.org'},
        {'countries': ['США', 'Канада'], 'langs': ['ППД'],
         'size': 11.4, 'tracker': 'rutor.info'},
        {'countries': ['США', 'Россия'], 'langs': ['ПМЗ'],
         'size': 19.9, 'tracker': 'rutor.info'},
        {'countries': ['Россия'], 'langs': ['Оригинальная'],
         'size': 5.1, 'tracker': 'rutracker.org'},
    ],
    [
        {'countries': ['США', 'Россия'],
         'langs': ['ПМЗ', 'Любительский (многоголосый)', 'Оригинальная'],
         'size': 6.0, 'tracker': 'rutracker.org'}
    ],
    [
        {'countries': ['Россия'], 'langs': ['Оригинальная'],
         'size': 20.0, 'tracker': 'rutor.info'}
    ],
])
def test_filter_trackers_pass(films):
    assert filter_trackers(films) == films


@pytest.mark.parametrize(('films'), [
    [
        {'countries': ['США'], 'langs': ['ПМЗ', 'Любительский (многоголосый)', 'Оригинальная'],
         'size': 4.9, 'tracker': 'kinozal.tv'},
        {'countries': ['Канада'], 'langs': ['ППД', 'Оригинальная'],
         'size': 21.0, 'tracker': 'rutracker.org'},
        {'countries': ['США', 'Канада'], 'langs': ['Любительский (многоголосый)', 'Оригинальная'],
         'size': 11.4, 'tracker': 'rutor.info'},
        {'countries': ['США', 'Россия'], 'langs': ['ПМЗ'],
         'size': 19.9, 'tracker': 'ru.info'},
        {'countries': ['США'], 'langs': ['Оригинальная'],
         'size': 5.1, 'tracker': 'rutracker.org'},
    ],
    [
        {'countries': ['США', 'Россия'], 'langs': ['Любительский (многоголосый)', 'Оригинальная'],
         'size': 4.0, 'tracker': 'rutracker.org'}],
    [
        {'countries': ['Канада'], 'langs': ['Оригинальная'],
         'size': 22.0, 'tracker': 'rutor.info'}
    ],
])
def test_filter_trackers_fail(films):
    assert not filter_trackers(films)


def test_get_best_torrent_url(requests_mock):
    film = {'countries': ['США'], 'href': 'https://beta.cinemate.cc/movie/343247/'}
    bad_url = 'http://rutracker.org/forum/viewtopic.php?t=6041502'
    best_url = 'http://kinozal.tv/details.php?id=1838590'
    best_html = '''
    <li class="tp2 center b"><a href="http://kinozal.tv/">''' + cinemate_user + '''</a>
    </li><tr><td style="width: 210px" class="nw">
    <a href="//dl.kinozal.tv/download.php?id=1838590" title="Скачать Никто / Nobody / 2021 / ПД /
    WEB-DL (1080p)">
    <img src="/pic/dwn_torrent.gif" class="block w200" alt="" height="25">
    </a>
    </td>
    <td>Для того, чтобы скачать раздачу - скачайте торрент-файл и запустите его при помощи
    <a href="http://forum.kinozal.tv/forumdisplay.php?f=25" class="sba">клиента</a>
    . Дополнительная информация на Форуме
    <a href="http://forum.kinozal.tv/showthread.php?t=64783" class="sba">здесь</a>.
    </td></tr>
    '''
    torrent_url = 'https://dl.kinozal.tv/download.php?id=1838590'
    requests_mock.get(film['href'] + 'links/#tabs',
                      text=codecs.open('tests/get_best_torrent_url_pass.html', 'r', 'utf-8').read())
    requests_mock.get(film['href'],
                      text=codecs.open('tests/get_best_torrent_url_pass.html', 'r', 'utf-8').read())
    rutracker_a = '<a id="logged-in-username" href="https://rutracker.org/forum/">'\
                  + cinemate_user + '</a>'
    requests_mock.get(bad_url, text=rutracker_a)
    requests_mock.get(best_url, text=best_html)
    rutracker_a = '<a href="http://rutracker.org/forum/viewtopic.php?t=6041502" rel="nofollow"></a>'
    requests_mock.get('https://beta.cinemate.cc/go/s/2672774', text=rutracker_a)
    requests_mock.get('https://beta.cinemate.cc/go/s/2672750',
                      text='<a href="http://kinozal.tv/details.php?id=1838590" rel="nofollow"></a>')
    ret = get_best_torrent_url(requests.session(), film, cinemate_user, cinemate_password)
    assert ret == torrent_url


def test_add_torrurl_and_mark_pass(mocker):
    mocker.patch('autocinemator.cinematorprobe.get_best_torrent_url', return_value='url')
    films = [
        {'categories': ['мультфильм']},
        {'categories': ['боевик']},
        {'categories': ['фантастика']}
    ]
    ret_films = add_torrurl_and_mark(requests.session(), films, cinemate_user, cinemate_password)
    assert ret_films[0]['filmfolder'] == 'mults'
    assert ret_films[1]['filmfolder'] == 'films'
    assert ret_films[2]['filmfolder'] == 'films'
    for item in ret_films:
        assert item['to_download'] == 1
        assert item['torrent_url'] == 'url'
        assert item['added_datetime']


def test_add_torrurl_and_mark_fail(mocker):
    mocker.patch('autocinemator.cinematorprobe.get_best_torrent_url', return_value=None)
    films = [
        {'categories': ['мультфильм']}
    ]
    assert not add_torrurl_and_mark(requests.session(), films, cinemate_user, cinemate_password)


def test_main_cinemate_fail(mocker):
    mocker.patch('autocinemator.cinematorprobe.loginin_cinemate', return_value=None)
    assert main() is None


def test_main_db_fail(mocker):
    mocker.patch('autocinemator.cinematorprobe.loginin_cinemate', return_value=None)
    mocker.patch('autocinemator.cinematorprobe.get_db', return_value=True)
    assert main() is None


def test_main_no_films_pass(mocker):
    mocker.patch('autocinemator.cinematorprobe.loginin_cinemate', return_value=True)
    mocker.patch('autocinemator.cinematorprobe.get_db', return_value=True)
    mocker.patch('autocinemator.cinematorprobe.get_new_films', return_value=[])
    assert main() == 0


def test_main_add_to_db_fail(mocker):
    mocker.patch('autocinemator.cinematorprobe.loginin_cinemate', return_value=True)
    mocker.patch('autocinemator.cinematorprobe.get_new_films', return_value=[])
    newfilms = [
        {'name': 'Test Name', 'date': datetime.datetime.utcnow(),
         'categories': ['Test Category']},
        {'name': 'Test Name 2', 'date': datetime.datetime.utcnow(),
         'categories': ['Test Category 2']}
    ]
    mocker.patch('autocinemator.cinematorprobe.add_torrurl_and_mark', return_value=newfilms)

    class Col:
        inserted_ids = []

    films_col = Col()
    mocker.patch.object(pymongo.collection.Collection, 'insert_many', return_value=films_col)
    assert main() is None


def test_main_pass(mocker):
    mocker.patch('autocinemator.cinematorprobe.loginin_cinemate', return_value=True)
    mocker.patch('autocinemator.cinematorprobe.get_new_films', return_value=[])
    newfilms = [
        {'name': 'Test Name', 'date': datetime.datetime.utcnow(),
         'categories': ['Test Category']},
        {'name': 'Test Name 2', 'date': datetime.datetime.utcnow(),
         'categories': ['Test Category 2']}
    ]
    mocker.patch('autocinemator.cinematorprobe.add_torrurl_and_mark', return_value=newfilms)

    class Col:
        inserted_ids = ['1', '2']

    films_col = Col()
    mocker.patch.object(pymongo.collection.Collection, 'insert_many', return_value=films_col)
    assert main() == 2
