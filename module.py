#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import re
import os
import json
import time
import yaml
import requests
from datetime import datetime
from lxml import etree
from subprocess import check_output, CalledProcessError
from optparse import OptionParser
from subprocess import Popen, PIPE
from colorama import init
from termcolor import colored

# Use Colorama to allow color output to the terminal
init()

# parse the CLI information
parser = OptionParser(usage='usage: %prog [options]')
parser.add_option('-v', action='count', dest='verbosity', default=0, help='increase output verbosity')
parser.add_option('-q', '--quiet', action='store_true', dest='quiet', help='disables all output')
parser.add_option('-f', '--frequency', dest='frequency', default=86400, help='image download frequency in seconds (default: 1 day)')
parser.add_option('-a', '--useragent', dest='useragent', default='sitemap-generator/1.0 (+https://github.com/telemundo/sitemap-generator)', type='string')
parser.add_option('-c', '--config', dest='config', default='config.yaml', type='string', help='YAML configuration file (default: config.yaml)')
(options, args) = parser.parse_args()

def log(message, verbosity=1):
    ''' Logging interface '''
    levels = [{ 'label': 'error', 'color': 'red' },   # 0
              { 'label': 'warn', 'color': 'yellow' }, # 1
              { 'label': 'info', 'color': 'white' },  # 2
              { 'label': 'debug', 'color': 'cyan' },  # 3
              { 'label': 'trace', 'color': 'green' }] # 4
    if options.verbosity >= verbosity and not options.quiet:
        try:
            level_label = levels[verbosity]['label']
            level_color = levels[verbosity]['color']
        except IndexError:
            level_label = 'unknown'
            level_color = 'magenta'
        print '[%s][%s] %s' % (colored(time.strftime('%Y-%m-%d %H:%M:%S'), 'blue'),
                               colored(level_label, level_color),
                               message)

def configure(input_file):
    ''' Loads and validates the configuration data '''
    config = {}
    if os.path.exists(input_file):
        fh = open(input_file)
        config = yaml.load(fh)
        fh.close()

    if 'publisher' not in config:
        parser.error('%s is missing the "publisher" configuration tree' % input_file)
    if 'domain' not in config['publisher'] or config['publisher']['domain'] is None:
        parser.error('%s is missing the "publisher:domain" parameter' % input_file)
    if 'proxy' not in config['publisher'] or config['publisher']['proxy'] is None:
        config['publisher']['proxy'] = None

    if 'mainsite' not in config:
        parser.error('%s is missing the "mainsite" configuration tree' % input_file)
    if 'domain' not in config['mainsite'] or config['mainsite']['domain'] is None:
        parser.error('%s is missing the "mainsite:domain" parameter' % input_file)
    if 'proxy' not in config['mainsite'] or config['mainsite']['proxy'] is None:
        config['mainsite']['proxy'] = None

    if 'binary' not in config:
        config['binary'] = {}
    if 'phantomjs' not in config['binary'] or config['binary']['phantomjs'] is None:
        config['binary']['phantomjs'] = 'phantomjs'
    if 'convert' not in config['binary'] or config['binary']['convert'] is None:
        config['binary']['convert'] = 'convert'

    if 'path' not in config:
        config['path'] = {}
    if 'assets' not in config['path'] or config['path']['assets'] is None:
        config['path']['assets'] = '%s/tmp' % (script_dir)
    if 'rasterizejs' not in config['path'] or config['path']['rasterizejs'] is None:
        config['path']['rasterizejs'] = '%s/lib/rasterize.js' % (script_dir)

    return config

