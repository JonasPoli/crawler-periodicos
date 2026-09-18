"""
Mede o tamanho de um periódico (edições e artigos) direto no site, ANTES de processá-lo.

É a base para estimar quantos e-mails um periódico deve render:
    e-mails estimados = artigos no site x média de e-mails por PDF do sistema

Estratégias, das mais baratas às mais caras (vence a primeira que trouxer uma contagem):
  OJS
    1. sitemap         {base}/sitemap lista edições e artigos publicados (1 requisição, exato)
    2. oai             OAI-PMH ListIdentifiers, contando registros não excluídos (exato ou extrapolado)
    3. archive_*       /issue/archive + contagem dos sumários (todos, ou amostra espalhada no tempo)
  SciELO
    1. articlemeta     API ArticleMeta do SciELO pelo ISSN (total de documentos e edições, exato)
    2. archive_*       /grid + contagem dos sumários (todos, ou amostra)
  Último recurso (site fora do ar, bloqueio anti-bot...)
    crossref           total de DOIs do periódico no Crossref, pelo ISSN ou pelo título exato (estimado)

Uso:
    python journal_sizer.py --all                 # varre todos os periódicos ativos
    python journal_sizer.py --id 129 --id 3       # periódicos específicos
    python journal_sizer.py --missing             # só os que ainda não têm medição válida
    python journal_sizer.py --stale-days 30       # sem medição válida nos últimos 30 dias
    python journal_sizer.py --all --full          # sem amostragem: lê todos os sumários quando cair no arquivo
    python journal_sizer.py --id 129 --dry-run    # mede e mostra, sem gravar no banco
"""
import argparse
import datetime
import html
import json
import logging
import math
import os
import re
import statistics
import sys
import tempfile
import threading
import time
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse, quote

import requests
from requests.adapters import HTTPAdapter
from sqlalchemy import func, text
from urllib3.util.retry import Retry

from database import get_session, init_db, Journal, JournalSizeEstimate
from ojs_crawler import OJSCrawler
from user_agents import get_headers, create_configured_session

logger = logging.getLogger('journal_sizer')

ARTICLEMETA_API = 'https://articlemeta.scielo.org/api/v1'
CROSSREF_API = 'https://api.crossref.org'
# Coleção do ArticleMeta por domínio do SciELO
SCIELO_COLLECTIONS = {
    'scielo.br': 'scl',
    'scielo.org.ar': 'arg',
    'scielo.cl': 'chl',
    'scielo.org.co': 'col',
    'scielo.org.mx': 'mex',
    'scielo.pt': 'prt',
    'scielosp.org': 'spa',
}

ISSN_RE = re.compile(r'\b(\d{4})-?(\d{3}[\dXx])\b')
HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.I)
# Primeiro segmento após /view/ é o id do artigo/edição; o segundo (opcional) é a galé (PDF, HTML...)
OJS_ARTICLE_RE = re.compile(r'^(.*?)/article/view/([^/?#]+)(?:/[^?#]*)?$')
OJS_ISSUE_RE = re.compile(r'^(.*?)/issue/view/([^/?#]+)(?:/[^?#]*)?$')


# Listas de periódicos do SciELO por domínio (baixadas só quando uma URL dá 404)
_scielo_titles_cache = {}


class SizerError(Exception):
    """Falha esperada de uma estratégia (endpoint ausente, resposta inesperada...)."""


# --- Helpers de URL / ISSN ---

def detect_platform(url):
    host = urlparse(url or '').netloc.lower()
    return 'scielo' if 'scielo' in host else 'ojs'


def normalize_base_url(url, platform):
    """Reduz a URL cadastrada à raiz do periódico (sem /issue/archive, /about, ...)."""
    u = (url or '').strip().split('#')[0].split('?')[0]
    if platform == 'scielo':
        m = re.match(r'^(https?://[^/]+/j/[^/]+)', u)
        return m.group(1) if m else u.rstrip('/')
    u = re.sub(r'/(issue|article|about|search|oai|sitemap|announcement|information|login|user)(/.*)?$', '', u, flags=re.I)
    u = re.sub(r'/index$', '', u.rstrip('/'))
    return u.rstrip('/')


def _url_key(url):
    """Chave para comparar URLs ignorando esquema, www., index.php e barra final."""
    u = re.sub(r'^https?://', '', (url or '').strip().lower())
    u = re.sub(r'^www\.', '', u)
    return u.replace('/index.php', '').rstrip('/')


# "pt_br", "en_us"... ou só o idioma; lista fechada porque há periódicos com caminho de 2 letras (ex.: /mr, /ra)
LOCALE_RE = re.compile(r'[a-z]{2}_[a-z]{2}|en|es|pt|fr|de|it')


def _journal_key(url, base_key):
    """Chave da raiz de periódico de uma URL; um segmento de idioma logo após a raiz cadastrada
    (OJS 3.4+: .../revista/pt_br/article/view/1) conta como a própria raiz."""
    key = _url_key(url)
    rest = key[len(base_key) + 1:] if base_key and key.startswith(base_key + '/') else ''
    return base_key if LOCALE_RE.fullmatch(rest) else key


def _valid_issn(digits):
    total = sum(int(d) * (8 - i) for i, d in enumerate(digits[:7]))
    check = (11 - total % 11) % 11
    return digits[7].upper() == ('X' if check == 10 else str(check))


def issns_from_fields(*values):
    """Extrai ISSNs válidos (dígito verificador), normalizados como NNNN-NNNN, de campos livres."""
    found = []
    for v in values:
        for a, b in ISSN_RE.findall(str(v or '')):
            issn = f"{a}-{b.upper()}"
            if _valid_issn(a + b) and issn not in found:
                found.append(issn)
    return found


