''' Class ranking method: Laps/Time, Best % rounds '''

import logging
import RHUtils
import math
from eventmanager import Evt
from RHRace import StartBehavior
from Results import RaceClassRankMethod
from RHUI import UIField, UIFieldType, UIFieldSelectOption

logger = logging.getLogger(__name__)

def rank_best_pct_rounds(rhapi, race_class, args):
    if 'round_pct' not in args or not args['round_pct'] or int(args['round_pct']) < 1:
        return False, {}

    round_pct = float(args['round_pct']) / 100

    race_format = rhapi.db.raceformat_by_id(race_class.format_id)
    heats = rhapi.db.heats_by_class(race_class.id)

    pilotresults = {}
    for heat in heats:
        races = rhapi.db.races_by_heat(heat.id)

        for race in races:
            race_result = rhapi.db.race_results(race)

            if race_result:
                # Get race number from race object if available
                race_num = None
                if hasattr(race, 'round') and race.round:
                    race_num = race.round
                elif hasattr(race, 'race_num') and race.race_num:
                    race_num = race.race_num
                elif hasattr(race, 'id'):
                    race_num = race.id
                
                for pilotresult in race_result['by_race_time']:
                    if pilotresult['pilot_id'] not in pilotresults:
                        pilotresults[pilotresult['pilot_id']] = []
                    # Add race number to pilotresult for later reference
                    pilotresult_with_race = pilotresult.copy()
                    pilotresult_with_race['race_num'] = race_num
                    pilotresults[pilotresult['pilot_id']].append(pilotresult_with_race)
            else:
                logger.warning("Failed building ranking, race result not available")
                return False, {}

    leaderboard = []
    for pilotresultlist in pilotresults:
        if race_format and race_format.start_behavior == StartBehavior.STAGGERED:
            pilot_result = sorted(pilotresults[pilotresultlist], key = lambda x: (
                -x['laps'], # reverse lap count
                x['total_time_laps_raw'] if x['total_time_laps_raw'] and x['total_time_laps_raw'] > 0 else float('inf') # total time ascending except 0
            ))
        else:
            pilot_result = sorted(pilotresults[pilotresultlist], key = lambda x: (
                -x['laps'], # reverse lap count
                x['total_time_raw'] if x['total_time_raw'] and x['total_time_raw'] > 0 else float('inf') # total time ascending except 0
            ))

        if 'rounding' not in args or args['rounding'] == 'down':
            rounds = int(len(pilot_result) * round_pct)
        elif args['rounding'] == 'nearest': 
            rounds = round(len(pilot_result) * round_pct)
        else: # up
            rounds = math.ceil(len(pilot_result) * round_pct)

        pilot_result = pilot_result[:rounds]

        new_pilot_result = {}
        new_pilot_result['pilot_id'] = pilot_result[0]['pilot_id']
        new_pilot_result['callsign'] = pilot_result[0]['callsign']
        new_pilot_result['team_name'] = pilot_result[0]['team_name']
        new_pilot_result['node'] = pilot_result[0]['node']
        new_pilot_result['laps'] = 0
        new_pilot_result['starts'] = 0
        new_pilot_result['total_time_raw'] = 0
        new_pilot_result['total_time_laps_raw'] = 0
        
        # Store round times with round numbers for sorting and formatting
        round_times = []  # List of (round_num, time_raw, time_formatted)
        round_times_laps = []  # List of (round_num, time_raw, time_formatted)

        timeFormat = rhapi.db.option('timeFormat')
        
        # Track round number - use race number if available, otherwise use index
        for round_idx, race in enumerate(pilot_result, start=1):
            new_pilot_result['laps'] += race['laps']
            new_pilot_result['starts'] += race['starts']
            new_pilot_result['total_time_raw'] += race['total_time_raw']
            new_pilot_result['total_time_laps_raw'] += race['total_time_laps_raw']
            
            # Get round number from race if available, otherwise use index (1-based)
            round_num = race.get('race_num')
            if round_num is None:
                round_num = round_idx
            
            # Store individual race times with round numbers
            if race['total_time_raw'] and race['total_time_raw'] > 0:
                formatted_time = RHUtils.time_format(race['total_time_raw'], timeFormat)
                round_times.append((round_num, race['total_time_raw'], formatted_time))
            
            if race['total_time_laps_raw'] and race['total_time_laps_raw'] > 0:
                formatted_time_laps = RHUtils.time_format(race['total_time_laps_raw'], timeFormat)
                round_times_laps.append((round_num, race['total_time_laps_raw'], formatted_time_laps))

        # Sort by time (fastest first) and format as "{round} > {time}"
        round_times.sort(key=lambda x: x[1])  # Sort by time_raw (ascending = fastest first)
        round_times_laps.sort(key=lambda x: x[1])  # Sort by time_raw (ascending = fastest first)
        
        # Format as line-separated strings using HTML line breaks
        new_pilot_result['best_round_times'] = '<br>'.join([f"({round_num}) {time}" for round_num, _, time in round_times])
        new_pilot_result['best_round_times_laps'] = '<br>'.join([f"({round_num}) {time}" for round_num, _, time in round_times_laps])

        new_pilot_result['total_time'] = RHUtils.time_format(new_pilot_result['total_time_raw'], timeFormat)
        new_pilot_result['total_time_laps'] = RHUtils.time_format(new_pilot_result['total_time_laps_raw'], timeFormat)

        leaderboard.append(new_pilot_result)

    if race_format and race_format.start_behavior == StartBehavior.STAGGERED:
        # Sort by laps time
        leaderboard = sorted(leaderboard, key = lambda x: (
            -x['laps'], # reverse lap count
            x['total_time_laps_raw'] if x['total_time_laps_raw'] and x['total_time_laps_raw'] > 0 else float('inf') # total time ascending except 0
        ))

        # determine ranking and calculate delta times
        last_rank = None
        last_rank_laps = 0
        last_rank_time = 0
        leader_time = None
        
        for i, row in enumerate(leaderboard, start=1):
            pos = i
            if last_rank_laps == row['laps'] and last_rank_time == row['total_time_laps_raw']:
                pos = last_rank
            last_rank = pos
            last_rank_laps = row['laps']
            last_rank_time = row['total_time_laps_raw']

            row['position'] = pos
            
            # Store leader's time (first position with valid time)
            if leader_time is None and pos == 1 and row['total_time_laps_raw'] and row['total_time_laps_raw'] > 0:
                leader_time = row['total_time_laps_raw']
        
        # Add delta times for non-leaders
        for row in leaderboard:
            if row['position'] != 1 and row['total_time_laps_raw'] and row['total_time_laps_raw'] > 0 and leader_time:
                delta_raw = row['total_time_laps_raw'] - leader_time
                if delta_raw > 0:  # Only show positive deltas
                    # Convert to seconds if needed (check if value seems to be in milliseconds)
                    # If delta is very large (> 1000), assume it's in milliseconds
                    if delta_raw > 1000:
                        delta = delta_raw / 1000.0
                    else:
                        delta = delta_raw
                    # Format as +ss:mm (seconds:centiseconds)
                    seconds = int(delta)
                    centiseconds = int(round((delta - seconds) * 100))
                    # Handle centiseconds overflow (shouldn't happen, but safety check)
                    if centiseconds >= 100:
                        seconds += centiseconds // 100
                        centiseconds = centiseconds % 100
                    delta_str = f"+{seconds}:{centiseconds:02d}"
                    row['total_time_laps'] = row['total_time_laps'] + '<br>' + delta_str

        meta = {
            'rank_fields': [{
                'name': 'laps',
                'label': "Laps"
            },{
                'name': 'total_time_laps',
                'label': "Total"
            },{
                'name': 'starts',
                'label': "Starts"
            },{
                'name': 'best_round_times_laps',
                'label': "Best Round Times"
            }]
        }

    else:
        # Sort by race time
        leaderboard = sorted(leaderboard, key = lambda x: (
            -x['laps'], # reverse lap count
            x['total_time_raw'] if x['total_time_raw'] and x['total_time_raw'] > 0 else float('inf') # total time ascending except 0
        ))

        # determine ranking and calculate delta times
        last_rank = None
        last_rank_laps = 0
        last_rank_time = 0
        leader_time = None
        
        for i, row in enumerate(leaderboard, start=1):
            pos = i
            if last_rank_laps == row['laps'] and last_rank_time == row['total_time_raw']:
                pos = last_rank
            last_rank = pos
            last_rank_laps = row['laps']
            last_rank_time = row['total_time_raw']

            row['position'] = pos
            
            # Store leader's time (first position with valid time)
            if leader_time is None and pos == 1 and row['total_time_raw'] and row['total_time_raw'] > 0:
                leader_time = row['total_time_raw']
        
        # Add delta times for non-leaders
        for row in leaderboard:
            if row['position'] != 1 and row['total_time_raw'] and row['total_time_raw'] > 0 and leader_time:
                delta_raw = row['total_time_raw'] - leader_time
                if delta_raw > 0:  # Only show positive deltas
                    # Convert to seconds if needed (check if value seems to be in milliseconds)
                    # If delta is very large (> 1000), assume it's in milliseconds
                    if delta_raw > 1000:
                        delta = delta_raw / 1000.0
                    else:
                        delta = delta_raw
                    # Format as +ss:mm (seconds:centiseconds)
                    seconds = int(delta)
                    centiseconds = int(round((delta - seconds) * 100))
                    # Handle centiseconds overflow (shouldn't happen, but safety check)
                    if centiseconds >= 100:
                        seconds += centiseconds // 100
                        centiseconds = centiseconds % 100
                    delta_str = f"+{seconds}:{centiseconds:02d}"
                    row['total_time'] = row['total_time'] + '<br>' + delta_str

        meta = {
            'rank_fields': [{
                'name': 'laps',
                'label': "Laps"
            },{
                'name': 'total_time',
                'label': "Total"
            },{
                'name': 'starts',
                'label': "Starts"
            },{
                'name': 'best_round_times',
                'label': "Best Round Times"
            }]
        }

    return leaderboard, meta

def register_handlers(args):
    args['register_fn'](
        RaceClassRankMethod(
            "Laps/Time: Best % Rounds",
            rank_best_pct_rounds,
            {
                'round_pct': 50
            },
            [
                UIField('round_pct', "Percentage of rounds", UIFieldType.BASIC_INT, placeholder="50"),
                UIField('rounding', "Rounding", UIFieldType.SELECT, options=[
                        UIFieldSelectOption('down', "Down"),
                        UIFieldSelectOption('nearest', "Nearest"),
                        UIFieldSelectOption('up', "Up"),
                    ], value='down'),
            ]
        )
    )

def initialize(rhapi):
    rhapi.events.on(Evt.CLASS_RANK_INITIALIZE, register_handlers)

