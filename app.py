
import pandas as pd
import streamlit as st
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.cache_handler import MemoryCacheHandler

st.set_page_config(page_title="StrideSync", page_icon="🏃", layout="wide")
st.title("🏃 StrideSync")
st.write("Build a personalized running playlist using workout type, genre, and RunScore V2.")

@st.cache_data
def load_song_data():
    scored_songs = pd.read_csv("scored_songs.csv")
    runscore_cutoff = scored_songs["RunScore_V2"].quantile(0.60)
    running_candidates = scored_songs[scored_songs["RunScore_V2"] >= runscore_cutoff].copy()
    excluded_genres = ["children", "kids", "sleep", "study", "ambient", "meditation", "nature", "rain", "white-noise", "new-age"]
    running_candidates = running_candidates[~running_candidates["track_genre"].isin(excluded_genres)].copy()
    running_candidates = running_candidates.dropna(subset=["track_id", "track_name", "artists", "track_genre", "duration_mins", "tempo", "energy", "RunScore_V2"])
    running_candidates = running_candidates.drop_duplicates(subset=["track_name", "artists"], keep="first")
    return running_candidates

running_candidates = load_song_data()

# WORKOUT RULES

workout_rules = {
    "Easy": {"minimum_energy": 0.45, "maximum_energy": 0.75, "minimum_tempo": 90, "maximum_tempo": 140},
    "Tempo": {"minimum_energy": 0.60, "maximum_energy": 0.90, "minimum_tempo": 110, "maximum_tempo": 160},
    "Interval": {"minimum_energy": 0.70, "maximum_energy": 1.00, "minimum_tempo": 120, "maximum_tempo": 180},
    "Race": {"minimum_energy": 0.75, "maximum_energy": 1.00, "minimum_tempo": 125, "maximum_tempo": 190}}

# SONG-SELECTION FUNCTION

def select_songs_for_phase(song_pool, target_minutes, used_tracks):
    selected_songs = []
    total_minutes = 0

    for index, song in song_pool.iterrows():
        track_id = song["track_id"]
        song_length = song["duration_mins"]

        if track_id not in used_tracks:
            selected_songs.append(song)
            used_tracks.append(track_id)
            total_minutes = total_minutes + song_length

            if total_minutes >= target_minutes:
                break

    return pd.DataFrame(selected_songs), total_minutes

# SPOTIFY CONNECTION FUNCTION

def connect_to_spotify():

    if "spotify_cache" not in st.session_state:
        st.session_state.spotify_cache = MemoryCacheHandler()

    spotify_auth = SpotifyOAuth(
        client_id=st.secrets["SPOTIFY_CLIENT_ID"],
        client_secret=st.secrets["SPOTIFY_CLIENT_SECRET"],
        redirect_uri="https://stridesync-mitch.streamlit.app/",
        scope="playlist-modify-private playlist-modify-public",
        cache_handler=st.session_state.spotify_cache,
        open_browser=False
    )

    token_info = spotify_auth.validate_token(
        st.session_state.spotify_cache.get_cached_token()
    )

    if token_info:
        return spotipy.Spotify(auth=token_info["access_token"])

    if "code" in st.query_params:

        token_info = spotify_auth.get_access_token(
            st.query_params["code"],
            check_cache=False
        )

        st.query_params.clear()
        st.rerun()

    st.link_button(
        "Connect to Spotify",
        spotify_auth.get_authorize_url()
    )

    return None

# GENRE OPTIONS

genre_counts = running_candidates["track_genre"].value_counts()
top_genres = list(genre_counts.head(20).index)
genre_options = ["Any"] + top_genres

# USER INPUT FORM

with st.form("playlist_form"):
    workout_type = st.selectbox("Workout type", ["Easy", "Tempo", "Interval", "Race"])
    genre_choice = st.selectbox("Music genre", genre_options)
    workout_minutes = st.number_input("Workout length in minutes, not including warm-up", min_value=10, max_value=180, value=30, step=5)
    warmup_minutes = st.number_input("Warm-up length in minutes", min_value=0, max_value=30, value=5, step=1)
    build_playlist = st.form_submit_button("Build My Playlist")

# BUILD THE PLAYLIST

