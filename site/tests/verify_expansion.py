"""Browser checks for expanded search, feature detail, filters, and saved profiles."""
import argparse,json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8080');parser.add_argument('--label',default='expanded-extra-local');args=parser.parse_args()
OUT=Path(__file__).resolve().parents[2]/'research/output/site-qa'
OUT.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch()
    for width in (1280,390):
        context=browser.new_context(viewport={'width':width,'height':1000},color_scheme='light')
        page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        # Saved v1 profiles have no new metadata filters. They must migrate via defaults.
        old={'version':1,'profile':[{'id':169,'name':'Breaking Bad','year':2008,'weight':1}],
             'settings':{'text':40,'themes':35,'genres':25,'closest':.3,'dislike':.35,'year_min':1990,'runtime_min':25,'rating_min':0,'axis_x':'all','axis_y':'all'},'isExample':False}
        page.goto(args.url);page.evaluate('(x)=>localStorage.setItem("tv-taste-profile-v1",JSON.stringify(x))',old);page.reload()
        expect(page.locator('#watched-list .watched-row')).to_have_count(1)
        expect(page.locator('#results')).to_have_attribute('aria-busy','false')
        expect(page.locator('#ranking-body tr')).to_have_count(20)
        page.locator('#start-list').click();expect(page.locator('#results')).to_be_hidden()
        for title,year in [('Dark',2017),('Planet Earth',2006),('Avatar: The Last Airbender',2005)]:
            page.locator('#show-search').fill(title)
            page.get_by_role('button',name=f'Add {title} ({year})',exact=True).click()
            expect(page.locator('#results')).to_have_attribute('aria-busy','false')
        expect(page.locator('#watched-list .watched-row')).to_have_count(3)
        page.locator('#model-settings summary').click()
        page.select_option('#language-filter','German')
        page.select_option('#type-filter','Scripted')
        expect(page.locator('#results')).to_have_attribute('aria-busy','false')
        expect(page.locator('#show-detail')).to_contain_text('German · Scripted')
        expect(page.locator('#show-detail')).to_contain_text('This show’s theme signals:')
        expect(page.locator('#show-detail')).to_contain_text('Distinctive plot terms:')
        page.select_option('#feature-group','language')
        expect(page.locator('#feature-bars')).to_contain_text('German')
        page.locator('#findings').screenshot(path=str(OUT/f'{args.label}-{width}-languages.png'))
        page.select_option('#feature-group','type')
        for label in ('Scripted','Documentary','Animation'):expect(page.locator('#feature-bars')).to_contain_text(label)
        page.locator('#findings').screenshot(path=str(OUT/f'{args.label}-{width}-formats.png'))
        page.select_option('#language-filter','English');page.select_option('#type-filter','Documentary')
        expect(page.locator('#results')).to_have_attribute('aria-busy','false')
        # Choose the top recommendation rather than retaining a liked show selection.
        page.locator('#ranking-body .show-link').first.click()
        expect(page.locator('#show-detail')).to_contain_text('English · Documentary')
        page.locator('#show-detail').screenshot(path=str(OUT/f'{args.label}-{width}-detail.png'))
        page.locator('#model-settings').screenshot(path=str(OUT/f'{args.label}-{width}-settings.png'))
        page.select_option('#status-filter','Ended');expect(page.locator('#results')).to_have_attribute('aria-busy','false')
        page.locator('#ranking-body .show-link').first.click();expect(page.locator('#show-detail')).to_contain_text('Documentary · Ended')
        assert page.evaluate('document.documentElement.scrollWidth')<=width
        for path in ('/model/vectors.bin.gz','/model/catalog.json.gz'):assert page.request.get(args.url+path).status==404
        audit=page.request.get(args.url+'/data/catalog-audit.json').json();assert audit['searchable_shows']==89594 and audit['themes']==32
        assert not errors,errors
        context.close()
    browser.close()
print('Expansion browser flows passed at 1280px and 390px.')
