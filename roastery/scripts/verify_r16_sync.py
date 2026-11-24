#!/usr/bin/env python3
"""Round 16 builder resync proof for the items round 15 flagged
but did not touch: the page-config, the SelectAll and InsertPress
named queries, and the style-class resource.json formatting.

Method (the round 13 to 15 extraction proof): AST-extract the
builder's assignments and functions from the repo builder, point
PROJ at a scratch tree, call ONLY write_page_config(),
write_named_queries() and write_styles(), and compare the emitted
files byte for byte against both the repo project tree and the
live gateway project tree. The builder's main() is never run and
nothing is written to the gateway.

Checks (98):
- page-config/config.json and resource.json identical.
- SelectAll and InsertPress query.sql and resource.json identical.
- All 92 style-class resource.json files identical, including the
  four lastModificationSignature files and the three trailing
  newline files.

Run with wsvenv python from ~/workspace/ignition-lab.
"""
import ast
import json
import os
import shutil
import sys

REPO = os.path.expanduser('~/workspace/ignition-coffee-lab')
BUILDER = os.path.join(REPO, 'roastery', 'scripts',
                       'build_roastery_v4.py')
SCRATCH = '/home/hatch/workspace/ignition-lab/r16-scratch/proj'
LIVE_PROJ = os.path.join(REPO, 'roastery', 'project', 'Roastery')
GW_PROJ = ('/home/hatch/workspace/ignition-lab/gateway-2027-maker/'
           'data/projects/Roastery')

FAILS = []
PASSES = [0]


def check(name, cond, detail=''):
    PASSES[0] += 1 if cond else 0
    print(('PASS' if cond else 'FAIL'), '|', name,
          ('| ' + str(detail)[:200]) if (detail and not cond) else '')
    if not cond:
        FAILS.append(name)


def load_builder():
    if os.path.exists(SCRATCH):
        shutil.rmtree(SCRATCH)
    os.makedirs(SCRATCH)
    src = open(BUILDER).read()
    tree = ast.parse(src)
    skip = {'LAB', 'GW', 'PROJ', 'SCHEMAS'}

    def assign_names(node):
        names = []
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.append(target.id)
            elif isinstance(target, ast.Tuple):
                names += [e.id for e in target.elts
                          if isinstance(e, ast.Name)]
            else:
                return None
        return names

    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = assign_names(node)
            if names is None or not names or names[0] in skip:
                continue
            nodes.append(node)
        elif isinstance(node, ast.FunctionDef):
            nodes.append(node)
    code = '\n\n'.join(ast.get_source_segment(src, n) for n in nodes)
    ns = {'os': os, 'json': json, 'copy': __import__('copy'),
          'shutil': shutil, 'sys': sys, 'PROJ': SCRATCH,
          'LAB': os.path.expanduser('~/workspace/ignition-lab'),
          'GW': 'x',
          'SCHEMAS': os.path.expanduser(
              '~/workspace/ignition-lab/knowledge/schemas-2027')}
    exec(compile(code, 'builder-extract', 'exec'), ns)
    return ns


def compare(rel):
    emitted = open(os.path.join(SCRATCH, rel), 'rb').read()
    repo = open(os.path.join(LIVE_PROJ, rel), 'rb').read()
    gateway = open(os.path.join(GW_PROJ, rel), 'rb').read()
    check('builder emits %s byte identical to repo and gateway'
          % rel, emitted == repo == gateway,
          'emitted=%d repo=%d gateway=%d'
          % (len(emitted), len(repo), len(gateway)))


def main():
    ns = load_builder()
    ns['write_page_config']()
    ns['write_named_queries']()
    ns['write_styles']()
    page = 'com.inductiveautomation.perspective/page-config'
    compare(page + '/config.json')
    compare(page + '/resource.json')
    for query in ('Batches/SelectAll', 'Events/InsertPress',
                  'Batches/Update', 'Events/SelectByBatch'):
        for filename in ('query.sql', 'resource.json'):
            compare('ignition/named-query/Roastery/%s/%s'
                    % (query, filename))
    styles = ('com.inductiveautomation.perspective/style-classes')
    for name in sorted(os.listdir(os.path.join(LIVE_PROJ, styles))):
        compare('%s/%s/resource.json' % (styles, name))
    print('TOTAL %d PASS, %d FAIL' % (PASSES[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