def issns_from_page(body):
    """ISSNs que aparecem logo após o rótulo 'ISSN' (evita telefones, CEPs e intervalos de anos)."""
    plain = re.sub(r'<[^>]+>', ' ', body)
    return issns_from_fields(*re.findall(r'ISSN[^0-9]{0,80}(\d{4}-\d{3}[\dXx])', plain, re.I))


def _norm_title(title):
    plain = unicodedata.normalize('NFKD', title or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', plain).strip()


GENERIC_TITLE_WORDS = {
    'journal', 'revista', 'review', 'reviews', 'research', 'studies', 'science', 'sciences',
    'brazilian', 'brasileira', 'brasileiro', 'international', 'the', 'and', 'for', 'para',
    'del', 'dos', 'das', 'cadernos', 'caderno',
}


def _titles_share_word(a, b):
    def words(t):
        return {w for w in _norm_title(t).split() if len(w) > 2 and w not in GENERIC_TITLE_WORDS}
    return bool(words(a) & words(b))


# Trechos que as proteções anti-bot mais comuns põem na página de desafio/bloqueio
ANTIBOT_BODY_MARKERS = (
    ('cloudflare', ('challenge-platform', 'cf-chl', 'just a moment...', 'attention required! | cloudflare',
                    'cf-error-details')),
    ('sucuri', ('sucuri website firewall',)),
    ('imperva', ('_incapsula_resource', 'incapsula incident')),
    ('ddos-guard', ('ddos-guard',)),
    ('aws-waf', ('awswaf',)),
    ('captcha', ('g-recaptcha', 'h-captcha', 'hcaptcha.com', 'recaptcha/api')),
)


def detect_antibot(response):
    """Nome da proteção anti-bot que barrou a resposta (desafio JS, captcha, WAF), ou None."""
    if response is None or response.status_code not in (401, 403, 429, 503):
        return None
    headers = {k.lower(): v.lower() for k, v in response.headers.items()}
    if headers.get('cf-mitigated') == 'challenge':
        return 'cloudflare'
    if 'x-sucuri-id' in headers or 'x-sucuri-block' in headers:
        return 'sucuri'
    if 'ddos-guard' in headers.get('server', ''):
        return 'ddos-guard'
    if 'x-amzn-waf-action' in headers:
        return 'aws-waf'
    try:
        body = response.text[:30000].lower()
    except Exception:
        return None
    return next((name for name, markers in ANTIBOT_BODY_MARKERS if any(m in body for m in markers)), None)


def _short_error(exc):
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        antibot = detect_antibot(exc.response)
        if antibot:
            return f"HTTP {exc.response.status_code} (bloqueio anti-bot: {antibot})"
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, requests.Timeout):
        return "timeout"
    if isinstance(exc, requests.ConnectionError):
        return "falha de conexão"
    return f"{type(exc).__name__}: {str(exc)[:200]}"


def _has_count(out):
    return 'error' not in out and out.get('articles') is not None


# --- Medição ---

