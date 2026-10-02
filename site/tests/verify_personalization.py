"""Exercise the actual personal-list flow, persistence, settings, APIs, and layouts."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'research/output/site-qa'
OUT.mkdir(parents=True,exist_ok=True)
parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8080');parser.add_argument('--label',default='personal-local');args=parser.parse_args()
results=[]
with sync_playwright() as p:
    browser=p.chromium.launch()
    for width,scheme in [(1280,'light'),(390,'light'),(390,'dark'),(736,'dark')]:
        context=browser.new_context(viewport={'width':width,'height':1000},color_scheme=scheme)
        page=context.new_page();errors=[];responses=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('response',lambda r:responses.append(r))
        page.goto(args.url,wait_until='networkidle')
        expect(page.locator('#ranking-body tr')).to_have_count(20)
        expect(page.locator('#watched-list .watched-row')).to_have_count(6)
        page.screenshot(path=str(OUT/f'{args.label}-{scheme}-{width}-top.png'))
        initial_bytes=sum(len(r.body()) for r in responses if r.status==200)
        assert initial_bytes<512000,initial_bytes
        page.get_by_role('button',name='Start my own list',exact=True).click()
        expect(page.locator('#results')).to_be_hidden()
        expect(page.locator('#watched-list .watched-row')).to_have_count(0)
        page.reload(wait_until='networkidle')
        expect(page.locator('#results')).to_be_hidden()
        expect(page.locator('#watched-list .watched-row')).to_have_count(0)
        page.locator('#show-search').fill('The Office')
        page.get_by_role('button',name='Add The Office (2005)',exact=True).click()
        expect(page.locator('#calculation-status')).to_contain_text('Updated for 1 liked shows')
        expect(page.locator('#ranking-body tr')).to_have_count(20)
        assert 'The Office (2005)' not in page.locator('#ranking-body').inner_text()
        # Repeated rating edits exercise listeners after the server replaces profile data.
        rating=page.get_by_label('Your rating for The Office (2005)',exact=True)
        rating.select_option('-1');expect(page.locator('#results')).to_be_hidden()
        rating.select_option('1');expect(page.locator('#calculation-status')).to_contain_text('Updated for 1 liked shows')
        page.locator('#show-search').fill('Severance')
        page.get_by_role('button',name='Add Severance (2022)',exact=True).click()
        expect(page.locator('#calculation-status')).to_contain_text('Updated for 2 liked shows')
        page.get_by_label('Your rating for Severance (2022)',exact=True).select_option('-1')
        expect(page.locator('#calculation-status')).to_contain_text('1 dislikes')
        page.reload(wait_until='networkidle')
        expect(page.locator('#calculation-status')).to_contain_text('1 dislikes')
        expect(page.get_by_label('Your rating for Severance (2022)',exact=True)).to_have_value('-1')
        assert page.locator('#watched-list .watched-row').count()==2
        page.locator('#model-settings summary').click()
        page.locator('#year-min').fill('2100')
        expect(page.locator('#empty-candidates')).to_be_visible()
        expect(page.locator('#ranking-body tr')).to_have_count(0)
        page.get_by_role('button',name='Reset recommendation settings',exact=True).click()
        expect(page.locator('#ranking-body tr')).to_have_count(20)
        # Invalid zero weights must not leave stale recommendations on display.
        for key in ['text','themes','genres']:
            page.locator(f'#{key}-weight').evaluate('(e)=>{e.value=0;e.dispatchEvent(new Event("input",{bubbles:true}))}')
        expect(page.locator('#calculation-status')).to_contain_text('weight above zero')
        expect(page.locator('#results')).to_be_hidden()
        page.get_by_role('button',name='Reset recommendation settings',exact=True).click()
        expect(page.locator('#ranking-body tr')).to_have_count(20)
        page.locator('#genres-weight').evaluate('(e)=>{e.value=100;e.dispatchEvent(new Event("input",{bubbles:true}))}')
        expect(page.locator('#results')).to_have_attribute('aria-busy','false')
        expect(page.locator('#genres-value')).to_have_text('100')
        # Candidate -> neutral watched -> removed from all recommendations.
        row=page.locator('#ranking-body tr').first
        seen_name=row.locator('.show-link').inner_text()
        row.get_by_role('button',name='Mark '+seen_name,exact=False).click()
        expect(page.locator('#watched-list .watched-row')).to_have_count(3)
        expect(page.locator('#results')).to_have_attribute('aria-busy','false')
        assert seen_name not in page.locator('#ranking-body .show-link').all_text_contents()
        with page.expect_download() as download:
            page.locator('#download-results').click()
        artifact=download.value;assert artifact.suggested_filename=='tv-recommendations.csv'
        artifact.save_as(OUT/f'{args.label}-{width}-export.csv')
        page.get_by_label('Your rating for Severance (2022)',exact=True).select_option('0.7')
        expect(page.locator('#calculation-status')).to_contain_text('2 liked shows')
        page.locator('#map-view').click()
        page.select_option('#axis-x',label='Severance (2022)')
        expect(page.locator('#axis-note')).to_contain_text('Horizontal: Severance.')
        page.locator('#taste-map rect').hover(position={'x':50,'y':50});expect(page.locator('#map-tooltip')).to_be_visible();page.mouse.move(0,0)
        page.locator('#explore').screenshot(path=str(OUT/f'{args.label}-{scheme}-{width}-map.png'))
        page.locator('#findings').screenshot(path=str(OUT/f'{args.label}-{scheme}-{width}-features.png'))
        assert page.evaluate('document.documentElement.scrollWidth')<=width
        assert not errors,errors
        # A separate browser context has no access to this profile.
        other=browser.new_context();other_page=other.new_page();other_page.goto(args.url)
        expect(other_page.locator('#watched-list .watched-row')).to_have_count(6);other.close()
        page.goto(args.url+'/research.html',wait_until='networkidle')
        assert page.locator('.matrix').count()==2
        assert page.evaluate('document.documentElement.scrollWidth')<=width
        for path in ['/model/catalog.json.gz', '/recommender.py', '/server.py', '/rig.yaml',
                     '/data/model/catalog.json.gz', '/backend/recommender.py', '/backend/server.py',
                     '/client/app.js', '/.rig.lock', '/../scripts/analyze.py', '/../pipeline/jobs/analyze.py']:
            assert page.request.get(args.url+path).status==404,path
        invalid=page.request.post(args.url+'/api/recommend',data={'profile':[{'id':-1,'weight':1}]})
        assert invalid.status==400
        results.append({'width':width,'scheme':scheme,'initial_page_bytes':initial_bytes,'errors':errors,'flow':'passed'})
        context.close()
    offline=browser.new_context(java_script_enabled=False);page=offline.new_page();page.goto(args.url);expect(page.locator('noscript')).to_be_visible();offline.close()
    browser.close()
(OUT/f'{args.label}-verification.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))
