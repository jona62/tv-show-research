"""Exercise matrix detail interactions using offline, real-source WebKit pages.

Mobile taps verify browser event wiring; they are not native Safari verification.
"""
import json
import re
import unittest
from unittest.mock import patch

if __package__:
    from . import test_comparison_layout as layout
else:
    import test_comparison_layout as layout

BASE_DOCUMENT = layout.source_document
LONG_SUMMARY = 'The characters follow a difficult trail and discover a new place. ' * 90


def source_document(long_summary=False, page_scroll=False):
    def episode(show, season, number, rating, name, summary='', source='TMDB', votes=None):
        return {'id': show * 100 + season * 10 + number, 'season': season, 'number': number,
                'rating': rating, 'name': name, 'summary': summary, 'rating_source': source,
                'rating_votes': votes, 'image': '/poster.svg' if number == 1 else None}

    episodes = {
        42184: [episode(42184, 1, 1, 8.4, 'Primal premiere',
                       '<p>' + (LONG_SUMMARY if long_summary else 'A difficult journey with <em>a new ally</em>.') + '</p>', votes=1234),
                episode(42184, 1, 2, None, 'Unrated Primal episode', 'No scores have arrived.', source=None),
                episode(42184, 1, 4, 6.6, 'A later Primal episode', source='TVmaze'),
                episode(42184, 2, 1, 9, 'Primal second-season premiere', 'The second season begins.'),
                episode(42184, 2, 2, 7, 'Another Primal episode'),
                episode(42184, 2024, 1, 7.2, 'Primal year-season premiere')],
        563: [episode(563, 1, 1, 9.3, 'Clone Wars premiere', 'A different episode at the same position.', source='TVmaze', votes=86),
              episode(563, 1, 2, 6.7, 'Clone Wars follow-up', source='TVmaze'),
              episode(563, 2, 1, 8, 'Clone Wars second-season premiere', source='TVmaze'),
              episode(563, 2, 3, None, 'Unrated Clone Wars episode', source=None)],
    }
    document = BASE_DOCUMENT(unavailable=True).replace('compare-view=timeline', 'compare-view=grid&compare-inverted=0')
    replacement = '      const fixtureEpisodes=' + json.dumps(episodes) + ';\n      const episodes=id=>fixtureEpisodes[id]||[];\n'
    document, changed = re.subn(r'      const episodes=id=>.*?(?=      window.disposeComparison=)',
                                lambda match: replacement, document, count=1, flags=re.S)
    if changed != 1:
        raise AssertionError('The shared episode fixture hook changed.')
    return document + ('<div style="height:1500px" aria-hidden="true"></div>' if page_scroll else '')