class JournalSizer:
    def __init__(self, journal_id, name, url, source_type='ojs', issns=(), agent_type='rotate',
                 full=False, sample_size=12, full_threshold=40, oai_max_pages=40, delay=0.2):
        self.journal_id = journal_id
        self.name = name
        self.url = (url or '').strip()
        self.source_type = source_type
        self.platform = detect_platform(self.url)
        self.base = normalize_base_url(self.url, self.platform)
        self.issns = list(issns)
        self.agent_type = agent_type
        self.full = full
        self.sample_size = max(2, sample_size)
        self.full_threshold = full_threshold
        self.oai_max_pages = oai_max_pages
        self.delay = delay

        self.requests = 0
        self.http_errors = 0
        self.antibot = Counter()  # respostas barradas por proteção anti-bot, por fornecedor
        self.warnings = []
        self.strategies = {}
        self._issue_urls = None
        # Raízes de URL que pertencem ao periódico: a cadastrada e as que o site de fato publica
        # (ex.: domínio novo após migração). O relatório usa para separar artigos próprios dos vazados.
        self.journal_keys = {_url_key(self.base)}

        self.session = create_configured_session(agent_type=agent_type, pool_size=4)
        # Sem repetir timeout de leitura: servidor lento (sitemap gerado na hora) continua lento,
        # e a estratégia seguinte resolve mais rápido
        adapter = HTTPAdapter(max_retries=Retry(total=2, read=False, backoff_factor=0.5,
                                                status_forcelist=[429, 502, 503, 504]),
                              pool_connections=4, pool_maxsize=4)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        self.session.hooks['response'].append(self._count_request)

    @classmethod
    def from_journal(cls, journal, **kwargs):
        return cls(journal.id, journal.name, journal.url, journal.source_type,
                   issns_from_fields(journal.issn, journal.issn_print, journal.issn_electronic), **kwargs)

    def _count_request(self, response, *args, **kwargs):
        self.requests += 1
        if response.status_code >= 400:
            self.http_errors += 1
        antibot = detect_antibot(response)
        if antibot:
            self.antibot[antibot] += 1

    def _fetch(self, url, timeout=(10, 30)):
        if self.agent_type == 'rotate':
            self.session.headers.update(get_headers('rotate'))
        resp = self.session.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp

    def _fetch_text_or_none(self, url):
        try:
            return self._fetch(url).text
        except Exception:
            return None

    def measure(self):
        start = time.time()
        result = {
            'status': 'failed', 'platform': self.platform, 'method': None,
            'issues_count': None, 'articles_count': None, 'is_exact': False,
            'confidence': None, 'error': None, 'blocked_by': None,
        }
        if self.source_type and self.source_type != self.platform:
            self.warnings.append(f"Cadastrado como '{self.source_type}', mas a URL é de {self.platform}")

        chosen = None
        site_ok = False
        if not self.url.startswith('http'):
            result['error'] = f"URL inválida: {self.url!r}"
        else:
            try:
                chosen = self._measure_scielo() if self.platform == 'scielo' else self._measure_ojs()
                site_ok = chosen is not None
                if not chosen:
                    # Último recurso, independente do site (fora do ar, bloqueio anti-bot...)
                    crossref = self._run('crossref', self._crossref)
                    if _has_count(crossref):
                        chosen = self._pick('crossref', crossref)
            except Exception as e:  # uma revista problemática nunca derruba a varredura
                logger.exception("Erro inesperado medindo periódico %s", self.journal_id)
                result['error'] = f"Erro inesperado: {type(e).__name__}: {e}"

        if self.antibot:
            antibot, hits = self.antibot.most_common(1)[0]
            if not site_ok:
                # Nada do site respondeu sem desafio: o crawler também não vai conseguir extrair
                result['blocked_by'] = antibot
            else:
                self.warnings.append(f"{hits} requisição(ões) barrada(s) por anti-bot ({antibot}): "
                                     f"a extração pode falhar em parte")

        if chosen:
            result.update(chosen)
            result['status'] = 'ok'
        elif not result['error']:
            errors = [f"{name}: {out['error']}" for name, out in self.strategies.items() if out.get('error')]
            result['error'] = '; '.join(errors) or 'Nenhuma estratégia retornou contagem'

        result['requests_count'] = self.requests
        result['duration_seconds'] = round(time.time() - start, 2)
        result['details'] = {'base_url': self.base, 'strategies': self.strategies, 'warnings': self.warnings,
                             'journal_keys': sorted(self.journal_keys)}
        return result

    def _run(self, name, fn, *args):
        t0, req0 = time.time(), self.requests
        try:
            out = fn(*args) or {}
        except SizerError as e:
            out = {'error': str(e)}
        except Exception as e:
            out = {'error': _short_error(e)}
        out['requests'] = self.requests - req0
        out['seconds'] = round(time.time() - t0, 2)
        self.strategies[name] = out
        return out

    def _pick(self, method, out, issues=None, confidence=None):
        return {
            'method': method,
            'articles_count': out['articles'],
            'issues_count': out['issues'] if out.get('issues') is not None else issues,
            'is_exact': bool(out.get('exact')),
            'confidence': confidence or out.get('confidence'),
        }

    # --- OJS ---

    def _measure_ojs(self):
        if self.base.endswith('/index.php') or not urlparse(self.base).path.strip('/'):
            self.warnings.append('URL sem o caminho do periódico (parece a raiz de um portal OJS)')

        sitemap = self._run('sitemap', self._ojs_sitemap)
        sitemap_ok = _has_count(sitemap) and sitemap['articles'] > 0
        # Com o sitemap resolvido o OAI só confere (1 página); sem ele, o OAI é paginado para contar tudo
        oai = self._run('oai', self._ojs_oai, not sitemap_ok)

        if sitemap_ok:
            confidence = None
            if _has_count(oai) and oai['articles'] > 0:
                diff = abs(sitemap['articles'] - oai['articles']) / max(sitemap['articles'], oai['articles'])
                if diff > 0.25:
                    self.warnings.append(
                        f"Sitemap ({sitemap['articles']}) e OAI ({oai['articles']}) divergem {diff:.0%}")
                    confidence = 'media'
            return self._pick('sitemap', sitemap, confidence=confidence)

        listing = self._run('archive_issues', self._ojs_issue_list)
        if _has_count(oai) and oai['articles'] > 0:
            return self._pick('oai', oai, issues=listing.get('issues'))

        if self._issue_urls:
            archive = self._run('archive', self._count_tocs, self._issue_urls, self._ojs_toc_count)
            if _has_count(archive):
                if listing.get('http_errors'):
                    archive['exact'] = False
                    return self._pick(archive['method'], archive, confidence='baixa')
                return self._pick(archive['method'], archive)

        # Nenhuma contagem positiva: aceita um zero confirmado (periódico ainda sem artigos publicados)
        for name in ('sitemap', 'oai'):
            if _has_count(self.strategies[name]):
                return self._pick(name, self.strategies[name], issues=listing.get('issues'))
        return None

    def _ojs_sitemap(self):
        body = self._fetch(f"{self.base}/sitemap", timeout=(10, 60)).text
        if '<sitemapindex' in body:
            raise SizerError('sitemap é um índice de vários periódicos (URL de portal?)')
        if '<urlset' not in body:
            raise SizerError('resposta não é um sitemap XML')

        articles, issues = defaultdict(set), defaultdict(set)
        for loc in re.findall(r'<loc>\s*([^<\s]+)\s*</loc>', body):
            loc = html.unescape(loc)
            m = OJS_ARTICLE_RE.match(loc)
            if m:
                articles[self._key(m.group(1))].add(m.group(2))
                continue
            m = OJS_ISSUE_RE.match(loc)
            if m:
                issues[self._key(m.group(1))].add(m.group(2))

        prefix = self._pick_journal_prefix(set(articles) | set(issues), 'sitemap')
        return {
            'articles': len(articles.get(prefix, ())),
            'issues': len(issues.get(prefix, ())),
            'exact': True,
            'confidence': 'alta',
        }

    def _key(self, url):
        return _journal_key(url, _url_key(self.base))

    def _own_prefix(self, prefixes):
        """
        Raiz (host + caminho do periódico) que corresponde à URL cadastrada, ou a única presente.
        Links para outros periódicos do mesmo site ou de outros sites nunca entram na contagem:
        foi esse vazamento que fez versões antigas do crawler baixarem PDFs de fora da revista.
        """
        base_key = _url_key(self.base)
        if base_key in prefixes:
            return base_key
        if len(prefixes) == 1:
            only = next(iter(prefixes))
            self.journal_keys.add(only)
            return only
        return None

    def _pick_journal_prefix(self, prefixes, source):
        if not prefixes:
            return None
        prefix = self._own_prefix(prefixes)
        if prefix is None:
            raise SizerError(f"{source} lista {len(prefixes)} periódicos e nenhum corresponde à URL cadastrada")
        if len(prefixes) > 1:
            self.warnings.append(f"{source}: {len(prefixes)} periódicos no mesmo site; contado só o cadastrado")
        elif prefix != _url_key(self.base):
            self.warnings.append(f"{source}: URLs publicadas em '{prefix}', diferente da cadastrada")
        return prefix

    def _ojs_oai(self, paginate):
        oai_url = f"{self.base}/oai"
        url = f"{oai_url}?verb=ListIdentifiers&metadataPrefix=oai_dc"
        active = deleted = pages = 0
        complete_size = None
        finished = False
        journals = Counter()

        while True:
            resp = self._fetch(url, timeout=(10, 60))
            if '?' not in resp.url and resp.url.rstrip('/') != oai_url:
                # Site mudou de domínio e o redirecionamento descartou os parâmetros: repete no endereço novo
                oai_url = resp.url.rstrip('/')
                if oai_url.endswith('/oai'):
                    self.journal_keys.add(_url_key(oai_url[:-len('/oai')]))
                resp = self._fetch(f"{oai_url}?{url.split('?', 1)[1]}", timeout=(10, 60))
            body = resp.text
            pages += 1
            if '<OAI-PMH' not in body:
                raise SizerError('endpoint OAI não respondeu OAI-PMH')
            err = re.search(r'<error[^>]*code="([^"]+)"', body)
            if err:
                if err.group(1) == 'noRecordsMatch':
                    finished = True
                    break
                raise SizerError(f"OAI retornou erro '{err.group(1)}'")

            for attrs, content in re.findall(r'<header\b([^>]*)>(.*?)</header>', body, re.S):
                if 'deleted' in attrs:
                    deleted += 1
                    continue
                active += 1
                # setSpec "periodico:SECAO" identifica o periódico dono do registro
                spec = re.search(r'<setSpec>([^<:]+):', content)
                if spec:
                    journals[spec.group(1)] += 1

            tok = re.search(r'<resumptionToken([^>]*)>([^<]*)</resumptionToken>', body, re.S)
            if tok and complete_size is None:
                m = re.search(r'completeListSize="(\d+)"', tok.group(1))
                complete_size = int(m.group(1)) if m else None
            token = tok.group(2).strip() if tok else ''
            if not token:
                finished = True
                break
            if not paginate or pages >= self.oai_max_pages:
                break
            url = f"{oai_url}?verb=ListIdentifiers&resumptionToken={quote(token)}"
            time.sleep(self.delay)

        if journals and journals.most_common(1)[0][1] / sum(journals.values()) < 0.9:
            raise SizerError(f"OAI agrega {len(journals)} periódicos (URL de portal?)")

        seen = active + deleted
        if finished:
            articles, exact = active, True
        elif complete_size and seen:
            # completeListSize inclui excluídos: aplica a proporção de ativos vista nas páginas lidas
            articles, exact = round(complete_size * active / seen), False
        else:
            articles, exact = active, False
        return {
            'articles': articles,
            'exact': exact,
            'confidence': 'alta' if exact else 'media',
            'pages': pages,
            'complete_list_size': complete_size,
            'deleted_seen': deleted,
        }

    def _ojs_issue_list(self):
        # Reaproveita a paginação do /issue/archive do crawler; nada é baixado (download_dir é descartável)
        crawler = OJSCrawler(self.base, self.name, download_dir=tempfile.gettempdir(), agent_type=self.agent_type)
        crawler.session = self.session
        errors_before = self.http_errors
        by_prefix = defaultdict(list)
        for item in crawler.get_all_issues():
            m = OJS_ISSUE_RE.match(item['url'] if isinstance(item, dict) else item)
            if not m:
                continue
            # /issue/view/ID/GALLEY (PDF da edição inteira) é a mesma edição
            u = f"{m.group(1)}/issue/view/{m.group(2)}"
            issues = by_prefix[self._key(m.group(1))]
            if u not in issues:
                issues.append(u)

        prefix = self._own_prefix(set(by_prefix))
        urls = by_prefix.get(prefix, []) if prefix else []
        ignored = sum(len(v) for v in by_prefix.values()) - len(urls)
        if ignored:
            self.warnings.append(f"archive: {ignored} edição(ões) de outros periódicos ignorada(s)")
        self._issue_urls = urls
        if not urls:
            raise SizerError('nenhuma edição do periódico encontrada em /issue/archive')
        out = {'issues': len(urls)}
        # O crawler para a paginação em silêncio quando uma página falha (ex.: site limitando acesso)
        errors = self.http_errors - errors_before
        if errors:
            out['http_errors'] = errors
            self.warnings.append(f"archive: {errors} página(s) do arquivo falharam; a lista de edições pode estar incompleta")
        return out

    def _ojs_toc_count(self, issue_url):
        body = self._fetch_text_or_none(issue_url)
        if body is None:
            return None
        by_prefix = defaultdict(set)
        for href in HREF_RE.findall(body):
            full = urljoin(issue_url, html.unescape(href)).split('?')[0].split('#')[0]
            m = OJS_ARTICLE_RE.match(full)
            if m:
                by_prefix[self._key(m.group(1))].add(m.group(2))
        prefix = self._own_prefix(set(by_prefix))
        return len(by_prefix[prefix]) if prefix else 0

    # --- SciELO ---

    @property
    def acron(self):
        return self.base.split('/j/')[-1].strip('/')

    @property
    def collection(self):
        host = urlparse(self.base).netloc.lower()
        return next((code for domain, code in SCIELO_COLLECTIONS.items() if host.endswith(domain)), 'scl')

    def _measure_scielo(self):
        grid = self._run('grid', self._scielo_grid)
        am = self._run('articlemeta', self._scielo_articlemeta, grid.get('issns') or [])

        if _has_count(am) and am['articles'] > 0:
            confidence = None
            grid_issues, am_issues = grid.get('issues'), am.get('issues')
            if grid_issues and am_issues and not (0.5 <= grid_issues / am_issues <= 2):
                self.warnings.append(
                    f"ArticleMeta indica {am_issues} edições e o grid {grid_issues}: confira o ISSN {am['issn']}")
                confidence = 'media'
            return self._pick('articlemeta', am, confidence=confidence)

        if self._issue_urls:
            archive = self._run('archive', self._count_tocs, self._issue_urls, self._scielo_toc_count)
            if _has_count(archive):
                return self._pick(archive['method'], archive)
        return None

    def _scielo_grid(self):
        try:
            body = self._fetch(f"{self.base}/grid").text
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                raise SizerError(self._scielo_not_found_message())
            raise
        marker = f"/j/{self.acron}/i/"
        urls = []
        for href in HREF_RE.findall(body):
            full = urljoin(self.base + '/', html.unescape(href)).split('#')[0].split('?')[0]
            if marker in full and full not in urls:
                urls.append(full)
        self._issue_urls = urls
        if not urls:
            raise SizerError('nenhuma edição encontrada no /grid')
        return {'issues': len(urls), 'issns': issns_from_page(body)}

    def _scielo_not_found_message(self):
        """Explica o 404 do SciELO procurando a revista pelo título nas listas oficiais do site."""
        message = f"não existe revista em /j/{self.acron}/ no SciELO"
        try:
            found = self._scielo_titles().get(_norm_title(self.name))
        except Exception:
            return f"{message} (acrônimo errado na URL ou revista fora do SciELO)"
        if not found:
            return f"{message}, e nenhuma revista do SciELO tem esse título (está fora do SciELO ou o cadastro usa sigla)"
        acron, status = found
        if status == 'current':
            return f"{message}: pelo título, a URL certa é {self._scielo_host}/j/{acron}/ (corrija o cadastro)"
        return f"{message}: pelo título, a revista saiu do SciELO (era /j/{acron}/)"

    @property
    def _scielo_host(self):
        parts = urlparse(self.base)
        return f"{parts.scheme}://{parts.netloc}"

    def _scielo_titles(self):
        """{título normalizado: (acrônimo, 'current' | 'no-current')} das listas de periódicos do SciELO."""
        host = self._scielo_host
        if host not in _scielo_titles_cache:
            titles = {}
            for status in ('current', 'no-current'):
                body = self._fetch(f"{host}/journals/alpha?status={status}", timeout=(10, 60)).text
                for acron, title in re.findall(
                        r'href="/j/([^/"]+)/[^"]*"[^>]*>\s*<strong class="journalTitle">([^<]+)</strong>', body):
                    titles.setdefault(_norm_title(html.unescape(title)), (acron, status))
            _scielo_titles_cache[host] = titles
        return _scielo_titles_cache[host]

    def _scielo_articlemeta(self, page_issns):
        # ISSNs do cadastro primeiro; os da página (cabeçalho) servem de reserva
        candidates = list(dict.fromkeys(self.issns + list(page_issns)))
        if not candidates:
            raise SizerError('sem ISSN no cadastro nem na página da revista para consultar a API')
        for issn in candidates:
            data = self._fetch(f"{ARTICLEMETA_API}/article/identifiers/"
                               f"?collection={self.collection}&issn={issn}&limit=1", timeout=(10, 40)).json()
            total = int((data.get('meta') or {}).get('total') or 0)
            if total > 0:
                issues = self._fetch(f"{ARTICLEMETA_API}/issue/identifiers/"
                                     f"?collection={self.collection}&issn={issn}&limit=1", timeout=(10, 40)).json()
                return {
                    'articles': total,
                    'issues': int((issues.get('meta') or {}).get('total') or 0) or None,
                    'issn': issn,
                    'exact': True,
                    'confidence': 'alta',
                }
        raise SizerError(f"ArticleMeta sem documentos para ISSN {', '.join(candidates)}")

    def _scielo_toc_count(self, issue_url):
        body = self._fetch_text_or_none(issue_url)
        if body is None:
            return None
        # O sumário tem /a/ID/ e /a/ID/abstract/ para o mesmo artigo: conta ids únicos
        return len(set(re.findall(rf'/j/{re.escape(self.acron)}/a/([A-Za-z0-9]+)', body)))

    # --- Crossref (fallback comum, fora do site) ---

    def _crossref(self):
        """Total de DOIs registrados para o periódico. DOI não é exatamente artigo, por isso é estimativa."""
        if self.issns:
            for issn in self.issns:
                try:
                    journal = self._fetch(f"{CROSSREF_API}/journals/{issn}").json()['message']
                except requests.HTTPError as e:
                    if e.response is not None and e.response.status_code == 404:
                        continue
                    raise
                if journal['counts']['total-dois']:
                    return self._crossref_result(journal, issn)
            raise SizerError(f"Crossref sem DOIs para ISSN {', '.join(self.issns)}")

        # Sem ISSN no cadastro: busca pelo título exato, só se o nome for descritivo o bastante
        title = _norm_title(self.name)
        if len(title) < 12 or len(title.split()) < 3:
            raise SizerError('sem ISSN e nome curto demais para buscar pelo título')
        items = self._fetch(f"{CROSSREF_API}/journals?rows=20&query={quote(self.name)}").json()['message']['items']
        hits = {tuple(sorted(set(it['ISSN']))): it for it in items
                if _norm_title(it.get('title')) == title and it.get('ISSN') and it['counts']['total-dois']}
        if len(hits) != 1:
            raise SizerError(f"Crossref: {len(hits)} periódico(s) com o título exato")
        issns, journal = next(iter(hits.items()))
        self.warnings.append(f"ISSN {', '.join(issns)} encontrado pelo título no Crossref (cadastro sem ISSN)")
        return self._crossref_result(journal, issns[0])

    def _crossref_result(self, journal, issn):
        out = {
            'articles': journal['counts']['total-dois'],
            'issues': None,
            'exact': False,
            'confidence': 'media',
            'issn': issn,
            'title': journal.get('title'),
        }
        if not _titles_share_word(journal.get('title'), self.name):
            # Ex.: cadastro de portal com o ISSN de uma das revistas dele
            self.warnings.append(f"ISSN {issn} é de '{journal.get('title')}' no Crossref, "
                                 f"mas o cadastro se chama '{self.name}'")
            out['confidence'] = 'baixa'
        return out

    # --- Contagem pelos sumários (fallback comum) ---

    def _count_tocs(self, issue_urls, counter):
        n = len(issue_urls)
        sampled = not self.full and n > self.full_threshold
        # Amostra espalhada do mais novo ao mais antigo (o tamanho das edições muda com o tempo),
        # ampliada aos poucos enquanto a margem de erro passar de 15%
        order = _spread_order(n) if sampled else list(range(n))
        target = min(self.sample_size, n) if sampled else n

        counts, failed, pos = [], 0, 0
        while True:
            while pos < len(order) and len(counts) + failed < target:
                c = counter(issue_urls[order[pos]])
                pos += 1
                if c is None:
                    failed += 1
                else:
                    counts.append(c)
                time.sleep(self.delay)
            if not sampled or pos >= len(order) or target >= self.full_threshold:
                break
            if len(counts) > 1 and _sample_margin(counts, n) <= 0.15 * statistics.mean(counts) * n:
                break
            target = min(target + 6, self.full_threshold)
        if not counts:
            raise SizerError(f"nenhum sumário pôde ser lido ({failed} falhas)")

        mean = statistics.mean(counts)
        out = {
            'issues': n,
            'issues_read': len(counts),
            'issues_failed': failed,
            'mean_per_issue': round(mean, 2),
            'method': 'archive_sample' if sampled else 'archive_full',
        }
        if sampled:
            estimate, margin = round(mean * n), _sample_margin(counts, n)
            out.update(articles=estimate, exact=False, margin=round(margin),
                       confidence='media' if estimate and margin / estimate <= 0.15 else 'baixa')
        else:
            out.update(articles=round(sum(counts) + mean * failed), exact=failed == 0,
                       confidence='alta' if failed == 0 else ('media' if failed / n <= 0.1 else 'baixa'))
        return out


