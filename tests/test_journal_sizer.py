import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from types import SimpleNamespace

from journal_report import EMPTY_COVERAGE, report_row
from journal_sizer import (JournalSizer, SizerError, _spread_order, detect_antibot, is_own_prefix,
                           issns_from_fields, issns_from_page, normalize_base_url)


class FakeResponse:
    def __init__(self, text, url='https://fake/?q=1'):
        self.text = text
        self.url = url


def make_sizer(url, **kwargs):
    return JournalSizer(1, 'Teste', url, 'ojs', delay=0, **kwargs)


def urlset(*locs):
    return '<urlset>' + ''.join(f'<url><loc>{loc}</loc></url>' for loc in locs) + '</urlset>'


class HelpersTest(unittest.TestCase):
    def test_issn_checksum_rejects_phones_and_year_ranges(self):
        self.assertEqual(issns_from_fields('0034-8910', '3061-7985', '2020-2021', 'ISSN: 0102311x'),
                         ['0034-8910', '0102-311X'])

    def test_issn_from_page_only_after_label(self):
        body = ('<span>ISSN printed version:</span> 0034-8910 <span>ISSN online version:</span> 1518-8787'
                '<p>Tel./Fax: +55 11 0034-8910</p>')
        self.assertEqual(issns_from_page(body), ['0034-8910', '1518-8787'])
        self.assertEqual(issns_from_page('<p>Tel.: 0034-8910</p>'), [])

    def test_normalize_base_url(self):
        self.assertEqual(normalize_base_url('https://x.com/index.php/EDUCA/issue/archive', 'ojs'),
                         'https://x.com/index.php/EDUCA')
        self.assertEqual(normalize_base_url('https://x.com/secretariado/issue/view/80', 'ojs'),
                         'https://x.com/secretariado')
        self.assertEqual(normalize_base_url('https://x.com/ojs/index.php/ejhr/about/', 'ojs'),
                         'https://x.com/ojs/index.php/ejhr')
        self.assertEqual(normalize_base_url('https://www.scielo.br/j/rsp/i/2026.v60/', 'scielo'),
                         'https://www.scielo.br/j/rsp')

    def test_spread_order_covers_all_starting_at_extremes(self):
        order = _spread_order(37)
        self.assertEqual(sorted(order), list(range(37)))
        self.assertEqual(order[:3], [0, 18, 9])


class SitemapTest(unittest.TestCase):
    def test_counts_only_own_journal_and_merges_galleys(self):
        sizer = make_sizer('https://site.com/index.php/rev/issue/archive')
        body = urlset(
            'https://site.com/index.php/rev/issue/view/1',
            'https://site.com/index.php/rev/issue/view/1/5',       # PDF da edição inteira
            'https://www.site.com/index.php/rev/article/view/10',
            'https://site.com/index.php/rev/article/view/10/99',   # galé do mesmo artigo
            'http://site.com/index.php/rev/article/view/11',
            'https://site.com/index.php/outra/article/view/12',    # outro periódico do mesmo OJS
        )
        sizer._fetch = lambda url, timeout=None: FakeResponse(body)
        out = sizer._ojs_sitemap()
        self.assertEqual((out['articles'], out['issues'], out['exact']), (2, 1, True))
        self.assertTrue(sizer.warnings)

    def test_locale_segment_counts_as_journal_root(self):
        sizer = make_sizer('https://site.com/index.php/rev')
        body = urlset('https://site.com/index.php/rev/pt_br/article/view/1',
                      'https://site.com/index.php/rev/en/article/view/2',
                      'https://site.com/index.php/rev/article/view/3',
                      'https://site.com/index.php/ra/article/view/4')  # periódico de 2 letras no mesmo site
        sizer._fetch = lambda url, timeout=None: FakeResponse(body)
        self.assertEqual(sizer._ojs_sitemap()['articles'], 3)

    def test_two_letter_journals_under_portal_are_not_locales(self):
        sizer = make_sizer('https://malque.pub/ojs')
        body = urlset('https://malque.pub/ojs/index.php/mr/article/view/1',
                      'https://malque.pub/ojs/index.php/ah/article/view/2')
        sizer._fetch = lambda url, timeout=None: FakeResponse(body)
        with self.assertRaises(SizerError):
            sizer._ojs_sitemap()

    def test_portal_without_matching_journal_fails(self):
        sizer = make_sizer('https://site.com/ojs/index.php')
        body = urlset('https://site.com/ojs/index.php/a/article/view/1',
                      'https://site.com/ojs/index.php/b/article/view/2')
        sizer._fetch = lambda url, timeout=None: FakeResponse(body)
        with self.assertRaises(SizerError):
            sizer._ojs_sitemap()