class ComparisonMatrixDetails(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.webkit.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def open_fixture(self, width=1280, zoom=100, long_summary=False, page_scroll=False):
        # Reuse the real source/asset routes without importing its TestCase into
        # this module's discovery or duplicating its existing fifteen tests.
        with patch.object(layout, 'source_document', lambda *args, **kwargs: source_document(long_summary, page_scroll)):
            page, errors = layout.ComparisonCardLayout.open_fixture(self, width, zoom, unavailable=True)
        page.locator('.rating-table').wait_for()
        return page, errors

    @staticmethod
    def choose(page, key, value):
        layout.ComparisonCardLayout.choose(page, key, value)

    @staticmethod
    def episode_cell(page, show, season=1, number=1):
        return page.locator(f'.rating-table [data-show-id="{show}"][data-episode="{show * 100 + season * 10 + number}"]')

    @staticmethod
    def average_cell(page, show, season):
        return page.locator(f'.rating-table [data-show-id="{show}"][data-season="{season}"]:not([data-episode])')

    def visible_tip(self, page):
        tip = page.get_by_role('tooltip')
        tip.wait_for(state='visible')
        self.assertEqual(page.locator('.ratings-tooltip').count(), 1)
        return tip

    def assert_episode(self, page, show_name, code, name, rating=None):
        tip = self.visible_tip(page)
        self.assertEqual(tip.locator('.ratings-tooltip-code').text_content(), show_name + ' · ' + code)
        self.assertEqual(tip.locator('.ratings-tooltip-body > b').text_content(), name)
        if rating is not None:
            self.assertIn(rating, tip.locator('.ratings-tooltip-score').text_content())
        self.assertEqual(tip.locator('.ratings-tooltip-summary').count(), 1)
        return tip

    def test_real_mouse_hover_and_keyboard_focus_show_the_correct_episode_for_each_show(self):
        page, errors = self.open_fixture()
        primal = self.episode_cell(page, 42184)
        self.assertIsNone(primal.get_attribute('title'), 'The rich tooltip replaces the overlapping native title')
        primal.hover()
        tip = self.assert_episode(page, 'Primal', 'S1 E1', 'Primal premiere', '8.4')
        self.assertIn('TMDB', tip.text_content())
        self.assertIn('1,234 votes', tip.text_content())
        self.assertEqual(tip.locator('img').get_attribute('src'), '/poster.svg')
        self.assertEqual(tip.locator('.ratings-tooltip-summary').text_content(), 'A difficult journey with a new ally.')
        self.assertEqual(tip.locator('.ratings-tooltip-summary em').count(), 0)
        self.assertEqual(primal.get_attribute('aria-describedby'), tip.get_attribute('id'))
        clone = self.episode_cell(page, 563)
        clone.hover()
        tip = self.assert_episode(page, 'Star Wars: The Clone Wars', 'S1 E1', 'Clone Wars premiere', '9.3')
        self.assertIn('TVmaze', tip.text_content())
        self.assertIn('86 votes', tip.text_content())
        self.assertIsNone(primal.get_attribute('aria-describedby'))
        primal.focus()
        self.assert_episode(page, 'Primal', 'S1 E1', 'Primal premiere', '8.4')
        primal.hover()
        page.mouse.move(5, 5)
        page.wait_for_timeout(200)
        self.assert_episode(page, 'Primal', 'S1 E1', 'Primal premiere', '8.4')
        primal.hover(); clone.focus()
        page.mouse.move(5, 5)
        page.wait_for_timeout(200)
        self.assert_episode(page, 'Star Wars: The Clone Wars', 'S1 E1', 'Clone Wars premiere')
        primal.focus()
        primal.press('Escape')
        self.assertFalse(page.get_by_role('tooltip').is_visible())
        self.assertIsNone(primal.get_attribute('aria-describedby'))
        primal.press('Enter')
        self.assert_episode(page, 'Primal', 'S1 E1', 'Primal premiere')
        primal.press('Escape'); primal.press('Space')
        self.assert_episode(page, 'Primal', 'S1 E1', 'Primal premiere')
        self.assertFalse(errors, errors)

    def test_season_averages_describe_rated_counts_without_inventing_an_episode(self):
        page, errors = self.open_fixture()
        self.choose(page, 'mode', 'all')
        for show, name, score, count in ((42184, 'Primal', '7.5', '2 rated of 3 episodes'),
                                         (563, 'Star Wars: The Clone Wars', '8', '2 rated of 2 episodes')):
            with self.subTest(show=show):
                cell = self.average_cell(page, show, 1)
                self.assertIsNone(cell.get_attribute('data-episode'))
                cell.hover()
                tip = self.visible_tip(page)
                self.assertIn(name, tip.locator('.ratings-tooltip-code').text_content())
                self.assertIn('Season 1', tip.locator('.ratings-tooltip-code').text_content())
                self.assertEqual(tip.locator('.ratings-tooltip-body > b').text_content(), 'Season average')
                self.assertIn(score, tip.locator('.ratings-tooltip-score').text_content())
                self.assertIn(count, tip.text_content())
                self.assertEqual(tip.locator('img').count(), 0)
                self.assertEqual(tip.locator('.ratings-tooltip-summary').text_content(), count)
                self.assertNotIn('A difficult journey', tip.text_content())
                self.assertNotIn('votes', tip.text_content())
                if show == 42184:
                    self.assertIn('TMDB / TVmaze', tip.locator('.ratings-tooltip-score').text_content())
                self.assertNotRegex(tip.locator('.ratings-tooltip-code').text_content(), r'\bE\d+\b')
        self.average_cell(page, 42184, 2024).focus()
        tip = self.visible_tip(page)
        self.assertIn('2024 season', tip.locator('.ratings-tooltip-code').text_content())
        self.assertIn('1 rated of 1', tip.text_content())
        page.keyboard.press('Escape')
        self.assertGreater(page.locator('.ratings-average[title*="average episode rating"]').count(), 0)
        self.assertEqual(page.locator('.ratings-average button').count(), 0, 'Overall averages retain their existing plain-cell behavior')
        self.assertFalse(errors, errors)

    def test_touch_taps_show_unrated_details_and_empty_positions_do_not_open_a_tip(self):
        page, errors = self.open_fixture(390, 85)
        primal = self.episode_cell(page, 42184)
        primal.tap()
        self.assert_episode(page, 'Primal', 'S1 E1', 'Primal premiere')
        unrated = self.episode_cell(page, 42184, number=2)
        unrated.tap()
        tip = self.assert_episode(page, 'Primal', 'S1 E2', 'Unrated Primal episode')
        self.assertIn('Awaiting audience ratings', tip.text_content())
        self.assertNotIn('out of 10', tip.locator('.ratings-tooltip-score').text_content())
        gap = page.locator('.rating-table tbody tr').filter(has=page.get_by_role('rowheader', name=re.compile(r'^Primal\b'))).locator('.rating-empty').first
        gap.tap()
        self.assertFalse(page.get_by_role('tooltip').is_visible())
        self.assertGreater(page.locator('.rating-table .rating-empty').count(), 3)
        primal.tap()
        page.locator('#compare-search').tap()
        self.assertFalse(page.get_by_role('tooltip').is_visible())
        self.assertFalse(errors, errors)

    def test_long_episode_popup_can_scroll_and_escape_without_losing_its_details(self):
        page, errors = self.open_fixture(long_summary=True)
        cell = self.episode_cell(page, 42184)
        cell.hover()
        tip = self.assert_episode(page, 'Primal', 'S1 E1', 'Primal premiere')
        self.assertGreater(tip.evaluate('node=>node.scrollHeight'), tip.evaluate('node=>node.clientHeight'))
        rect = tip.bounding_box()
        page.mouse.move(rect['x'] + rect['width'] / 2, rect['y'] + rect['height'] / 2)
        page.mouse.wheel(0, 300)
        page.wait_for_function('document.querySelector(".ratings-tooltip").scrollTop>0')
        self.assertTrue(tip.is_visible(), 'Scrolling details does not dismiss their popup')
        self.assertIn(LONG_SUMMARY.strip(), tip.text_content())
        cell.focus(); cell.press('Escape')
        self.assertFalse(tip.is_visible())
        self.assertIsNone(cell.get_attribute('aria-describedby'))
        self.assertFalse(errors, errors)

    def test_scrolling_a_focused_matrix_cell_offscreen_dismisses_its_popup(self):
        page, errors = self.open_fixture(page_scroll=True)
        cell = self.episode_cell(page, 42184)
        cell.focus()
        tip = self.visible_tip(page)
        cell.evaluate('node=>window.scrollTo(0,scrollY+node.getBoundingClientRect().bottom+100)')
        page.wait_for_function('document.querySelector("[data-episode=\\"4218411\\"]").getBoundingClientRect().bottom<0')
        tip.wait_for(state='hidden')
        self.assertIsNone(cell.get_attribute('aria-describedby'))
        page.evaluate('window.scrollTo(0,0)')
        cell.press('Enter')
        self.assert_episode(page, 'Primal', 'S1 E1', 'Primal premiere')
        self.assertFalse(errors, errors)

    def test_view_invert_scope_reorder_and_season_changes_cleanup_and_rebind_a_single_tip(self):
        page, errors = self.open_fixture()
        cell = self.episode_cell(page, 42184)
        cell.focus()
        self.visible_tip(page)
        cell.evaluate('node=>{window.oldMatrixCell=node;window.oldMatrixTip=document.querySelector(".ratings-tooltip")}')
        self.choose(page, 'view', 'timeline')
        self.assertFalse(page.evaluate('window.oldMatrixTip.isConnected'))
        self.assertIn('Primal', page.evaluate('window.oldMatrixCell.title'))
        self.assertEqual(page.locator('.ratings-tooltip').count(), 1)
        page.evaluate('window.oldMatrixCell.dispatchEvent(new Event("pointerenter"));window.oldMatrixCell.dispatchEvent(new Event("focus"))')
        self.assertTrue(page.evaluate('window.oldMatrixTip.hidden'))
        self.choose(page, 'view', 'grid')
        self.episode_cell(page, 42184).focus()
        self.assert_episode(page, 'Primal', 'S1 E1', 'Primal premiere')
        page.locator('[data-action="invert"]').click()
        self.episode_cell(page, 563).focus()
        self.assert_episode(page, 'Star Wars: The Clone Wars', 'S1 E1', 'Clone Wars premiere')
        self.choose(page, 'mode', 'all')
        self.average_cell(page, 42184, 1).focus()
        self.assertIn('2 rated of 3 episodes', self.visible_tip(page).text_content())
        page.keyboard.press('Escape')
        page.locator('[data-action="move"][data-id="563"][data-direction="-1"]').click()
        self.average_cell(page, 563, 1).focus()
        self.assertIn('Star Wars: The Clone Wars', self.visible_tip(page).text_content())
        self.choose(page, 'mode', 'single')
        page.locator('[data-compare-season="42184"]').select_option('2')
        self.episode_cell(page, 42184, season=2).focus()
        self.assert_episode(page, 'Primal', 'S2 E1', 'Primal second-season premiere', '9.0')
        page.locator('[data-action="averages"]').click()
        self.episode_cell(page, 42184, season=2).focus()
        self.assert_episode(page, 'Primal', 'S2 E1', 'Primal second-season premiere')
        self.assertEqual(page.locator('.ratings-average').count(), 0)
        cell = page.locator('.rating-table [data-episode="4218421"]')
        page.evaluate('window.disposeComparison()')
        self.assertEqual(page.locator('.ratings-tooltip').count(), 0)
        cell.click()
        self.assertEqual(page.locator('.ratings-tooltip').count(), 0)
        self.assertIsNone(cell.get_attribute('aria-describedby'))
        self.assertFalse(errors, errors)


if __name__ == '__main__':
    unittest.main()