def _spread_order(n):
    """Índices 0..n-1 numa ordem que cobre a lista inteira cada vez mais fino (sequência de van der Corput)."""
    order, seen, i = [], set(), 0
    while len(order) < n:
        x, denom, k = 0.0, 1.0, i
        while k:
            denom *= 2
            x += (k & 1) / denom
            k >>= 1
        idx = min(n - 1, int(x * n))
        if idx not in seen:
            seen.add(idx)
            order.append(idx)
        i += 1
    return order


def _sample_margin(counts, n):
    """Margem de 95% do total estimado (média x n), com correção de população finita."""
    k = len(counts)
    stdev = statistics.stdev(counts) if k > 1 else 0.0
    return 1.96 * stdev / math.sqrt(k) * math.sqrt(max(0.0, 1 - k / n)) * n


# --- Persistência / consultas ---

_engine = None
_engine_lock = threading.Lock()
_db_write_lock = threading.Lock()


def _get_engine():
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = init_db()  # cria a tabela journal_size_estimates se ainda não existir
        return _engine


def ensure_schema():
    """Garante que a tabela journal_size_estimates exista (roda init_db uma vez por processo)."""
    _get_engine()


def save_estimate(journal_id, result):
    session = get_session(_get_engine())
    try:
        est = JournalSizeEstimate(
            journal_id=journal_id,
            status=result['status'],
            platform=result.get('platform'),
            method=result.get('method'),
            issues_count=result.get('issues_count'),
            articles_count=result.get('articles_count'),
            is_exact=result.get('is_exact', False),
            confidence=result.get('confidence'),
            blocked_by=result.get('blocked_by'),
            requests_count=result.get('requests_count', 0),
            duration_seconds=result.get('duration_seconds', 0),
            details=json.dumps(result.get('details') or {}, ensure_ascii=False, default=str),
            error=result.get('error'),
        )
        with _db_write_lock:
            session.add(est)
            session.commit()
        return est.id
    finally:
        session.close()


