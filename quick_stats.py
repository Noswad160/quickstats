import streamlit as st
from nba_api.stats.static import teams
from nba_api.stats.endpoints import commonallplayers, playergamelog
import pandas as pd
import numpy as np
import collections
import random
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
@st.cache_data
def fetch_player_data():
    retries = 5
    player_team_map = None
    for attempt in range(retries):
        try:
            nba_players = commonallplayers.CommonAllPlayers(is_only_current_season=1).get_data_frames()[0]
            player_team_map = {}
            for _, player in nba_players.iterrows():
                team_name = player['TEAM_NAME']
                if team_name:
                    team_name_lower = team_name.lower()
                    standardized_team_name = team_aliases.get(team_name_lower, team_name_lower)
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

    if not player_team_map:
        st.error("Failed to fetch player data after multiple attempts. Please check your network connection.")
        return

# Proper handling for game log retrieval for a player's entire career
def display_player_stats(selected_player, selected_stat, threshold=None, simulations=10000):
    player_info = st.session_state['player_team_map'].get(selected_player, None)
    if player_info:
        player_id = player_info['id']
        try:
            with st.spinner('Fetching player game logs...'):
                # Retrieve player's entire career game log
                gamelog_df = playergamelog.PlayerGameLog(player_id=player_id).get_data_frames()[0]

            # Ensure the game log is sorted chronologically
            gamelog_df = gamelog_df.sort_values(by="GAME_DATE", ascending=True)

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

            # Handle single or combined stats correctly
            if isinstance(stat_columns, list):
                # Sum combined stats across columns
                stats = gamelog_df[stat_columns].fillna(0).sum(axis=1)
            else:
                # Directly use single stat column
                stats = gamelog_df[stat_columns].fillna(0)

            if stats.empty:
                st.warning(f"No data available for {selected_stat.lower()} for the selected player.")
                return

            # Monte Carlo Simulation for Fair Line
            simulated_outcomes = [random.choice(stats) for _ in range(simulations)]
            fair_line = np.mean(simulated_outcomes)

            # Calculate metrics
            avg_stat = np.mean(stats)
            median_stat = np.median(stats)
            high_ceiling = np.max(stats)
            low_ceiling = np.min(stats)
            most_common_stat = collections.Counter(stats).most_common(1)[0][0] if len(stats) > 0 else None

            # Display statistics
            st.markdown(f"### Stats for {selected_player} ({selected_stat}):")
            st.markdown(f"- **Average {selected_stat}:** {avg_stat:.2f}")
            st.markdown(f"- **Median {selected_stat}:** {median_stat:.2f}")
            st.markdown(f"- **High Ceiling {selected_stat}:** {high_ceiling}")
            st.markdown(f"- **Low Ceiling {selected_stat}:** {low_ceiling}")
            st.markdown(f"- **Most Common {selected_stat}:** {most_common_stat}")
            st.markdown(f"- **Suggested Fair Line (Monte Carlo):** <span style='color:green; font-weight:bold;'>{fair_line:.2f}</span>", unsafe_allow_html=True)

        except IndexError:
            st.warning(f"No game data available for {selected_player}.")
        except RequestException as e:
            st.error(f"Network error while fetching data for {selected_player}: {str(e)}")
        except Exception as e:
            st.error(f"An error occurred: {str(e)}")

# Streamlit application
st.title("NBA Player Stats Viewer")

with st.spinner('Fetching team data...'):
    fetch_player_data()

selected_team = st.selectbox("Select Team:", sorted(team_dict.values()))
standardized_team_name = team_aliases.get(selected_team.lower(), selected_team.lower())
filtered_players = [
    player for player, info in st.session_state.get('player_team_map', {}).items()
    if info['team_name'].lower() == standardized_team_name
]

if filtered_players:
    selected_player = st.selectbox("Select Player:", sorted(filtered_players))
    selected_stat = st.selectbox("Select Statistic:", ["Points", "Rebounds", "Assists", "P + R", "P + A", "R + A", "P + R + A"])
    threshold = st.number_input("Enter Threshold (optional):", min_value=0.0, step=1.0)

    if selected_player and st.button("Display Player Stats"):
        display_player_stats(selected_player, selected_stat, threshold)
else:
    st.warning("No players available for the selected team. Please choose a different team.")