class OAITest(unittest.TestCase):
    PAGE1 = ('<OAI-PMH><ListIdentifiers>'
             '<header status="deleted"><identifier>a/1</identifier><setSpec>rev:ART</setSpec></header>'
             '<header><identifier>a/2</identifier><setSpec>rev:ART</setSpec><setSpec>driver</setSpec></header>'
             '<header><identifier>a/3</identifier><setSpec>rev:ED</setSpec></header>'
             '<resumptionToken expirationDate="x"\n completeListSize="6"\n cursor="0">tok1</resumptionToken>'
             '</ListIdentifiers></OAI-PMH>')
    PAGE2 = ('<OAI-PMH><ListIdentifiers>'
             '<header><identifier>a/4</identifier><setSpec>rev:ART</setSpec></header>'
             '<header><identifier>a/5</identifier><setSpec>rev:ART</setSpec></header>'
             '<header><identifier>a/6</identifier><setSpec>rev:ART</setSpec></header>'
             '<resumptionToken completeListSize="6" cursor="3"></resumptionToken>'
             '</ListIdentifiers></OAI-PMH>')

    def setUp(self):
        self.sizer = make_sizer('https://site.com/index.php/rev')
        self.sizer._fetch = lambda url, timeout=None: FakeResponse(self.PAGE2 if 'tok1' in url else self.PAGE1)

    def test_paginates_and_ignores_deleted(self):
        out = self.sizer._ojs_oai(True)
        self.assertEqual((out['articles'], out['exact'], out['pages']), (5, True, 2))

    def test_first_page_only_extrapolates(self):
        out = self.sizer._ojs_oai(False)
        self.assertEqual((out['articles'], out['exact']), (4, False))  # 6 x 2/3 ativos

    def test_follows_redirect_that_drops_query_string(self):
        requested = []

        def fetch(url, timeout=None):
            requested.append(url)
            if url.startswith('https://site.com/'):  # domínio antigo: 302 sem a query
                return FakeResponse('<OAI-PMH><error code="badVerb"/></OAI-PMH>', url='https://ojs.site.com/rev/oai')
            return FakeResponse(self.PAGE2 if 'tok1' in url else self.PAGE1, url=url)

        self.sizer._fetch = fetch
        out = self.sizer._ojs_oai(True)
        self.assertEqual(out['articles'], 5)
        self.assertEqual(requested[1], 'https://ojs.site.com/rev/oai?verb=ListIdentifiers&metadataPrefix=oai_dc')
        self.assertTrue(requested[2].startswith('https://ojs.site.com/rev/oai?verb=ListIdentifiers&resumptionToken='))

    def test_rejects_aggregated_portal(self):
        page = self.PAGE1.replace('rev:ED', 'outra:ART').replace('rev:ART</setSpec><setSpec>driver', 'x:ART')
        self.sizer._fetch = lambda url, timeout=None: FakeResponse(page)
        with self.assertRaises(SizerError):
            self.sizer._ojs_oai(False)


class ScieloNotFoundTest(unittest.TestCase):
    LIST = ('<a class="collectionLink " href="/j/osoc/?ilang=en"><strong class="journalTitle">'
            'Organizações &amp; Sociedade</strong></a>')

    def sizer(self, name):
        sizer = JournalSizer(1, name, 'https://www.scielo.br/j/os/', 'scielo', delay=0)
        pages = {'status=current': self.LIST, 'status=no-current': ''}

        def fetch(url, timeout=None):
            if url.endswith('/grid'):
                raise requests_http_error(404, {})
            return FakeResponse(next(v for k, v in pages.items() if url.endswith(k)))

        sizer._fetch = fetch
        return sizer

    def test_suggests_right_url_found_by_title(self):
        with self.assertRaisesRegex(SizerError, r'URL certa é https://www.scielo.br/j/osoc/'):
            self.sizer('ORGANIZAÇÕES & SOCIEDADE')._scielo_grid()

    def test_says_when_title_is_not_in_scielo(self):
        with self.assertRaisesRegex(SizerError, 'nenhuma revista do SciELO tem esse título'):
            self.sizer('REME')._scielo_grid()


class FakeJsonResponse:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def crossref_journal(title, issns, dois):
    return {'title': title, 'ISSN': issns, 'counts': {'total-dois': dois}}