def latest_estimates(session, journal_ids=None, only_ok=False):
    """Retorna {journal_id: JournalSizeEstimate} com a medição mais recente de cada periódico."""
    latest_ids = session.query(func.max(JournalSizeEstimate.id)).group_by(JournalSizeEstimate.journal_id)
    if only_ok:
        latest_ids = latest_ids.filter(JournalSizeEstimate.status == 'ok')
    if journal_ids is not None:
        latest_ids = latest_ids.filter(JournalSizeEstimate.journal_id.in_(list(journal_ids)))
    rows = session.query(JournalSizeEstimate).filter(JournalSizeEstimate.id.in_(latest_ids)).all()
    return {r.journal_id: r for r in rows}


def journals_needing_measurement(session, journal_ids=None, stale_days=None, include_inactive=False):
    """Ids dos periódicos sem medição válida (ou com medição mais velha que stale_days)."""
    query = session.query(Journal.id)
    if not include_inactive:
        query = query.filter(Journal.active == True)
    if journal_ids is not None:
        query = query.filter(Journal.id.in_(list(journal_ids)))
    ids = [row[0] for row in query.order_by(Journal.id).all()]
    measured = latest_estimates(session, ids, only_ok=True)
    limit = datetime.datetime.utcnow() - datetime.timedelta(days=stale_days) if stale_days else None
    return [i for i in ids if i not in measured or (limit and measured[i].measured_at < limit)]


