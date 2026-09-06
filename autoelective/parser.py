#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# filename: parser.py
# modified: 2019-09-09

import re
from lxml import etree
from .course import Course

_regexBzfxSida = re.compile(r'\?sida=(\S+?)&sttp=(?:bzx|bfx)')


def get_tree_from_response(r):
    return etree.HTML(r.text) # 不要用 r.content, 否则可能会以 latin-1 编码

def get_tree(content):
    return etree.HTML(content)

def get_tables(tree):
    return tree.xpath('.//table[contains(concat(" ", normalize-space(@class), " "), " datagrid ")]')

def cell_text(cell):
    return ''.join(cell.itertext()).strip()

def get_table_header(table):
    rows = table.xpath('.//tr[contains(concat(" ", normalize-space(@class), " "), " datagrid-header ")]')
    return [cell_text(c) for c in rows[0].xpath('./th | ./td')] if rows else []

def get_table_trs(table):
    return table.xpath('.//tr[contains(concat(" ", normalize-space(@class), " "), " datagrid-odd ") or contains(concat(" ", normalize-space(@class), " "), " datagrid-even ")]')

def get_title(tree):
    title = tree.find('.//head/title')
    if title is None: # 双学位 sso_login 后先到 主修/辅双 选择页，这个页面没有 title 标签
        return None
    return title.text

def get_errInfo(tree):
    tds = tree.xpath(".//table//table//table//td")
    assert len(tds) == 1
    td = tds[0]
    strong = td.getchildren()[0]
    assert strong.tag == 'strong' and strong.text in ('出错提示:', '提示:')
    return "".join(td.xpath('./text()')).strip()

def get_tips(tree):
    tips = tree.xpath('.//td[@id="msgTips"]')
    if len(tips) == 0:
        return None
    td = tips[0].xpath('.//table//table//td')[1]
    return "".join(td.xpath('.//text()')).strip()

def get_sida(r):
    return _regexBzfxSida.search(r.text).group(1)

def get_courses(table):
    header = get_table_header(table)
    trs = get_table_trs(table)
    ixs = tuple(map(header.index, ["课程名","班号","开课单位"]))
    cs = []
    for tr in trs:
        t = tr.xpath('./th | ./td')
        name, class_no, school = (cell_text(t[ix]) for ix in ixs)
        c = Course(name, class_no, school)
        cs.append(c)
    return cs

def get_courses_with_detail(table):
    header = get_table_header(table)
    trs = get_table_trs(table)
    ixs = tuple(map(header.index, ["课程名","班号","开课单位","限数/已选","补选"]))
    cs = []
    for tr in trs:
        t = tr.xpath('./th | ./td')
        name, class_no, school, status, _ = (cell_text(t[ix]) for ix in ixs)
        status = tuple(map(int, status.split("/")))
        links = t[ixs[-1]].xpath('.//a/@href')
        href = links[0] if links else None
        c = Course(name, class_no, school, status, href)
        cs.append(c)
    return cs

def get_election_states(table):
    header = get_table_header(table)
    if '选课状态' not in header:
        raise ValueError('Selected-course table has no election state column')
    ix = header.index('选课状态')
    return {course: cell_text(row.xpath('./th | ./td')[ix])
            for course, row in zip(get_courses(table), get_table_trs(table))}
