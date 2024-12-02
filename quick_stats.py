# Modified fetch_player_data to handle unsuccessful attempts better
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

# Proper handling for game log retrieval when either season is empty
def display_player_stats(selected_player, selected_stat, threshold=None):
    player_info = st.session_state['player_team_map'].get(selected_player, None)
    if player_info:
        player_id = player_info['id']
        try:
            # Retrieve player's game log for the current and previous season
            gamelog_current = playergamelog.PlayerGameLog(player_id=player_id, season='2024-25').get_data_frames()[0]
            gamelog_previous = playergamelog.PlayerGameLog(player_id=player_id, season='2023-24').get_data_frames()[0]
            gamelog_df = pd.concat([gamelog_current, gamelog_previous], ignore_index=True)

            # Check if the gamelog is empty
            if gamelog_df.empty:
                st.warning("No game data available for the selected player.")
                return

            # Further calculations and display here
            ...

        except IndexError:
            st.warning(f"No game data available for {selected_player}.")
        except RequestException as e:
            st.error(f"Network error while fetching data for {selected_player}: {str(e)}")
        except Exception as e:
            st.error(f"An error occurred: {str(e)}")

# Ensure player list is populated before displaying selection options
st.title("NBA Player Stats Viewer")

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
