import streamlit as st
from nba_api.stats.static import teams
from nba_api.stats.endpoints import commonallplayers, playergamelog
import pandas as pd
import numpy as np
import collections
from requests.exceptions import RequestException

# Get all NBA teams
nba_teams = teams.get_teams()
team_dict = {team['full_name'].lower(): team['full_name'] for team in nba_teams}
team_aliases = {
    "knicks": "new york knicks",
    "rockets": "houston rockets",
    "heat": "miami heat",
    "raptors": "toronto raptors",
    "grizzlies": "memphis grizzlies",
    "nuggets": "denver nuggets",
    "timberwolves": "minnesota timberwolves",
    "suns": "phoenix suns",
    "cavaliers": "cleveland cavaliers",
    "pelicans": "new orleans pelicans",
    "warriors": "golden state warriors",
    "bucks": "milwaukee bucks",
    "magic": "orlando magic",
    "trail blazers": "portland trail blazers",
    "wizards": "washington wizards",
    "hornets": "charlotte hornets",
    "bulls": "chicago bulls",
    "clippers": "los angeles clippers",
    "jazz": "utah jazz",
    "76ers": "philadelphia 76ers",
    "hawks": "atlanta hawks",
    "spurs": "san antonio spurs",
    "lakers": "los angeles lakers",
    "kings": "sacramento kings",
    "pacers": "indiana pacers",
    "mavericks": "dallas mavericks",
    "thunder": "oklahoma city thunder",
    "celtics": "boston celtics",
    "nets": "brooklyn nets"
}

