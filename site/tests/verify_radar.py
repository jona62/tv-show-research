"""Verify radar math, customization, accessibility, persistence, and responsive views."""
import argparse,json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8084');parser.add_argument('--label',default='radar-local');args=parser.parse_args()
OUT=Path(__file__).resolve().parents[2]/'research/output/site-qa'
OUT.mkdir(parents=True,exist_ok=True)
results=[]
with sync_playwright() as p:
    browser=p.chromium.launch()
    for width,scheme in [(1280,'light'),(390,'light'),(390,'dark'),(736,'dark')]:
        context=browser.new_context(viewport={'width':width,'height':1000},color_scheme=scheme)
        page=context.new_page();errors=[];requests=[]
        page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:requests.append(r.url) if r.method=='POST' else None)
        page.goto(args.url,wait_until='networkidle')
        expect(page.locator('#radar-panel')).to_be_visible();expect(page.locator('#map-panel')).to_be_hidden()
        expect(page.locator('#taste-radar .radar-shape')).to_have_count(3)
        expect(page.locator('#radar-dimension-count')).to_have_text('(8 of 60)')
        expect(page.locator('#radar-table tbody tr')).to_have_count(60)
        # Independent computation from the actual default profile and recorded signals.
        expected=page.evaluate('''()=>{
          const d=JSON.parse(document.getElementById('research-data').textContent).initial;
          const total=d.profile.filter(p=>p.weight>0).reduce((a,p)=>a+p.weight,0);
          return d.profile.filter(p=>p.weight>0).reduce((a,p)=>a+(d.points.find(s=>s.id===p.id).detected_themes.includes('Money / class')?p.weight:0),0)/total*100;
        }''')
        row=page.locator('#radar-table tr[data-feature="Money / class"]')
        expect(row.locator('td').nth(2)).to_contain_text(f'{expected:.1f}%')
        # Pure values include unknowns without fabricating intensity or redistributing weight.
        math_result=page.evaluate('''async()=>{
          const {radarRows}=await import('/assets/scripts/radar.js');
          const a={id:1,summary:'plot',genres:['Drama'],detected_themes:['Crime']};
          const b={id:2,summary:'',genres:[],detected_themes:[]};
          const features=[{group:'themes',feature:'Crime'},{group:'genres',feature:'Genre: Drama'}];
          return radarRows({features,profile:[{id:1,weight:1},{id:2,weight:.35}],points:[a,b]},a,b);
        }''')
        for item in math_result:
            assert item['a']==100 and item['b'] is None
            assert abs(item['profile']-100/1.35)<1e-8
            assert abs(item['coverage']-100/1.35)<1e-8
        page.select_option('#show-select','13417')
        page.select_option('#radar-compare','169')
        expect(page.locator('#radar-legend')).to_contain_text('Ozark (2017)')
        expect(page.locator('#radar-legend')).to_contain_text('Breaking Bad (2008)')
        expect(page.locator('#radar-summary')).to_contain_text('Ozark and Breaking Bad share')
        page.locator('#radar-panel').screenshot(path=str(OUT/f'{args.label}-{scheme}-{width}-default.png'))
        page.locator('#radar-settings summary').click()
        before=len(requests)
        # Change N from eight to three, then twelve; guard both bounds.
        while page.locator('#radar-dimensions input:checked').count()>3:page.locator('#radar-dimensions input:checked').last.uncheck()
        page.locator('#radar-dimensions input:checked').last.click()
        expect(page.locator('#radar-dimension-status')).to_contain_text('between 3 and 12')
        expect(page.locator('#radar-dimensions input:checked')).to_have_count(3)
        while page.locator('#radar-dimensions input:checked').count()<12:page.locator('#radar-dimensions input:not(:checked)').first.check()
        page.locator('#radar-dimensions input:not(:checked)').first.click()
        expect(page.locator('#radar-dimensions input:checked')).to_have_count(12)
        expect(page.locator('#taste-radar .radar-dot')).to_have_count(36)
        custom=page.locator('#radar-dimensions input:checked').evaluate_all('(els)=>els.map(e=>e.value)')
        page.select_option('#show-select','182')
        assert custom==page.locator('#radar-dimensions input:checked').evaluate_all('(els)=>els.map(e=>e.value)')
        page.locator('#radar-settings summary').click()
        page.locator('#radar-panel').screenshot(path=str(OUT/f'{args.label}-{scheme}-{width}-12.png'))
        page.select_option('#radar-preset','themes');expect(page.locator('#radar-dimension-count')).to_have_text('(8 of 32)')
        page.select_option('#radar-preset','genres');expect(page.locator('#radar-dimension-count')).to_have_text('(8 of 28)')
        assert len(requests)==before,'Radar-only controls must not request a new recommendation ranking.'
        page.locator('#radar-values summary').click();expect(page.locator('#radar-table')).to_be_visible()
        page.locator('#radar-table').screenshot(path=str(OUT/f'{args.label}-{scheme}-{width}-table.png'))
        page.locator('#map-view').click();expect(page.locator('#taste-map rect')).to_be_visible()
        page.select_option('#axis-x','169');expect(page.locator('#results')).to_have_attribute('aria-busy','false')
        page.locator('#radar-view').click();expect(page.locator('#taste-radar')).to_be_visible()
        page.select_option('#radar-preset','mixed')
        page.get_by_label('Your rating for Ozark (2017)',exact=True).select_option('-1')
        expect(page.locator('#calculation-status')).to_contain_text('1 dislikes')
        page.locator('#example-list').click();expect(page.locator('#calculation-status')).to_contain_text('6 liked shows')
        page.locator('#start-list').click();expect(page.locator('#results')).to_be_hidden()
        page.locator('#show-search').fill('Breaking Bad');page.get_by_role('button',name='Add Breaking Bad (2008)',exact=True).click()
        expect(page.locator('#results')).to_have_attribute('aria-busy','false')
        page.select_option('#show-select','169')
        expect(page.locator('#taste-radar .radar-shape')).to_have_count(2)
        expect(page.locator('#radar-summary')).to_contain_text('Add another liked show')
        page.reload(wait_until='networkidle');expect(page.locator('#watched-list .watched-row')).to_have_count(1)
        expect(page.locator('#taste-radar')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth')<=width
        assert not errors,errors
        results.append({'width':width,'scheme':scheme,'radar':'passed','errors':errors})
        context.close()
    browser.close()
(OUT/f'{args.label}-verification.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))
