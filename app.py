from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import requests

app = Flask(__name__)
CORS(app)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/search')
def search():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'URL parameter is required'}), 400

    try:
        resp = requests.get(
            'https://web.archive.org/cdx/search/cdx',
            params={
                'url': url,
                'output': 'json',
                'filter': 'statuscode:200',
                'fl': 'timestamp,statuscode,mimetype,digest',
                'limit': 50
            },
            timeout=9
        )
        data = resp.json()
        if len(data) <= 1:
            return jsonify({'snapshots': []})
        headers = data[0]
        snapshots = [dict(zip(headers, row)) for row in data[1:]]
        return jsonify({'snapshots': snapshots})
    except requests.exceptions.Timeout:
        return jsonify({'error': 'Archive.org took too long to respond'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/availability')
def availability():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'URL parameter is required'}), 400

    try:
        resp = requests.get(
            'https://archive.org/wayback/available',
            params={'url': url},
            timeout=9
        )
        return jsonify(resp.json())
    except requests.exceptions.Timeout:
        return jsonify({'error': 'Archive.org took too long to respond'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500