# Function to fetch all players and their team information
def fetch_player_data():
    retries = 5
    for attempt in range(retries):
        try:
            nba_players = commonallplayers.CommonAllPlayers(is_only_current_season=1).get_data_frames()[0]
            player_team_map = {}
            for _, player in nba_players.iterrows():
                team_name = player['TEAM_NAME']
                if team_name:
                    team_name_lower = team_name.lower()
                    standardized_team_name = team_aliases.get(team_name_lower, team_name.lower())
                    if standardized_team_name in team_dict:
                        player_team_map[player['DISPLAY_FIRST_LAST']] = {
                            'id': player['PERSON_ID'],
                            'team_name': standardized_team_name
                        }
            st.session_state['player_team_map'] = player_team_map
            break
        except RequestException as e:
            st.warning(f"Network error: {str(e)}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            st.warning(f"Attempt {attempt + 1} of {retries}: Error fetching player data: {str(e)}")
    else:
        st.error("Failed to fetch player data after multiple attempts. Please check your network connection.")

# Automatically fetch player data when the app starts
if 'player_team_map' not in st.session_state or not st.session_state['player_team_map']:
    fetch_player_data()

# Function to display player statistics
def display_player_stats(selected_player, selected_stat, threshold=None):
    player_info = st.session_state['player_team_map'].get(selected_player, None)
    if player_info:
        player_id = player_info['id']
        try:
            # Retrieve player's game log for the current and previous season
                        gamelog_current = playergamelog.PlayerGameLog(player_id=player_id, season='2024-25')
            gamelog_previous = playergamelog.PlayerGameLog(player_id=player_id, season='2023-24')
                                    gamelog_current_df = gamelog_current.get_data_frames()[0]
            gamelog_previous_df = gamelog_previous.get_data_frames()[0]
            gamelog_df = pd.concat([gamelog_current_df, gamelog_previous_df])
    gamelog_df = pd.concat([gamelog_current_df, gamelog_previous_df])
            # Check if the gamelog is empty
            if gamelog_df.empty:
                st.warning("No game data available for the selected player.")
                return
            # Determine which statistic to display
            stat_map = {
                "Points": "PTS",
                "Rebounds": "REB",
                "Assists": "AST",
                "P + R": ["PTS", "REB"],
                "P + A": ["PTS", "AST"],
                "R + A": ["REB", "AST"],
                "P + R + A": ["PTS", "REB", "AST"]
            }
            stat_columns = stat_map.get(selected_stat, None)
            if stat_columns is None:
                st.warning("Please select a valid statistic type.")
                return

            # Calculate statistics
            if isinstance(stat_columns, list):
                stats = gamelog_df[stat_columns].fillna(0).sum(axis=1)
            else:
                stats = gamelog_df[stat_columns].fillna(0)
            if stats.empty:
                st.warning(f"No data available for {selected_stat.lower()} for the selected player.")
                return
            avg_stat = np.mean(stats)
            median_stat = np.median(stats)
            high_ceiling = np.max(stats)
            low_ceiling = np.min(stats)
            most_common_stat = collections.Counter(stats).most_common(1)[0][0] if len(stats) > 0 else None
            avg_range = (avg_stat * 0.9, avg_stat * 1.1)
            median_range = (median_stat * 0.9, median_stat * 1.1)

            total_games = len(stats)
            high_ceiling_percentage = (stats == high_ceiling).sum() / total_games * 100 if total_games > 0 else 0
            low_ceiling_percentage = (stats == low_ceiling).sum() / total_games * 100 if total_games > 0 else 0
            most_common_percentage = (stats == most_common_stat).sum() / total_games * 100 if total_games > 0 else 0
            avg_stat_percentage = ((stats >= avg_range[0]) & (stats <= avg_range[1])).sum() / total_games * 100 if total_games > 0 else 0
            median_stat_percentage = ((stats >= median_range[0]) & (stats <= median_range[1])).sum() / total_games * 100 if total_games > 0 else 0

            # Display statistics
            st.markdown(f"### Stats for {selected_player} ({selected_stat}, 2023-24 and 2024-25 seasons):")
            st.markdown(f"- **Average {selected_stat}:** <span style='color:green; font-weight:bold;'>{avg_stat:.2f}</span> ({avg_stat_percentage:.2f}% impact)", unsafe_allow_html=True)
            st.markdown(f"- **Median {selected_stat}:** <span style='color:green; font-weight:bold;'>{median_stat:.2f}</span> ({median_stat_percentage:.2f}% impact)", unsafe_allow_html=True)
            st.markdown(f"- **High Ceiling {selected_stat}:** <span style='color:green; font-weight:bold;'>{high_ceiling}</span> ({high_ceiling_percentage:.2f}% impact)", unsafe_allow_html=True)
            st.markdown(f"- **Low Ceiling {selected_stat}:** <span style='color:green; font-weight:bold;'>{low_ceiling}</span> ({low_ceiling_percentage:.2f}% impact)", unsafe_allow_html=True)
            st.markdown(f"- **Most Common {selected_stat}:** <span style='color:green; font-weight:bold;'>{most_common_stat}</span> (Achieved {most_common_percentage:.2f}% of games)", unsafe_allow_html=True)

            # Calculate percentage above and below the threshold if provided
            if threshold is not None:
                above_threshold_percentage = (stats > threshold).sum() / total_games * 100 if total_games > 0 else 0
                below_threshold_percentage = (stats < threshold).sum() / total_games * 100 if total_games > 0 else 0
                st.markdown(f"- **Percentage Above {threshold:.2f} {selected_stat}:** <span style='color:green; font-weight:bold;'>{above_threshold_percentage:.2f}%</span>", unsafe_allow_html=True)
                st.markdown(f"- **Percentage Below {threshold:.2f} {selected_stat}:** <span style='color:green; font-weight:bold;'>{below_threshold_percentage:.2f}%</span>", unsafe_allow_html=True)

            # Add suggested fair line at the end
            st.markdown(f"- **Suggested Fair Line:** <span style='color:green; font-weight:bold;'>{avg_stat:.2f}</span>", unsafe_allow_html=True)

            
        except IndexError:
            st.warning("No game data available for the selected player.")
        except Exception as e:
            st.error(f"An error occurred: {str(e)}")

# Streamlit application
st.title("NBA Player Stats Viewer")

# Team selection
selected_team = st.selectbox("Select Team:", sorted(team_dict.values()))
standardized_team_name = team_aliases.get(selected_team.lower(), selected_team.lower())
filtered_players = [
    player for player, info in st.session_state['player_team_map'].items()
    if info['team_name'].lower() == standardized_team_name
]

# Player selection
selected_player = st.selectbox("Select Player:", sorted(filtered_players) if filtered_players else [])

# Statistic type selection
selected_stat = st.selectbox("Select Statistic:", ["Points", "Rebounds", "Assists", "P + R", "P + A", "R + A", "P + R + A"])

# Threshold input
threshold = st.number_input("Enter Threshold (optional):", min_value=0.0, step=1.0)

# Display player stats
if selected_player and st.button("Display Player Stats"):
    display_player_stats(selected_player, selected_stat, threshold)