# Raiz da URL de um artigo (tudo antes de /article/view/ no OJS ou /a/ no SciELO), em SQL
ARTICLE_PREFIX_SQL = """CASE WHEN instr(a.url, '/article/view/') > 0 THEN substr(a.url, 1, instr(a.url, '/article/view/') - 1)
                WHEN instr(a.url, '/a/') > 0 THEN substr(a.url, 1, instr(a.url, '/a/') - 1)
                ELSE '' END"""


def journal_own_keys(session):
    """
    {journal_id: raízes de URL do periódico}: a cadastrada e as que a medição achou publicadas
    no site (ex.: domínio novo após migração). Artigos fora delas vieram de vazamento.
    """
    keys = {jid: {_url_key(normalize_base_url(url, detect_platform(url)))}
            for jid, url in session.query(Journal.id, Journal.url).all()}
    for est in latest_estimates(session, only_ok=True).values():
        try:
            extra = json.loads(est.details or '{}').get('journal_keys') or []
        except ValueError:
            extra = []
        keys.setdefault(est.journal_id, set()).update(extra)
    return keys


def is_own_prefix(prefix, keys):
    """A raiz de URL de um artigo pertence ao periódico (aceita segmento de idioma, ex.: /pt_br)?"""
    return bool(prefix) and any(_journal_key(prefix, key) == key for key in keys)


