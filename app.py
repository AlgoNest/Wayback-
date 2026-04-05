from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import requests
import re
import time

app = Flask(__name__)
CORS(app)

# ── Security: simple rate limiting via in-memory store ──────────────────────
from collections import defaultdict
request_counts = defaultdict(list)
RATE_LIMIT = 20          # max requests
RATE_WINDOW = 60         # per 60 seconds

def is_rate_limited(ip):
    now = time.time()
    window = request_counts[ip]
    window[:] = [t for t in window if now - t < RATE_WINDOW]
    if len(window) >= RATE_LIMIT:
        return True
    window.append(now)
    return False

def get_ip():
    return request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()

# ── Input validation ─────────────────────────────────────────────────────────
def sanitize_url(url):
    if not url:
        return None, "URL is required"
    url = url.strip()
    if len(url) > 500:
        return None, "URL too long"
    # Allow bare domains and full URLs
    if not re.match(r'^(https?://)?[\w\-]+(\.[\w\-]+)+(/.*)?$', url):
        return None, "Invalid URL format"
    # Strip any script injection attempts
    if re.search(r'[<>"\'`;]', url):
        return None, "Invalid characters in URL"
    return url, None

def sanitize_date(date_str):
    if not date_str:
        return None
    date_str = date_str.strip()
    if not re.match(r'^\d{8}$', date_str):
        return None
    return date_str

# ── Routes ───────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/search')
def search():
    if is_rate_limited(get_ip()):
        return jsonify({'error': 'Too many requests. Please wait a moment.'}), 429

    raw_url = request.args.get('url', '')
    url, err = sanitize_url(raw_url)
    if err:
        return jsonify({'error': err}), 400

    from_date = sanitize_date(request.args.get('from', ''))
    to_date   = sanitize_date(request.args.get('to', ''))

    params = {
        'url':    url,
        'output': 'json',
        'filter': 'statuscode:200',
        'fl':     'timestamp,statuscode,mimetype,digest',
        'limit':  100,
        'collapse': 'digest',   # auto-deduplicate identical snapshots
    }
    if from_date:
        params['from'] = from_date
    if to_date:
        params['to'] = to_date

    try:
        resp = requests.get(
            'https://web.archive.org/cdx/search/cdx',
            params=params,
            timeout=9
        )
        resp.raise_for_status()
        data = resp.json()

        if not data or len(data) <= 1:
            return jsonify({'snapshots': [], 'total': 0})

        headers   = data[0]
        snapshots = [dict(zip(headers, row)) for row in data[1:]]
        return jsonify({'snapshots': snapshots, 'total': len(snapshots)})

    except requests.exceptions.Timeout:
        return jsonify({'error': 'Archive.org is taking too long. Try a more specific URL or date range.'}), 504
    except requests.exceptions.HTTPError as e:
        return jsonify({'error': f'Archive.org returned an error: {e.response.status_code}'}), 502
    except Exception as e:
        return jsonify({'error': 'Something went wrong. Please try again.'}), 500


@app.route('/api/availability')
def availability():
    if is_rate_limited(get_ip()):
        return jsonify({'error': 'Too many requests. Please wait a moment.'}), 429

    raw_url = request.args.get('url', '')
    url, err = sanitize_url(raw_url)
    if err:
        return jsonify({'error': err}), 400

    try:
        resp = requests.get(
            'https://archive.org/wayback/available',
            params={'url': url},
            timeout=9
        )
        resp.raise_for_status()
        return jsonify(resp.json())
    except requests.exceptions.Timeout:
        return jsonify({'error': 'Request timed out.'}), 504
    except Exception:
        return jsonify({'error': 'Could not check availability.'}), 500


@app.route('/api/save', methods=['POST'])
def save_page():
    if is_rate_limited(get_ip()):
        return jsonify({'error': 'Too many requests. Please wait a moment.'}), 429

    body = request.get_json(silent=True) or {}
    raw_url = body.get('url', '')
    url, err = sanitize_url(raw_url)
    if err:
        return jsonify({'error': err}), 400

    try:
        resp = requests.get(
            f'https://web.archive.org/save/{url}',
            timeout=20,
            allow_redirects=True,
            headers={'User-Agent': 'WaybackWrapper/1.0'}
        )
        archived_url = resp.url
        if 'web.archive.org/web/' in archived_url:
            return jsonify({'success': True, 'archived_url': archived_url})
        return jsonify({'error': 'Page could not be saved. Archive.org may have rejected it.'}), 502
    except requests.exceptions.Timeout:
        return jsonify({'error': 'Save request timed out. Try again later.'}), 504
    except Exception:
        return jsonify({'error': 'Failed to save page.'}), 500


@app.route('/api/changes')
def check_changes():
    if is_rate_limited(get_ip()):
        return jsonify({'error': 'Too many requests. Please wait a moment.'}), 429

    raw_url = request.args.get('url', '')
    url, err = sanitize_url(raw_url)
    if err:
        return jsonify({'error': err}), 400

    try:
        resp = requests.get(
            'https://web.archive.org/cdx/search/cdx',
            params={
                'url':    url,
                'output': 'json',
                'fl':     'timestamp,digest',
                'limit':  50,
                'collapse': 'digest',
            },
            timeout=9
        )
        resp.raise_for_status()
        data = resp.json()

        if not data or len(data) <= 1:
            return jsonify({'changes': [], 'total_changes': 0})

        headers = data[0]
        rows    = [dict(zip(headers, row)) for row in data[1:]]
        return jsonify({'changes': rows, 'total_changes': len(rows)})

    except requests.exceptions.Timeout:
        return jsonify({'error': 'Request timed out.'}), 504
    except Exception:
        return jsonify({'error': 'Could not fetch change history.'}), 500