if build_playlist:
    rules = workout_rules[workout_type]

    workout_song_pool = running_candidates[(running_candidates["energy"] >= rules["minimum_energy"]) & (running_candidates["energy"] <= rules["maximum_energy"]) & (running_candidates["tempo"] >= rules["minimum_tempo"]) & (running_candidates["tempo"] <= rules["maximum_tempo"])].copy()

    if genre_choice != "Any":
        workout_song_pool = workout_song_pool[workout_song_pool["track_genre"] == genre_choice].copy()

    workout_song_pool = workout_song_pool.sort_values("RunScore_V2", ascending=False)

    if len(workout_song_pool) == 0:
        st.error("No songs matched those settings. Try another genre or workout type.")

    else:
        finish_minutes = workout_minutes * 0.15
        main_minutes = workout_minutes - finish_minutes
        total_target_minutes = workout_minutes + warmup_minutes

        warmup_pool = workout_song_pool.sort_values("energy").copy()
        main_pool = workout_song_pool.sort_values("RunScore_V2", ascending=False).copy()
        finish_pool = workout_song_pool.sort_values("energy", ascending=False).copy()

        used_tracks = []

        warmup_songs, actual_warmup_minutes = select_songs_for_phase(warmup_pool, warmup_minutes, used_tracks)
        main_songs, actual_main_minutes = select_songs_for_phase(main_pool, main_minutes, used_tracks)
        finish_songs, actual_finish_minutes = select_songs_for_phase(finish_pool, finish_minutes, used_tracks)

        warmup_songs["phase"] = "Warm-up"
        main_songs["phase"] = "Main Workout"
        finish_songs["phase"] = "Final Push"

        generated_playlist = pd.concat([warmup_songs, main_songs, finish_songs], ignore_index=True)
        generated_playlist["playlist_order"] = range(1, len(generated_playlist) + 1)

        actual_total_minutes = generated_playlist["duration_mins"].sum()

        while actual_total_minutes < total_target_minutes:
            extra_song = workout_song_pool[~workout_song_pool["track_id"].isin(generated_playlist["track_id"])].head(1)

            if len(extra_song) == 0:
                break

            extra_song = extra_song.copy()
            extra_song["phase"] = "Final Push"
            generated_playlist = pd.concat([generated_playlist, extra_song], ignore_index=True)
            generated_playlist["playlist_order"] = range(1, len(generated_playlist) + 1)
            actual_total_minutes = generated_playlist["duration_mins"].sum()

        st.session_state["generated_playlist"] = generated_playlist
        st.session_state["workout_type"] = workout_type
        st.session_state["genre_choice"] = genre_choice
        st.session_state["workout_minutes"] = workout_minutes
        st.session_state["warmup_minutes"] = warmup_minutes
        st.session_state["total_target_minutes"] = total_target_minutes
        st.session_state["actual_total_minutes"] = actual_total_minutes

# DISPLAY THE PLAYLIST

if "generated_playlist" in st.session_state:
    generated_playlist = st.session_state["generated_playlist"]
    total_target_minutes = st.session_state["total_target_minutes"]
    actual_total_minutes = st.session_state["actual_total_minutes"]

    st.success("Playlist created!")

    column1, column2, column3, column4 = st.columns(4)

    column1.metric("Workout", st.session_state["workout_type"])
    column2.metric("Genre", st.session_state["genre_choice"])
    column3.metric("Songs", len(generated_playlist))
    column4.metric("Playlist Minutes", round(actual_total_minutes, 1))

    st.write("Workout length:", st.session_state["workout_minutes"], "minutes")
    st.write("Warm-up length:", st.session_state["warmup_minutes"], "minutes")
    st.write("Total playlist target:", round(total_target_minutes, 1), "minutes")
    st.write("Minutes over target:", round(actual_total_minutes - total_target_minutes, 1))

    display_columns = ["playlist_order", "phase", "track_name", "artists", "track_genre", "duration_mins", "tempo", "energy", "RunScore_V2"]
    display_playlist = generated_playlist[display_columns].copy()

    display_playlist["duration_mins"] = display_playlist["duration_mins"].round(2)
    display_playlist["tempo"] = display_playlist["tempo"].round(1)
    display_playlist["energy"] = display_playlist["energy"].round(2)
    display_playlist["RunScore_V2"] = display_playlist["RunScore_V2"].round(1)

    st.dataframe(display_playlist, hide_index=True, use_container_width=True)

    csv_file = generated_playlist.to_csv(index=False).encode("utf-8")

    st.download_button(label="Download Playlist CSV", data=csv_file, file_name="generated_running_playlist.csv", mime="text/csv")


# Connect to Spotify
if "generated_playlist" in st.session_state:

    spotify = connect_to_spotify()

    if spotify is not None:

        try:
            user = spotify.current_user()

            st.success("Connected to Spotify as " + user["display_name"])

            if st.button("Send Playlist to Spotify"):

                generated_playlist = st.session_state["generated_playlist"]

                track_uris = []

                for track_id in generated_playlist["track_id"]:
                    track_uris.append("spotify:track:" + str(track_id))

                playlist_name = (
                    st.session_state["workout_type"]
                    + " Run - "
                    + st.session_state["genre_choice"]
                )

                new_playlist = spotify.user_playlist_create(
                    user=user["id"],
                    name=playlist_name,
                    public=False,
                    description="Running playlist created using StrideSync"
                )

                spotify.playlist_add_items(
                    new_playlist["id"],
                    track_uris
                )

                st.success(
                    playlist_name
                    + " was successfully added to Spotify!"
                )

        except Exception as error:
            st.error("Spotify connection failed.")
            st.write(error)
