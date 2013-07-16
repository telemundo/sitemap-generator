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

# use Colorama to allow color output to the terminal
init()

# parse the CLI information
parser = OptionParser(usage='usage: %prog [options]')
parser.add_option('-v', action='count', dest='verbosity', default=0, help='increase output verbosity')
parser.add_option('-q', '--quiet', action='store_true', dest='quiet', help='disables all output')
parser.add_option('-c', '--config', dest='config', default='config.yaml', type='string', help='YAML configuration file (default: config.yaml)')
parser.add_option('-b', '--domain', dest='base_domain', default='msnlatino.telemundo.com', type='string',
                  help='base domain (default: msnlatino.telemundo.com)')
(options, args) = parser.parse_args()

def log(message, verbosity=1):
    ''' Logging interface '''
    levels = [{ 'label': 'error', 'color': 'red' },
              { 'label': 'warn', 'color': 'yellow' },
              { 'label': 'info', 'color': 'white' },
              { 'label': 'debug', 'color': 'cyan' },
              { 'label': 'trace', 'color': 'green' }]
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
        parser.error('%s is missing the "publisher" tree root' % input_file)
    if 'domain' not in config['publisher'] or ('domain' in config['publisher'] and config['publisher']['domain'] is None):
        parser.error('%s is missing the "publisher:domain" parameter' % input_file)
    if 'proxy' not in config['publisher'] or ('proxy' in config['publisher'] and config['publisher']['proxy'] is None):
        config['publisher']['proxy'] = None

    if 'mainsite' not in config:
        parser.error('%s is missing the "mainsite" tree root' % input_file)
    if 'domain' not in config['mainsite'] or ('domain' in config['mainsite'] and config['mainsite']['domain'] is None):
        parser.error('%s is missing the "mainsite:domain" parameter' % input_file)
    if 'proxy' not in config['mainsite'] or ('proxy' in config['mainsite'] and config['mainsite']['proxy'] is None):
        config['mainsite']['proxy'] = None

    if 'binary' not in config:
        config['binary'] = {}
    if 'phantomjs' not in config['binary'] or ('phantomjs' in config['binary'] and config['binary']['phantomjs'] is None):
        config['binary']['phantomjs'] = 'phantomjs'
    if 'convert' not in config['binary'] or ('convert' in config['binary'] and config['binary']['convert'] is None):
        config['binary']['convert'] = 'convert'

    if 'path' not in config:
        config['path'] = {}
    if 'assets' not in config['path'] or ('assets' in config['path'] and config['path']['assets'] is None):
        config['path']['assets'] = 'web/assets'
    if 'rasterizejs' not in config['path'] or 'rasterizejs' in config['path'] and config['path']['rasterizejs'] is None:
        config['path']['rasterizejs'] = '%s/lib/rasterize.js' % (script_dir)

    return config

def request(record, url, redir=False):
    ''' Request processor '''
    log('request [%s]' % (url), verbosity=2)
    image_dir = '%s' % (record['url'])
    req = requests.head(url, verify=False)
    if req.status_code in [200] and rasterize(image_dir, url):
        return {
            'name': record['name'],
            'url': record['url'],
            'section': record['cat'],
            'images': image_dir,
            'destination': url,
            'redir': redir,
            'error': False
        }
    elif req.status_code in [301, 302]:
        log('redirect [%s] > %s' % (url, req.headers['location']), verbosity=1)
        if not re.match('^https?:', req.headers['location'], re.IGNORECASE):
            url = 'http://%s/%s' % (script_config['mainsite']['domain'], req.headers['location'].lstrip('/'))
        else:
            url = req.headers['location']
        return request(record, url, True)
    else:
        log('failed [%s] > %s' % (url, req.status_code), verbosity=0)
        return {
            'name': record['name'],
            'url': record['url'],
            'section': record['cat'],
            'images': 'http://placehold.it/300x360/&text=ERROR',
            'destination': url,
            'redir': redir,
            'error': req.status_code
        }

    return None

def rasterize(image_dir, url):
    ''' Image rasterizer '''
    image_path = '%s/%s/%s' % (script_dir, script_config['path']['assets'], image_dir)
    image_raw = '%s/raw.png' % (image_path)
    image_crop = '%s/crop.png' % (image_path)
    image_thumb = '%s/thumb.png' % (image_path)

    download = True
    if os.path.exists(image_raw):
        time_now = time.time()
        time_mod = os.path.getmtime(image_raw)
        difference = int(time_now-time_mod)
        if difference < 86400:
            download = False

    if download is True:
        log('rasterize [%s]' % (image_dir), verbosity=1)
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