def request(record, url, redir=False):
    ''' Request processor '''
    log('request [%s]' % (url), verbosity=3)
    image_dir = '%s' % (record['url'])
    res = requests.head(url, verify=False, headers=request_headers)
    if res.status_code in [200] and rasterize(image_dir, url):
        body = requests.get(url, verify=False, headers=request_headers)
        body_html = body.text.encode('utf-8')
        body_dom = etree.HTML(body_html)
        meta_title = body_dom.xpath('//title')
        meta_description = body_dom.xpath('//meta[@name="description"]')
        return {
            'title': record['title'],
            'metadata': {
                'title': meta_title[0].text if meta_title else None,
                'description': meta_description[0].get('content') if meta_description else None
            },
            'template': record['template'],
            'cname': record['cname'],
            'section': record['section_url'],
            'images': image_dir,
            'url': record['url'],
            'destination': url,
            'source': record['source'],
            'redir': redir,
            'error': False
        }
    elif res.status_code in [301, 302]:
        log('redirect [%s] > [%s]' % (url, res.headers['location']), verbosity=1)
        if not re.match('^https?:', res.headers['location'], re.IGNORECASE):
            url = 'http://%s/%s' % (script_config['mainsite']['domain'], res.headers['location'].lstrip('/'))
        else:
            url = res.headers['location']
        return request(record, url, True)
    else:
        log('request ![%s] (%s)' % (url, res.status_code), verbosity=0)
        return {
            'title': record['title'],
            'metadata' : None,
            'template': None,
            'cname': record['cname'],
            'section': record['section_url'],
            'images': 'http://placehold.it/300x360.png&text=',
            'url': record['url'],
            'destination': url,
            'source': record['source'],
            'redir': redir,
            'error': res.status_code
        }

    return None

def rasterize(image_dir, url):
    ''' Image rasterizer '''
    image_path = '%s/%s' % (script_config['path']['assets'], image_dir)
    image_raw = '%s/raw.png' % (image_path)
    image_crop = '%s/crop.png' % (image_path)
    image_thumb = '%s/thumb.png' % (image_path)

    download = True
    if os.path.exists(image_raw):
        time_now = time.time()
        time_mod = os.path.getmtime(image_raw)
        difference = int(time_now-time_mod)
        # only re-download images that are more than a week old
        if difference < request_freq:
            download = False

    if download is True:
        log('download [%s]' % (image_dir), verbosity=4)
        if not os.path.exists(image_path):
            os.makedirs(image_path)
        try:
            check_output([script_config['binary']['phantomjs'], script_config['path']['rasterizejs'], url, image_raw])
            check_output([script_config['binary']['convert'], image_raw, '-crop', '1200x1200+0+0', image_crop])
            check_output([script_config['binary']['convert'], image_crop, '-filter', 'Lanczos', '-resize', '300x360', '-unsharp', '2x0.5+0.9+0', '-quality', '95', image_thumb])
        except CalledProcessError, child_exception:
            return False

    return True

# Global settings
script_dir = os.path.dirname(os.path.realpath(__file__))
script_config = configure(options.config)
request_freq = int(options.frequency)
request_headers = {
    'User-Agent': options.useragent
}

