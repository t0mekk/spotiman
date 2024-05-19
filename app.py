from flask import Flask, request, redirect, url_for, render_template_string
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import pandas as pd
import time
import os

app = Flask(__name__)

client_id = "5fbfa7d239514ef4b2ce7f078ff24995"
client_secret = "51617959271e4253aceaf53c3db13938"
redirect_uri = "http://localhost:8080/callback"

scope = 'user-follow-read user-follow-modify'
sp_oauth = SpotifyOAuth(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri, scope=scope)

@app.route('/')
def index():
    auth_url = sp_oauth.get_authorize_url()
    return render_template_string('''
        <h1>Spotify Follow Manager</h1>
        <a href="{{ auth_url }}">Login to Spotify</a>
    ''', auth_url=auth_url)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    token_info = sp_oauth.get_access_token(code)
    sp = spotipy.Spotify(auth=token_info['access_token'])
    request.environ['sp'] = sp
    return redirect(url_for('menu'))

@app.route('/menu')
def menu():
    return render_template_string('''
        <h1>Spotify Follow Manager</h1>
        <ul>
            <li><a href="{{ url_for('fetch_followed_artists') }}">Fetch Followed Artists</a></li>
            <li><a href="{{ url_for('unfollow_artists') }}">Unfollow Artists</a></li>
        </ul>
    ''')

@app.route('/fetch_followed_artists')
def fetch_followed_artists():
    sp = request.environ.get('sp')
    if not sp:
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
    return f"Successfully saved {len(artists)} followed artists to followed_artists.csv"

@app.route('/unfollow_artists')
def unfollow_artists():
    sp = request.environ.get('sp')
    if not sp:
        return redirect(url_for('index'))

    if not os.path.exists('unfollow_artists.csv'):
        return "The file 'unfollow_artists.csv' does not exist. Please create it based on 'followed_artists.csv'."

    try:
        unfollow_df = pd.read_csv('unfollow_artists.csv')
        if 'id' not in unfollow_df.columns:
            return "The 'unfollow_artists.csv' file must contain an 'id' column."
        artist_ids_to_unfollow = unfollow_df['id'].tolist()
    except Exception as e:
        return f"Error reading 'unfollow_artists.csv': {e}"

    unfollowed_artists = []

    def unfollow_batch(artist_ids):
        batch_size = 50
        for i in range(0, len(artist_ids), batch_size):
            batch = artist_ids[i:i + batch_size]
            sp.user_unfollow_artists(batch)
            for artist_id in batch:
                unfollowed_artists.append(artist_id)
            if i + batch_size < len(artist_ids):
                time.sleep(15)

    unfollow_batch(artist_ids_to_unfollow)

    return f"Successfully unfollowed {len(unfollowed_artists)} artists."

if __name__ == "__main__":
    app.run(debug=True, port=8080)