class CrossrefTest(unittest.TestCase):
    def test_title_search_needs_single_exact_match(self):
        sizer = JournalSizer(1, 'Brazilian Journal of Development', 'https://x.com/rev', delay=0)
        items = [crossref_journal('Brazilian Journal of Development', ['2525-8761', '2525-8761'], 26641),
                 crossref_journal('Brazilian Journal of Development', [], 0),
                 crossref_journal('Brazilian Journal of Development Studies', ['1234-5679'], 50)]
        sizer._fetch = lambda url, timeout=None: FakeJsonResponse({'message': {'items': items}})
        out = sizer._crossref()
        self.assertEqual((out['articles'], out['issn'], out['exact']), (26641, '2525-8761', False))

    def test_generic_names_are_not_searched(self):
        sizer = JournalSizer(1, 'Home', 'https://x.com/rev', delay=0)
        with self.assertRaises(SizerError):
            sizer._crossref()

    def test_uses_registered_issn(self):
        sizer = JournalSizer(1, 'AMBIENTE & SOCIEDADE', 'https://x.com/rev', issns=['1809-4422'], delay=0)
        sizer._fetch = lambda url, timeout=None: FakeJsonResponse(
            {'message': crossref_journal('Ambiente & sociedade', ['1809-4422'], 1291)})
        out = sizer._crossref()
        self.assertEqual((out['articles'], out['confidence']), (1291, 'media'))
        self.assertEqual(sizer.warnings, [])

    def test_issn_of_another_journal_lowers_confidence(self):
        sizer = JournalSizer(1, 'MALQUE Publishing', 'https://malque.pub/ojs', issns=['2318-1265'], delay=0)
        sizer._fetch = lambda url, timeout=None: FakeJsonResponse(
            {'message': crossref_journal('Journal of Animal Behaviour and Biometeorology', ['2318-1265'], 427)})
        self.assertEqual(sizer._crossref()['confidence'], 'baixa')
        self.assertIn('Journal of Animal Behaviour', sizer.warnings[0])


class TocCountTest(unittest.TestCase):
    def test_full_count_when_few_issues(self):
        sizer = make_sizer('https://site.com/rev', full_threshold=40)
        out = sizer._count_tocs([f'i{i}' for i in range(10)], lambda url: 7)
        self.assertEqual((out['articles'], out['exact'], out['method']), (70, True, 'archive_full'))

    def test_failed_tocs_are_extrapolated(self):
        sizer = make_sizer('https://site.com/rev')
        out = sizer._count_tocs(['a', 'b', 'c', 'd'], lambda url: None if url == 'd' else 10)
        self.assertEqual((out['articles'], out['exact'], out['issues_failed']), (40, False, 1))

    def test_uniform_sample_stops_early(self):
        sizer = make_sizer('https://site.com/rev', sample_size=12, full_threshold=40)
        read = []
        out = sizer._count_tocs([f'i{i}' for i in range(300)], lambda url: read.append(url) or 15)
        self.assertEqual((out['articles'], out['margin'], out['method']), (4500, 0, 'archive_sample'))
        self.assertEqual(len(read), 12)

    def test_heterogeneous_sample_grows_up_to_threshold(self):
        sizer = make_sizer('https://site.com/rev', sample_size=12, full_threshold=40)
        sizes = [5, 60] * 150
        out = sizer._count_tocs(list(range(300)), lambda i: sizes[i] if i % 7 else 120)
        self.assertEqual(out['issues_read'], 40)
        self.assertEqual(out['confidence'], 'baixa')

    def test_ojs_toc_ignores_links_to_other_journals(self):
        sizer = make_sizer('https://site.com/index.php/rev')
        page = ('<a href="/index.php/rev/article/view/1">A</a>'
                '<a href="https://site.com/index.php/rev/article/view/1/9">PDF</a>'
                '<a href="../../article/view/2">B</a>'
                '<a href="https://site.com/index.php/outra/article/view/3">Outra</a>'
                '<a href="https://externo.org/rev/article/view/4">Externo</a>')
        sizer._fetch_text_or_none = lambda url: page
        self.assertEqual(sizer._ojs_toc_count('https://site.com/index.php/rev/issue/view/5'), 2)


class AntibotTest(unittest.TestCase):
    def response(self, status, headers=None, text=''):
        return SimpleNamespace(status_code=status, headers=headers or {}, text=text)

    def test_detects_cloudflare_challenge_header_and_page(self):
        self.assertEqual(detect_antibot(self.response(403, {'cf-mitigated': 'challenge'})), 'cloudflare')
        self.assertEqual(detect_antibot(self.response(503, text='<title>Just a moment...</title>')), 'cloudflare')

    def test_detects_other_providers(self):
        self.assertEqual(detect_antibot(self.response(403, {'X-Sucuri-ID': '1'})), 'sucuri')
        self.assertEqual(detect_antibot(self.response(403, {'Server': 'ddos-guard'})), 'ddos-guard')
        self.assertEqual(detect_antibot(self.response(403, text='<div class="g-recaptcha">')), 'captcha')

    def test_plain_errors_are_not_antibot(self):
        self.assertIsNone(detect_antibot(self.response(403, text='Forbidden')))
        self.assertIsNone(detect_antibot(self.response(404, {'cf-mitigated': 'challenge'})))
        self.assertIsNone(detect_antibot(self.response(200, text='just a moment...')))

    def test_blocked_site_is_flagged_even_with_crossref_count(self):
        sizer = make_sizer('https://site.com/index.php/rev')
        blocked = requests_http_error(403, {'cf-mitigated': 'challenge'})

        def fetch(url, timeout=None):
            if 'crossref' in url:
                return FakeJsonResponse({'message': crossref_journal('Teste', ['1809-4422'], 100)})
            sizer._count_request(blocked.response)
            raise blocked

        sizer.issns = ['1809-4422']
        sizer._fetch = fetch
        sizer._ojs_issue_list = lambda: {'issues': 0}
        result = sizer.measure()
        self.assertEqual((result['status'], result['method'], result['blocked_by']), ('ok', 'crossref', 'cloudflare'))
        self.assertIn('bloqueio anti-bot', result['details']['strategies']['sitemap']['error'])