# main routine
def main():
    timer_start = datetime.now()
    log('config [domain %s]' % (options.base_domain), verbosity=1)

    records = []
    sections = {}

    log('processing [publisher]', verbosity=3)
    microsite_proxies = None
    if script_config['publisher']['proxy'] is not None:
        microsite_proxies = {
            'http': script_config['publisher']['proxy'],
            'https': script_config['publisher']['proxy'],
        }
    microsite_params = {'category': 'all'}
    microsite_req = requests.get('http://%s/services/listCategoryItems' % (script_config['publisher']['domain']), params=microsite_params, proxies=microsite_proxies)
    log('request [%s]' % (microsite_req.url), verbosity=3)
    if microsite_req.status_code in [200]:
        microsite_xml = microsite_req.text.encode('utf-8')
        microsite_tree = etree.XML(microsite_xml)
        microsite_result = microsite_tree.xpath('/CategoryItemList/categoryItem')
        for microsite in microsite_result:
            microsite_path = microsite.xpath('urlFriendlyShowName')[0].text.lower()
            microsite_name = microsite.xpath('displayName')
            microsite_cname = microsite.xpath('categoryItemName')[0].text
            microsite_section = microsite.xpath('categoryName')[0].text.lower()
            microsite_active = microsite.xpath('isActive')[0].text.lower()
            if microsite_active in ['true']:
                section = None
                if microsite_section not in sections:
                    section_params = {'categoryItem': microsite_section}
                    section_req = requests.get('http://%s/services/findPage' % (script_config['publisher']['domain']), params=section_params, proxies=microsite_proxies)
                    log('request [%s]' % (section_req.url), verbosity=3)
                    if section_req.status_code in [200]:
                        section_xml = section_req.text.encode('utf-8')
                        section_tree = etree.XML(section_xml)
                        section_result = section_tree.xpath('/Page/categoryItem')
                        for section in section_result:
                            section_path = section.xpath('path')[0].text.lower()
                            log('section [%s]' % (section_path), verbosity=1)
                            sections[microsite_section] = section
                    else:
                        sections[microsite_section] = None
                        log('section [%s] > %d' % (microsite_section, section_req.status_code), verbosity=0)
                else:
                    section = sections[microsite_section]
                # only process microsites within a valid section
                if section is not None:
                    log('microsite [%s]' % (microsite_path), verbosity=1)
                    if len(microsite_name) > 0:
                        name = microsite_name[0].text
                    else:
                        name = microsite_cname
                    microsite_section = section.xpath('path')[0].text.lower()
                    metadata = {
                        'name': name,
                        'cat': microsite_section,
                        'path': microsite_path,
                        'url': '%s/%s' % (microsite_section, microsite_path),
                        'source': 'P'
                    }
                    records.append(metadata)
            else:
                log('microsite [%s] > disabled' % (microsite_path), verbosity=2)
    else:
        log('microsite [%s] > %d' % (microsite_path, microsite_req.status_code), verbosity=0)

    section_index = dict((r['cat'], i) for i, r in enumerate(records))
    microsite_index = dict((r['path'], i) for i, r in enumerate(records))

    log('processing [showconfig]', verbosity=3)
    showconfig_proxies = None
    if script_config['mainsite']['proxy'] is not None:
        showconfig_proxies = {
            'http': script_config['mainsite']['proxy'],
            'https': script_config['mainsite']['proxy'],
        }
    showconfig_url = 'http://%s/config/showconfig/showconfig.xml' % (script_config['mainsite']['domain'])
    showconfig_req = requests.get(showconfig_url, proxies=showconfig_proxies)
    log('request [%s]' % (showconfig_req.url), verbosity=3)
    if microsite_req.status_code in [200]:
        showconfig_xml = showconfig_req.text.encode('utf-8')
        showconfig_tree = etree.XML(showconfig_xml)
        showconfigs = showconfig_tree.xpath('/shows/show')
        for showconfig in showconfigs:
            metadata = None
            showconfig_hub = showconfig.get('isHub')
            showconfig_name = showconfig.xpath('fullShowName')[0].text
            showconfig_path = showconfig.xpath('urlFriendlyShowName')[0].text
            if showconfig_hub is None:
                showconfig_path = showconfig_path.lower()
                showconfig_result = showconfig.xpath('showCategory')
                if len(showconfig_result) > 0:
                    showconfig_section = showconfig_result[0].text.lower()
                    microsite_pos = microsite_index.get(showconfig_path, -1)
                    if microsite_pos == -1:
                        log('microsite [%s]' % (showconfig_path), verbosity=1)
                        metadata = {
                            'name': showconfig_name,
                            'cat':  showconfig_section,
                            'path': showconfig_path,
                            'url': '%s/%s' % (showconfig_section, showconfig_path),
                            'type': 'M'
                        }
                    else:
                        log('microsite [%s] > skipped' % (showconfig_path), verbosity=2)
                else:
                    log('section [%s] > skipped' % (showconfig_path), verbosity=2)
            else:
                if showconfig_path and len(showconfig_path) > 0:
                    showconfig_path = showconfig_path.lower()
                    section_pos = section_index.get(showconfig_path, -1)
                    if section_pos == -1:
                        log('section [%s]' % (showconfig_path), verbosity=1)
                        metadata = {
                            'name': showconfig_name,
                            'cat':  showconfig_path,
                            'path': '',
                            'url':  showconfig_path,
                            'source': 'M'
                        }
                    else:
                        log('section [%s] > skipped' % (showconfig_path), verbosity=2)
                else:
                    log('homepage [%s]' % (showconfig_path), verbosity=1)
                    metadata = {
                        'name': showconfig_name,
                        'cat':  '',
                        'path':  '',
                        'url':  '',
                        'source': 'M'
                    }
            if metadata:
                records.append(metadata)
    else:
        log('microsite [%s] > %d' % (showconfig_path, showconfig_req.status_code), verbosity=0)

    images = []
    sortedrecords = sorted(records, key=lambda k: k['url'])
    for record in sortedrecords:
        url = 'http://%s/%s' % (script_config['mainsite']['domain'], record['url'])
        image = request(record, url)
        if image is not None:
            images.append(image)

    log('images [%d]' % (len(images)), verbosity=1)
    if len(images):
        fp = open('%s/sitemap.json' % (script_config['path']['assets']), 'w')
        fp.write(json.dumps(images))
        fp.close()

    timer_end = datetime.now()
    log('runtime [%s]' % (timer_end-timer_start))

if __name__ == "__main__":
    main()