# Histograma "e-mails por PDF" agrupado pela raiz da URL do artigo, para separar os PDFs do
# próprio periódico dos que vazaram de outros sites
EMAILS_PER_PDF_SQL = text(f"""
    SELECT e.journal_id,
           {ARTICLE_PREFIX_SQL} AS prefix,
           COALESCE(c.n, 0) AS n,
           COUNT(*) AS pdfs
    FROM articles a
    JOIN editions e ON e.id = a.edition_id
    LEFT JOIN (SELECT article_id, COUNT(*) AS n FROM captured_emails GROUP BY article_id) c
           ON c.article_id = a.id
    WHERE a.status = 'completed'
    GROUP BY 1, 2, 3
""")

_avg_cache = {'at': 0.0, 'value': None}


def _hist_quantile(hist, q, total):
    acc = 0
    for n, c in hist:
        acc += c
        if acc >= q * total:
            return n
    return hist[-1][0]


def system_emails_per_pdf(session, cap_quantile=0.99, max_age=600):
    """
    Média de e-mails encontrados por PDF processado (artigos 'completed'), em todo o sistema.
    Só entram PDFs do próprio periódico (URL do artigo sob a URL da revista): os baixados por
    vazamento para outros sites ficam de fora. 'mean_capped' limita cada PDF ao percentil 99
    (PDFs de edições inteiras, com centenas de e-mails, puxariam a média) e é o valor usado
    nas estimativas.
    """
    if _avg_cache['value'] and time.time() - _avg_cache['at'] < max_age:
        return _avg_cache['value']
    own_keys = journal_own_keys(session)
    own, pdfs_all = Counter(), 0
    for journal_id, prefix, n, pdfs in session.execute(EMAILS_PER_PDF_SQL).fetchall():
        pdfs_all += pdfs
        if is_own_prefix(prefix, own_keys.get(journal_id, ())):
            own[int(n)] += int(pdfs)
    hist = sorted(own.items())
    total = sum(c for _, c in hist)
    if not total:
        return None
    cap = _hist_quantile(hist, cap_quantile, total)
    value = {
        'pdfs': total,
        'pdfs_all': pdfs_all,
        'emails': sum(n * c for n, c in hist),
        'mean': sum(n * c for n, c in hist) / total,
        'mean_capped': sum(min(n, cap) * c for n, c in hist) / total,
        'cap': cap,
        'median': _hist_quantile(hist, 0.5, total),
        'pct_with_email': sum(c for n, c in hist if n > 0) / total,
    }
    _avg_cache.update(at=time.time(), value=value)
    return value


def estimated_emails(articles_count, avg):
    if articles_count is None or not avg:
        return None
    return round(articles_count * avg['mean_capped'])


# --- Execução (varredura e segundo plano) ---

def _journal_specs(journal_ids):
    session = get_session(_get_engine())
    try:
        journals = session.query(Journal).filter(Journal.id.in_(list(journal_ids))).order_by(Journal.id).all()
        return [dict(journal_id=j.id, name=j.name, url=j.url, source_type=j.source_type,
                     issns=issns_from_fields(j.issn, j.issn_print, j.issn_electronic)) for j in journals]
    finally:
        session.close()


def measure_journals(journal_ids, workers=4, dry_run=False, on_result=None, **sizer_opts):
    """Mede os periódicos em paralelo (um por thread) e grava cada resultado assim que termina."""
    specs = _journal_specs(journal_ids)
    results = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(lambda s: JournalSizer(**s, **sizer_opts).measure(), spec): spec for spec in specs}
        for fut in as_completed(futures):
            spec, result = futures[fut], fut.result()
            if not dry_run:
                save_estimate(spec['journal_id'], result)
            logger.info("Journal %s (%s): %s %s artigos via %s (%s req, %ss)%s",
                        spec['journal_id'], spec['name'], result['status'], result['articles_count'],
                        result['method'], result['requests_count'], result['duration_seconds'],
                        f" - {result['error']}" if result['error'] else '')
            results.append((spec, result))
            if on_result:
                on_result(spec, result)
    return results


_bg_lock = threading.Lock()
_bg_state = {'running': False, 'queue': [], 'total': 0, 'done': 0, 'started_at': None, 'finished_at': None}