def requests_http_error(status, headers):
    import requests
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers)
    response._content = b''
    return requests.HTTPError(response=response)


class OwnPrefixTest(unittest.TestCase):
    def test_registered_and_published_roots(self):
        keys = {'studiespublicacoes.com.br/ojs/sees', 'ojs.studiespublicacoes.com.br/ojs/sees'}
        self.assertTrue(is_own_prefix('https://ojs.studiespublicacoes.com.br/ojs/index.php/sees', keys))
        self.assertTrue(is_own_prefix('https://studiespublicacoes.com.br/ojs/index.php/sees/pt_br', keys))
        self.assertFalse(is_own_prefix('https://rsdjournal.org/index.php/rsd', keys))
        self.assertFalse(is_own_prefix('', keys))


class ReportRowTest(unittest.TestCase):
    AVG = {'mean_capped': 2.0}
    JOURNAL = SimpleNamespace(id=1, name='Rev', active=True, source_type='ojs', url='https://x')

    def estimate(self, articles, blocked_by=None, status='ok'):
        return SimpleNamespace(status=status, articles_count=articles, blocked_by=blocked_by, details='{}',
                               is_exact=False)

    def coverage(self, **kwargs):
        cov = dict(EMPTY_COVERAGE, **kwargs)
        cov['articles'] = cov['analyzed'] + cov['no_pdf'] + cov['errors'] + cov['queued']
        return cov

    def test_extractable_journal(self):
        row = report_row(self.JOURNAL, self.estimate(100), self.coverage(analyzed=40, no_pdf=10, queued=20,
                                                                         emails_found=90), self.AVG)
        self.assertEqual((row['situation'], row['to_analyze'], row['not_discovered'], row['progress']),
                         ('extraivel', 50, 30, 50.0))
        self.assertEqual((row['emails_expected'], row['emails_to_extract'], row['emails_lost_antibot'],
                          row['emails_lost_no_pdf']), (200, 100, 0, 20))

    def test_blocked_journal_moves_remaining_to_unreachable(self):
        row = report_row(self.JOURNAL, self.estimate(1000, blocked_by='cloudflare'), self.coverage(), self.AVG)
        self.assertEqual((row['situation'], row['emails_to_extract'], row['emails_lost_antibot']),
                         ('bloqueado', 0, 2000))

    def test_more_analyzed_than_site_never_goes_negative(self):
        row = report_row(self.JOURNAL, self.estimate(10), self.coverage(analyzed=15), self.AVG)
        self.assertEqual((row['to_analyze'], row['not_discovered'], row['progress']), (0, 0, 100.0))

    def test_db_is_floor_when_site_estimate_is_too_low(self):
        row = report_row(self.JOURNAL, self.estimate(100), self.coverage(analyzed=150, queued=30), self.AVG)
        self.assertEqual((row['articles_site'], row['site_exact'], row['to_analyze']), (180, False, 30))
        self.assertIn('abaixo dos artigos próprios', row['warnings'][0])

    def test_exact_site_count_is_kept_even_if_db_has_more(self):
        est = self.estimate(100)
        est.is_exact = True
        row = report_row(self.JOURNAL, est, self.coverage(analyzed=150, queued=30), self.AVG)
        self.assertEqual((row['articles_site'], row['site_exact'], row['to_analyze']), (100, True, 0))
        self.assertIn('mais que os 100 do site', row['warnings'][0])

    def test_unmeasured_journal_uses_what_db_knows(self):
        row = report_row(self.JOURNAL, None, self.coverage(analyzed=5, errors=2, queued=3), self.AVG)
        self.assertEqual((row['situation'], row['to_analyze'], row['progress'], row['emails_expected']),
                         ('nao_medido', 5, None, None))


if __name__ == '__main__':
    unittest.main()
