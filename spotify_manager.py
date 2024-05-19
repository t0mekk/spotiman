from flask import Flask, request, redirect, url_for, render_template, session, flash, send_file
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import pandas as pd
import os
from dotenv import load_dotenv
from flask_session import Session
from datetime import datetime, timedelta
import time

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Secret key for session management
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

client_id = os.getenv('SPOTIPY_CLIENT_ID')
client_secret = os.getenv('SPOTIPY_CLIENT_SECRET')
redirect_uri = os.getenv('SPOTIPY_REDIRECT_URI')

scope = 'user-follow-read user-follow-modify'
sp_oauth = SpotifyOAuth(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri, scope=scope)

def create_spotify_client():
    token_info = session.get('token_info', None)
    if not token_info:
        return None
    if sp_oauth.is_token_expired(token_info):
        token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
        session['token_info'] = token_info
    return spotipy.Spotify(auth=token_info['access_token'])

@app.context_processor
def utility_processor():
    return dict(max=max, min=min)

@app.route('/')
def index():
    auth_url = sp_oauth.get_authorize_url()
    return render_template('index.html', auth_url=auth_url)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    token_info = sp_oauth.get_access_token(code)
    session['token_info'] = token_info
    return redirect(url_for('menu'))

@app.route('/menu')
def menu():
    return render_template('menu.html')

@app.route('/fetch_followed_artists')
def fetch_followed_artists():
    sp = create_spotify_client()
    if not sp:
        flash("Please login to Spotify.", "warning")
        return redirect(url_for('index'))

    artists = []
    results = sp.current_user_followed_artists(limit=50)
    while results:
        for artist in results['artists']['items']:
            artists.append({'name': artist['name'], 'id': artist['id']})
        if results['artists']['next']:
            results = sp.next(results['artists'])
        else:
            results = None
    df = pd.DataFrame(artists)
    df.to_csv('followed_artists.csv', index=False)
    return render_template('followed_artists.html', count=len(artists))

@app.route('/display_followed_artists')
def display_followed_artists():
    if not os.path.exists('followed_artists.csv'):
        flash("The file 'followed_artists.csv' does not exist. Please fetch followed artists first.", "danger")
        return redirect(url_for('menu'))

    try:
        followed_df = pd.read_csv('followed_artists.csv')
        artists = followed_df.to_dict(orient='records')
    except Exception as e:
        flash(f"Error reading 'followed_artists.csv': {str(e)}", "danger")
        return redirect(url_for('menu'))

    total_artists = len(artists)
    page = request.args.get('page', 1, type=int)
    sort = request.args.get('sort', 'asc')
    per_page = request.args.get('per_page', 50, type=int)

    if sort == 'asc':
        artists = sorted(artists, key=lambda x: x['name'])
    else:
        artists = sorted(artists, key=lambda x: x['name'], reverse=True)

    total_pages = (total_artists + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    paginated_artists = artists[start:end]

    return render_template('display_followed_artists.html', artists=paginated_artists, page=page, total_pages=total_pages, total_artists=total_artists, sort=sort, per_page=per_page)

@app.route('/save_selected_artists', methods=['POST'])
def save_selected_artists():
    selected_artist_ids = request.form.getlist('selected_artists')
    if not selected_artist_ids:
        flash("No artists selected.", "warning")
        return redirect(url_for('display_followed_artists'))

    followed_df = pd.read_csv('followed_artists.csv')
    selected_artists = followed_df[followed_df['id'].isin(selected_artist_ids)]
    selected_artists.to_csv('selected_artists_to_unfollow.csv', index=False)

    flash(f"Selected artists saved. {len(selected_artists)} artists will be unfollowed later.", "success")
    return redirect(url_for('display_followed_artists'))

@app.route('/unfollow_artists', methods=['GET', 'POST'])
def unfollow_artists():
    sp = create_spotify_client()
    if not sp:
        flash("Please login to Spotify.", "warning")
        return redirect(url_for('index'))

    if request.method == 'POST':
        file = request.files.get('file')
        if file:
            file_path = file.filename
            file.save(file_path)
        else:
            file_path = 'selected_artists_to_unfollow.csv'
            if not os.path.exists(file_path):
                return render_template('unfollow_artists_form.html', file_not_found=True)

        try:
            unfollow_df = pd.read_csv(file_path)
            if 'id' not in unfollow_df.columns:
                flash("The file must contain an 'id' column.", "danger")
                return redirect(url_for('unfollow_artists'))
            artist_ids_to_unfollow = unfollow_df['id'].tolist()
            artist_names = unfollow_df['name'].tolist()
        except Exception as e:
            flash(f"Error reading file: {str(e)}", "danger")
            return redirect(url_for('unfollow_artists'))

        unfollowed_artists = []

        def unfollow_batch(artist_ids, artist_names):
            batch_size = 50
            for i in range(0, len(artist_ids), batch_size):
                batch = artist_ids[i:i + batch_size]
                sp.user_unfollow_artists(batch)
                for j, artist_id in enumerate(batch):
                    unfollowed_artists.append(artist_names[i + j])
                if i + batch_size < len(artist_ids):
                    time.sleep(15)

        unfollow_batch(artist_ids_to_unfollow, artist_names)

        return render_template('unfollow_artists_results.html', count=len(unfollowed_artists), unfollowed_artists=unfollowed_artists)

    return render_template('unfollow_artists_form.html', file_not_found=not os.path.exists('selected_artists_to_unfollow.csv'))

@app.route('/fetch_label_releases', methods=['GET', 'POST'])
def fetch_label_releases():
    sp = create_spotify_client()
    if not sp:
        flash("Please login to Spotify.", "warning")
        return redirect(url_for('index'))

    if request.method == 'POST':
        label_name = request.form.get('label_name')
        if not label_name:
            flash("Please enter a record label name.", "danger")
            return redirect(url_for('fetch_label_releases'))

        results = sp.search(q=f'label:"{label_name}"', type='album', limit=50)
        releases = []
        for album in results['albums']['items']:
            release_date = album['release_date']
            release_name = album['name']
            release_type = album['album_type']
            release_url = album['external_urls']['spotify']
            artist_name = ', '.join([artist['name'] for artist in album['artists']])
            releases.append({
                'release_date': release_date,
                'release_name': release_name,
                'release_type': release_type,
                'release_url': release_url,
                'artist_name': artist_name
            })

        if not releases:
            flash(f"No releases found for label: {label_name}", "info")
            return redirect(url_for('menu'))

        # Convert release_date to datetime and filter by recent releases
        for release in releases:
            release['release_date'] = datetime.strptime(release['release_date'], '%Y-%m-%d')
        
        # Filter releases to only include those within the last year
        one_year_ago = datetime.now() - timedelta(days=365)
        recent_releases = [release for release in releases if release['release_date'] >= one_year_ago]

        # Sort releases by date (newest first)
        recent_releases.sort(key=lambda x: x['release_date'], reverse=True)

        return render_template('fetch_label_releases_results.html', label_name=label_name, releases=recent_releases[:10])

    return render_template('fetch_label_releases_form.html')

if __name__ == '__main__':
    app.run(debug=True)