def enqueue_measurement(journal_ids, **opts):
    """
    Agenda a medição em segundo plano (usado pelo painel ao cadastrar um periódico).
    Uma única thread consome a fila; pedidos feitos durante uma varredura entram na mesma fila.
    """
    with _bg_lock:
        new_ids = [i for i in journal_ids if i not in _bg_state['queue']]
        if not _bg_state['running']:
            _bg_state.update(total=0, done=0, started_at=datetime.datetime.utcnow(), finished_at=None)
        _bg_state['queue'].extend(new_ids)
        _bg_state['total'] += len(new_ids)
        if _bg_state['running']:
            return
        _bg_state['running'] = True
    threading.Thread(target=_bg_worker, kwargs=opts, daemon=True, name='journal-sizer').start()


def _bg_progress(spec, result):
    with _bg_lock:
        _bg_state['done'] += 1


def _bg_worker(**opts):
    while True:
        with _bg_lock:
            batch = list(_bg_state['queue'])
            _bg_state['queue'].clear()
            if not batch:
                # Decide parar sob o mesmo lock do enqueue: nenhum pedido fica órfão na fila
                _bg_state.update(running=False, finished_at=datetime.datetime.utcnow())
                return
        try:
            measure_journals(batch, on_result=_bg_progress, **opts)
        except Exception:
            logger.exception("Falha na medição em segundo plano")


def background_status():
    with _bg_lock:
        return {k: (list(v) if isinstance(v, list) else v) for k, v in _bg_state.items()}


# --- CLI ---

def _fmt(n):
    return '-' if n is None else f"{n:,}".replace(',', '.')


def format_result(spec, result, avg=None):
    name = (spec['name'] or '')[:38]
    head = f"[{spec['journal_id']:>4}] {name:<38} {result['platform']:<6}"
    if result.get('blocked_by'):
        head += f" [BLOQUEADO anti-bot: {result['blocked_by']}]"
    if result['status'] != 'ok':
        return f"{head} FALHOU: {result['error']}"
    strategy = result['details']['strategies'].get('archive', {})
    precision = 'exato' if result['is_exact'] else (f"±{_fmt(strategy['margin'])}" if 'margin' in strategy else 'estimado')
    emails = estimated_emails(result['articles_count'], avg)
    line = (f"{head} {result['method']:<14} edições {_fmt(result['issues_count']):>6}  "
            f"artigos {_fmt(result['articles_count']):>7} ({precision}, {result['confidence']})")
    if emails is not None:
        line += f"  ~{_fmt(emails)} e-mails"
    line += f"  [{result['requests_count']} req, {result['duration_seconds']}s]"
    for w in result['details']['warnings']:
        line += f"\n{'':>7}aviso: {w}"
    return line


def main():
    parser = argparse.ArgumentParser(description="Mede edições e artigos de periódicos direto no site, antes do processamento.")
    parser.add_argument('--id', type=int, action='append', help="Id do periódico (pode repetir)")
    parser.add_argument('--all', action='store_true', help="Todos os periódicos ativos")
    parser.add_argument('--missing', action='store_true', help="Só periódicos sem medição válida")
    parser.add_argument('--stale-days', type=int, help="Periódicos sem medição válida nos últimos N dias")
    parser.add_argument('--include-inactive', action='store_true', help="Inclui periódicos inativos")
    parser.add_argument('--workers', type=int, default=4, help="Periódicos medidos em paralelo (padrão: 4)")
    parser.add_argument('--full', action='store_true', help="Sem amostragem: lê todos os sumários e pagina todo o OAI")
    parser.add_argument('--sample-size', type=int, default=12, help="Sumários lidos na amostragem (padrão: 12)")
    parser.add_argument('--agent', default='rotate', help="Perfil de User-Agent (padrão: rotate)")
    parser.add_argument('--dry-run', action='store_true', help="Não grava no banco")
    parser.add_argument('--json', action='store_true', help="Imprime o resultado completo em JSON")
    args = parser.parse_args()

    if not (args.id or args.all or args.missing or args.stale_days):
        parser.print_help()
        return 1

    os.makedirs('logs', exist_ok=True)
    logging.basicConfig(filename='logs/sizer.log', level=logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    session = get_session(_get_engine())
    try:
        if args.id and not (args.missing or args.stale_days):
            ids = args.id
        elif args.missing or args.stale_days:
            ids = journals_needing_measurement(session, args.id, args.stale_days, args.include_inactive)
        else:
            query = session.query(Journal.id)
            if not args.include_inactive:
                query = query.filter(Journal.active == True)
            ids = [row[0] for row in query.order_by(Journal.id).all()]
        avg = system_emails_per_pdf(session)
    finally:
        session.close()

    if not ids:
        print("Nenhum periódico para medir.")
        return 0

    if avg:
        print(f"Média do sistema: {avg['mean_capped']:.2f} e-mails/PDF (bruta {avg['mean']:.2f}, "
              f"teto p99 = {avg['cap']}, base {_fmt(avg['pdfs'])} PDFs do próprio periódico "
              f"de {_fmt(avg['pdfs_all'])} processados)")
    print(f"Medindo {len(ids)} periódico(s) com {args.workers} worker(s)"
          f"{' [dry-run]' if args.dry_run else ''}...\n")

    printed = threading.Lock()

    def on_result(spec, result):
        with printed:
            print(format_result(spec, result, avg), flush=True)

    results = measure_journals(ids, workers=args.workers, dry_run=args.dry_run, on_result=on_result,
                               full=args.full, sample_size=args.sample_size, agent_type=args.agent)

    ok = [r for _, r in results if r['status'] == 'ok']
    total_articles = sum(r['articles_count'] or 0 for r in ok)
    print(f"\nMedidos: {len(ok)} ok, {len(results) - len(ok)} falha(s) | "
          f"artigos no site: {_fmt(total_articles)} | "
          f"e-mails estimados: {_fmt(estimated_emails(total_articles, avg))}")
    if args.json:
        print(json.dumps([{'journal': s, 'result': r} for s, r in results], ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