# main routine
def main():
    timer_start = datetime.now()
    log('config [file %s]' % (options.config), verbosity=3)

    sections = {}
    microsites = {}

    microsite_proxies = None
    if script_config['publisher']['proxy'] is not None:
        microsite_proxies = {
            'http': script_config['publisher']['proxy'],
            'https': script_config['publisher']['proxy'],
        }
    showconfig_proxies = None
    if script_config['mainsite']['proxy'] is not None:
        showconfig_proxies = {
            'http': script_config['mainsite']['proxy'],
            'https': script_config['mainsite']['proxy'],
        }

    log('processing [showconfig]', verbosity=2)
    showconfig_url = 'http://%s/config/showconfig/showconfig.xml' % (script_config['mainsite']['domain'])
    showconfig_req = requests.get(showconfig_url, proxies=showconfig_proxies, headers=request_headers)
    log('request [%s]' % (showconfig_req.url), verbosity=3)
    if showconfig_req.status_code in [200]:
        showconfig_xml = showconfig_req.text.encode('utf-8')
        showconfig_tree = etree.XML(showconfig_xml)
        showconfigs = showconfig_tree.xpath('/shows/show')
        for showconfig in showconfigs[::-1]:
            metadata = None
            showconfig_hub = showconfig.get('isHub')
            showconfig_name = showconfig.xpath('fullShowName')[0].text
            showconfig_path = showconfig.xpath('urlFriendlyShowName')[0].text
            if showconfig_hub is None:
                showconfig_path = showconfig_path.lower()
                showconfig_cname = showconfig.xpath('categoryItemName')[0].text.lower()
                showconfig_result = showconfig.xpath('showCategory')
                showconfig_template = showconfig.xpath('templateName')[0].text.lower()
                if len(showconfig_result) > 0:
                    showconfig_section = showconfig_result[0].text.lower()
                    if showconfig_cname not in microsites:
                        log('microsite [%s]' % (showconfig_cname), verbosity=4)
                        microsites[showconfig_cname] = {
                            'title': showconfig_name,
                            'cname': showconfig_cname,
                            'template': showconfig_template,
                            'section_url':  showconfig_section,
                            'microsite_url': showconfig_path,
                            'source': 'showconfig'
                        }
                    else:
                        log('microsite +[%s]' % (showconfig_cname), verbosity=4)
            else:
                if showconfig_path and len(showconfig_path) > 0:
                    showconfig_path = showconfig_path.lower()
                    if showconfig_path not in sections:
                        section_params = {'categoryItem': showconfig_path}
                        section_req = requests.get('http://%s/services/findPage' % (script_config['publisher']['domain']), params=section_params, proxies=microsite_proxies, headers=request_headers)
                        log('request [%s]' % (section_req.url), verbosity=3)
                        if section_req.status_code in [200]:
                            section_xml = section_req.text.encode('utf-8')
                            section_tree = etree.XML(section_xml)
                            section_result = section_tree.xpath('/Page/categoryItem')
                            if len(section_result) > 0:
                                for section_data in section_result:
                                    section_path = section_data.xpath('path')[0].text.lower()
                                    section_name = section_data.xpath('name')[0].text
                                    section_title = section_data.xpath('displayName')
                                    if len(section_title) > 0:
                                        title = section_title[0].text
                                    else:
                                        title = section_name
                                    log('section [%s]' % (section_path), verbosity=4)
                                    sections[showconfig_path] = {
                                        'title': title,
                                        'cname': section_name.lower(),
                                        'template': 'home',
                                        'section_url': showconfig_path,
                                        'microsite_url': '',
                                        'source': 'publisher'
                                    }
                                    break
                            else:
                                log('section +[%s]' % (showconfig_path), verbosity=4)
                                sections[showconfig_path] = {
                                    'title': showconfig_name,
                                    'cname': '',
                                    'template': 'home',
                                    'section_url': showconfig_path,
                                    'microsite_url': '',
                                    'source': 'showconfig'
                                }
                        else:
                            log('section ![%s] (%d)' % (showconfig_path, section_req.status_code), verbosity=0)
                    else:
                        log('section ?[%s]' % (showconfig_path), verbosity=4)
                else:
                    log('section ^[homepage]', verbosity=4)
    else:
        log('request [%s] (%d)' % (showconfig_req.url, showconfig_req.status_code), verbosity=0)

    section_index = dict((r['section_url'], i) for i, r in sections.items())
    microsite_index = dict((r['microsite_url'], i) for i, r in microsites.items())

    log('processing [publisher]', verbosity=2)
    microsite_params = {'category': 'all'}
    microsite_req = requests.get('http://%s/services/listCategoryItems' % (script_config['publisher']['domain']), params=microsite_params, proxies=microsite_proxies, headers=request_headers)
    log('request [%s]' % (microsite_req.url), verbosity=3)
    if microsite_req.status_code in [200]:
        microsite_xml = microsite_req.text.encode('utf-8')
        microsite_tree = etree.XML(microsite_xml)
        microsite_result = microsite_tree.xpath('/CategoryItemList/categoryItem')
        for microsite in microsite_result:
            microsite_path = microsite.xpath('urlFriendlyShowName')[0].text.lower()
            microsite_name = microsite.xpath('displayName')
            microsite_cname = microsite.xpath('categoryItemName')[0].text.lower()
            microsite_section = microsite.xpath('categoryName')[0].text.lower()
            microsite_active = microsite.xpath('isActive')[0].text.lower()
            if microsite_active in ['true']:
                section = None
                if microsite_section not in sections:
                    section_params = {'categoryItem': microsite_section}
                    section_req = requests.get('http://%s/services/findPage' % (script_config['publisher']['domain']), params=section_params, proxies=microsite_proxies, headers=request_headers)
                    log('request [%s]' % (section_req.url), verbosity=3)
                    if section_req.status_code in [200]:
                        section_xml = section_req.text.encode('utf-8')
                        section_tree = etree.XML(section_xml)
                        section_result = section_tree.xpath('/Page/categoryItem')
                        for section_data in section_result:
                            section_path = section_data.xpath('path')[0].text.lower()
                            section_name = section_data.xpath('name')[0].text
                            section_title = section_data.xpath('displayName')
                            if section_path not in sections:
                                log('section [%s]' % (section_path), verbosity=4)
                                if len(section_title) > 0:
                                    title = section_title[0].text
                                else:
                                    title = section_name
                                sections[section_path] = {
                                    'title': title,
                                    'cname': section_name.lower(),
                                    'template': 'home',
                                    'section_url': section_path,
                                    'microsite_url': '',
                                    'source': 'publisher'
                                }
                            else:
                                log('section +[%s]' % (section_path), verbosity=4)
                                sections[section_path]['title'] = section_name.lower()
                            section = sections[section_path]
                            break
                    else:
                        sections[microsite_section] = None
                        log('section ?[%s] (%d)' % (microsite_section, section_req.status_code), verbosity=0)
                # only process microsites within a valid section
                if section is not None:
                    if len(microsite_name) > 0:
                        title = microsite_name[0].text
                    else:
                        title = microsite_cname
                    if microsite_cname not in microsites:
                        log('microsite [%s]' % (microsite_cname), verbosity=4)
                        metadata = {
                            'title': title,
                            'cname': microsite_cname,
                            'template': None,
                            'section_url': section['section_url'],
                            'microsite_url': microsite_path,
                            'source': 'publisher'
                        }
                        microsites[microsite_cname] = metadata
                    else:
                        log('microsite +[%s]' % (microsite_cname), verbosity=4)
                        microsites[microsite_cname]['title'] = title
    else:
        log('microsite ![%s] (%d)' % (microsite_cname, microsite_req.status_code), verbosity=0)

    records = []
    records.append({
        'title': 'Homepage',
        'template': '',
        'cname': '',
        'section_url':  '',
        'microsite_url':  '',
        'source': None
    })
    for section in sections:
        records.append(sections[section])
    for microsite in microsites:
        records.append(microsites[microsite])
    log('records [%d]' % (len(records)), verbosity=2)

    images = []
    sortedrecords = sorted(records, key=lambda k: (k['section_url'], k['microsite_url']))

    for record in sortedrecords:
        path = '%s/%s' % (record['section_url'], record['microsite_url'])
        record['url'] = path.rstrip('/')
        url = 'http://%s/%s' % (script_config['mainsite']['domain'], record['url'])
        image = request(record, url.rstrip('/'))
        if image is not None:
            images.append(image)

    log('images [%d]' % (len(images)), verbosity=2)
    if len(images):
        jsonfile = '%s/sitemap.json' % (script_config['path']['assets'])
        with open(jsonfile, 'w') as fp:
            json.dump(images, fp)

    timer_end = datetime.now()
    log('runtime [%s]' % (timer_end-timer_start), verbosity=2)

if __name__ == "__main__":
    main()
