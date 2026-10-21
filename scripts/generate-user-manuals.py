#!/usr/bin/env python3
"""Regenerate screenshot-backed OpenTradingCore Trade/Tenant/Platform ZH+EN PDF manuals.

Default: build six PDF files from checked-in screenshots, with zero API writes.
Optional --capture refreshes safe public Trade and fixture-backed Platform screenshots.
Explicit --capture-tenant-live/--capture-trader-login require --allow-demo-writes.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
NAMES = {
    'trade': 'OpenTradingCore_Trading_Web_User_Guide_',
    'tenant': 'OpenTradingCore_Tenant_Management_User_Guide_',
    'platform': 'OpenTradingCore_Platform_User_Guide_',
}


def call(args: list[str], cwd: pathlib.Path, env: dict[str, str]):
    print('RUN', cwd.name, ' '.join(args[:3]), flush=True)
    subprocess.run(args, cwd=cwd, env=env, check=True)


def page_counts(paths: list[pathlib.Path]):
    # macOS has a system PDF renderer and PDFKit; require proper page counts.
    swift = shutil.which('swift')
    if swift:
        script = ('import Foundation; import PDFKit; '
                  'for path in CommandLine.arguments.dropFirst() { '
                  'guard let pdf = PDFDocument(url: URL(fileURLWithPath: path)), pdf.pageCount > 0 '
                  'else { fputs("INVALID PDF "+path+"\\n",stderr); exit(3) }; '
                  'print(String(pdf.pageCount)) }')
        result = subprocess.run([swift, '-e', script, *map(str, paths)], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError('PDFKit validation failed: ' + result.stderr[-800:])
        values = [int(x) for x in result.stdout.splitlines() if x.strip().isdigit()]
        if len(values) != len(paths):
            raise RuntimeError('PDFKit returned an unexpected count: ' + result.stdout[-500:])
        return values
    pdfinfo = shutil.which('pdfinfo')
    if pdfinfo:
        import re
        return [int(re.search(r'^Pages:\s+(\d+)', subprocess.check_output([pdfinfo, str(p)], text=True), re.M).group(1)) for p in paths]
    raise RuntimeError('PDF validation requires macOS PDFKit (swift) or poppler pdfinfo')


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=['all', *NAMES], default='all')
    parser.add_argument('--output', help='Directory containing six versioned PDF files and manifest.json')
    parser.add_argument('--repo-base', help='Parent directory containing dc-trade-web, dc-saas-tenant-web, dc-saas-platform-web')
    parser.add_argument('--capture', action='store_true', help='Refresh read-only Trade/public and fixture-backed Platform screenshots')
    parser.add_argument('--capture-tenant-live', action='store_true', help='Create a disposable Demo tenant and recapture the bilingual tenant manual (writes Demo business data)')
    parser.add_argument('--capture-trader-login', action='store_true', help='Create a disposable trader login and recapture account/screens (writes Demo user data)')
    parser.add_argument('--allow-demo-writes', action='store_true', help='Explicit permission for the two account-creating screenshot flows')
    args = parser.parse_args()
    if (args.capture_tenant_live or args.capture_trader_login) and not args.allow_demo_writes:
        parser.error('Demo account registration requires --allow-demo-writes; default generation never creates accounts')
    possible = [pathlib.Path(args.repo_base).expanduser() if args.repo_base else None,
                REPO / '.work', REPO.parent, REPO.parent / '.work']
    base = next((p for p in possible if p is not None and (p/'dc-trade-web').is_dir() and (p/'dc-saas-tenant-web').is_dir() and (p/'dc-saas-platform-web').is_dir()), None)
    if base is None:
        parser.error('UI repositories not found; use --repo-base /path/to/parent/repositories')
    chosen = list(NAMES) if args.scope == 'all' else [args.scope]
    dirs = {'trade':base/'dc-trade-web','tenant':base/'dc-saas-tenant-web','platform':base/'dc-saas-platform-web'}
    common = base/'site-playwright-qa'/'node_modules'
    env = os.environ.copy()
    env['NODE_PATH'] = str(common) + os.pathsep + env.get('NODE_PATH','')
    env['TZ'] = 'Asia/Shanghai'
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    out = pathlib.Path(args.output).expanduser().resolve() if args.output else (REPO/'generated-user-manuals'/stamp).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if args.capture and 'platform' in chosen:
        call(['node', 'qa/capture-user-manual.cjs'], dirs['platform'], env)
    if args.capture and 'trade' in chosen:
        call(['node', 'qa/capture-trading-web-guide.cjs'], dirs['trade'], env)
    if args.capture_tenant_live and 'tenant' in chosen:
        call(['node','qa/capture-user-manual.cjs','--execute'],dirs['tenant'],env)
    if args.capture_trader_login and 'trade' in chosen:
        call(['node','qa/capture-trading-web-guide-auth.cjs','--execute'],dirs['trade'],env)
    specs = []
    if 'trade' in chosen:
        d = dirs['trade']
        call(['python3','docs/user-manual/trading-web/build-guide.py'],d,env)
        call(['node','qa/render-trading-web-guide.cjs'],d,env)
        call(['node','qa/build-trading-web-guide-en.cjs'],d,env)
        for lang in ('ZH','EN'):
            specs.append(('trade',lang,d/'docs/user-manual/trading-web'/f'{NAMES["trade"]}{lang}.pdf'))
    if 'tenant' in chosen:
        d=dirs['tenant'];call(['node','qa/build-user-manual-pdf.cjs'],d,env)
        for lang in ('ZH','EN'):
            specs.append(('tenant',lang,d/'public/help'/f'{NAMES["tenant"]}{lang}.pdf'))
    if 'platform' in chosen:
        d=dirs['platform'];call(['node','qa/build-user-manual-pdf.cjs'],d,env)
        for lang in ('ZH','EN'):
            specs.append(('platform',lang,d/'docs/user-manual'/f'{NAMES["platform"]}{lang}.pdf'))
    copies=[]
    for name,lang,source in specs:
        if not source.is_file() or source.stat().st_size < 12000 or source.open('rb').read(5) != b'%PDF-':
            raise RuntimeError('Missing or invalid manual: '+str(source))
        target=out/source.name;shutil.copyfile(source,target)
        copies.append((name,lang,target))
    pages=page_counts([p for _,_,p in copies])
    entries=[{'module':name,'language':lang,'filename':p.name,'pages':num,'bytes':p.stat().st_size,
              'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for (name,lang,p),num in zip(copies,pages)]
    manifest={'generatedAt':dt.datetime.now(dt.timezone.utc).isoformat(),
              'screenshots': 'refreshed read-only where requested' if args.capture else 'version-controlled snapshots (no recapture)',
              'realDemoWrite':bool(args.capture_tenant_live or args.capture_trader_login),
              'count':len(entries),'manuals':entries}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    if shutil.which('zip'):
        subprocess.run(['zip','-q','-j',str(out/('OpenTradingCore_User_Manuals_'+args.scope+'.zip')),*[str(p) for _,_,p in copies]],check=True)
    print('\nUSER_MANUALS_COMPLETE',len(entries),'PDFs',out,flush=True)
    for e in entries:
        print(e['module'],e['language'],e['pages'],'pages',e['bytes'],'bytes',e['filename'])
    return 0


if __name__=='__main__':
    try:sys.exit(run())
    except (subprocess.CalledProcessError,RuntimeError,OSError) as exc:
        print('USER_MANUALS_FAILED:',str(exc),file=sys.stderr)
        sys.exit(1)
