import zipfile
import json
import pandas as pd
import os
import requests
from datetime import datetime

# ===== CONFIG =====
ZIP_URL = 'https://cricsheet.org/downloads/sat_male_json.zip'
ZIP_PATH = 'sat_male_json.zip'
SEASON_DIR = 'sa20_seasonwise'
SUMMARY_DIR = 'sa20_season_summary'
# ==================

os.makedirs(SEASON_DIR, exist_ok=True)
os.makedirs(SUMMARY_DIR, exist_ok=True)

# ===== STEP 1: ZIP DOWNLOAD =====
if not os.path.exists(ZIP_PATH):
    print("Downloading SA20 data...")
    r = requests.get(ZIP_URL, timeout=120)
    with open(ZIP_PATH, 'wb') as f:
        f.write(r.content)
    print("Download complete!")
else:
    print("Zip file already exists, skipping download.")

# ===== FUNCTION: SEASON NIKAALNE KE LIYE =====
def get_season(date_str):
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    year = dt.year
    if dt.month <= 6:
        season_start = year - 1
    else:
        season_start = year
    season_end = season_start + 1
    return f"{season_start}-{str(season_end)[2:]}"

# ===== STEP 2: ZIP SE PARSE KARO =====
print("\nParsing SA20 matches...")
season_data = {}
match_info_list = []

with zipfile.ZipFile(ZIP_PATH, 'r') as z:
    json_files = [f for f in z.namelist() if f.endswith('.json')]
    print(f"Total matches found: {len(json_files)}")

    for filename in json_files:
        with z.open(filename) as f:
            match = json.load(f)

            info = match.get('info', {})
            match_date = info['dates'][0]
            season = get_season(match_date)
            teams = info['teams']
            venue = info.get('venue', 'Unknown')
            match_id = info.get('id', filename)

            outcome = info.get('outcome', {})
            winner = outcome.get('winner', 'Unknown')
            toss = info.get('toss', {})
            toss_winner = toss.get('winner', 'Unknown')
            toss_decision = toss.get('decision', 'Unknown')

            match_info_list.append({
                'match_id': match_id,
                'winner': winner,
                'toss_winner': toss_winner,
                'toss_decision': toss_decision
            })

            for innings in match.get('innings', []):
                batting_team = innings.get('team')
                bowling_team = teams[0] if batting_team == teams[1] else teams[1]

                for over in innings.get('overs', []):
                    for delivery in over.get('deliveries', []):
                        row = {
                            'match_id': match_id,
                            'date': match_date,
                            'season': season,
                            'venue': venue,
                            'batting_team': batting_team,
                            'bowling_team': bowling_team,
                            'over': over.get('over'),
                            'ball': delivery.get('extras', {}).get('balls', 1) if 'extras' in delivery else 1,
                            'striker': delivery.get('batter'),
                            'bowler': delivery.get('bowler'),
                            'non_striker': delivery.get('non_striker'),
                            'runs_batter': delivery['runs'].get('batter', 0),
                            'runs_extras': delivery['runs'].get('extras', 0),
                            'runs_total': delivery['runs'].get('total', 0),
                            'wicket': 1 if 'wickets' in delivery else 0,
                            'dismissal_kind': delivery['wickets'][0].get('kind') if 'wickets' in delivery else None,
                            'player_dismissed': delivery['wickets'][0].get('player_out') if 'wickets' in delivery else None,
                        }
                        if season not in season_data:
                            season_data[season] = []
                        season_data[season].append(row)

# ===== STEP 3: SEASON-WISE CSV SAVE KARO =====
print("\nSaving season-wise CSV files...")
info_df = pd.DataFrame(match_info_list)
info_df['match_id'] = info_df['match_id'].astype(str)

for season, rows in sorted(season_data.items()):
    df = pd.DataFrame(rows)
    df['match_id'] = df['match_id'].astype(str)
    merged_df = pd.merge(df, info_df, on='match_id', how='left')
    output_file = f'{SEASON_DIR}/sa20_{season}.csv'
    merged_df.to_csv(output_file, index=False)
    print(f"SA20 {season}: {len(merged_df)} balls -> {output_file}")

# ===== STEP 4: MATCH SUMMARY + PITCH TYPE =====
print("\nCreating match summary with Pitch Type...")

for season in sorted(season_data.keys()):
    file_path = f'{SEASON_DIR}/sa20_{season}.csv'
    df = pd.read_csv(file_path)

    matches = []
    for match_id in df['match_id'].unique():
        match_df = df[df['match_id'] == match_id]
        first_batting = match_df['batting_team'].iloc[0]
        second_batting = match_df['bowling_team'].iloc[0]
        first_innings = match_df[match_df['batting_team'] == first_batting]
        second_innings = match_df[match_df['batting_team'] == second_batting]
        first_runs = first_innings['runs_total'].sum()
        second_runs = second_innings['runs_total'].sum()
        first_wickets = first_innings['wicket'].sum()
        second_wickets = second_innings['wicket'].sum()

        matches.append({
            'match_id': match_id,
            'date': match_df['date'].iloc[0],
            'venue': match_df['venue'].iloc[0],
            'team1': first_batting,
            'team2': second_batting,
            'team1_score': f"{first_runs}/{first_wickets}",
            'team2_score': f"{second_runs}/{second_wickets}",
            'winner': match_df['winner'].iloc[0],
            'toss_winner': match_df['toss_winner'].iloc[0],
            'toss_decision': match_df['toss_decision'].iloc[0],
            'total_balls': len(match_df),
        })

    summary_df = pd.DataFrame(matches)

    def get_runs(score):
        try:
            return int(str(score).split("/")[0])
        except:
            return None

    summary_df["team1_runs"] = summary_df["team1_score"].apply(get_runs)
    summary_df["team2_runs"] = summary_df["team2_score"].apply(get_runs)

    def first_innings_runs(row):
        if row["toss_decision"] == "bat":
            if row["toss_winner"] == row["team1"]:
                return row["team1_runs"]
            else:
                return row["team2_runs"]
        else:
            if row["toss_winner"] == row["team1"]:
                return row["team2_runs"]
            else:
                return row["team1_runs"]

    summary_df["first_innings_runs"] = summary_df.apply(first_innings_runs, axis=1)
    avg_score = summary_df["first_innings_runs"].mean()

    def pitch_type(avg):
        if pd.isna(avg):
            return "Unknown"
        elif avg >= 175:
            return "Batting Friendly"
        elif avg >= 155:
            return "Balanced"
        else:
            return "Slow / Bowling"

    summary_df["avg_1st_innings_score"] = round(avg_score, 1)
    summary_df["pitch_type"] = pitch_type(avg_score)
    summary_df = summary_df.drop(columns=["team1_runs", "team2_runs", "first_innings_runs"])

    output_file = f'{SUMMARY_DIR}/sa20_{season}_matches.csv'
    summary_df.to_csv(output_file, index=False)
    print(f"SA20 {season}: {len(matches)} matches | Avg = {avg_score:.1f} | {pitch_type(avg_score)}")

print("\n" + "=" * 60)
print("DONE!")
print("=" * 60)