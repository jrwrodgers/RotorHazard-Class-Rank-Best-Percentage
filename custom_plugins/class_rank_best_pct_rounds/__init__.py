''' Class ranking method: Laps/Time, Best % rounds '''

import logging
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
    pilot_race_order = {}  # Track sequential race order for each pilot
    
    for heat in heats:
        races = rhapi.db.races_by_heat(heat.id)

        for race in races:
            race_result = rhapi.db.race_results(race)

            if race_result:
                # Get race number from race object if available (for reference)
                race_num = None
                if hasattr(race, 'round') and race.round:
                    race_num = race.round
                elif hasattr(race, 'race_num') and race.race_num:
                    race_num = race.race_num
                elif hasattr(race, 'id'):
                    race_num = race.id
                
                for pilotresult in race_result['by_race_time']:
                    pilot_id = pilotresult['pilot_id']
                    if pilot_id not in pilotresults:
                        pilotresults[pilot_id] = []
                        pilot_race_order[pilot_id] = 0
                    
                    # Increment sequential race order for this pilot
                    pilot_race_order[pilot_id] += 1
                    sequential_round = pilot_race_order[pilot_id]
                    
                    # Add race data to pilotresult for later reference
                    pilotresult_with_race = pilotresult.copy()
                    pilotresult_with_race['race_num'] = race_num  # Keep original for reference
                    pilotresult_with_race['sequential_round'] = sequential_round  # Sequential order for this pilot
                    pilotresults[pilot_id].append(pilotresult_with_race)
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

        # Calculate total starts across ALL races (before filtering to best percentage)
        total_starts = sum(race.get('starts', 0) for race in pilotresults[pilotresultlist] if race.get('starts'))

        pilot_result = pilot_result[:rounds]

        # Skip pilots with no rounds to include
        if not pilot_result or rounds == 0:
            continue

        new_pilot_result = {}
        new_pilot_result['pilot_id'] = pilot_result[0]['pilot_id']
        new_pilot_result['callsign'] = pilot_result[0]['callsign']
        new_pilot_result['team_name'] = pilot_result[0]['team_name']
        new_pilot_result['node'] = pilot_result[0]['node']
        new_pilot_result['laps'] = 0
        new_pilot_result['starts'] = total_starts  # Total starts across all races
        new_pilot_result['total_time_raw'] = 0
        new_pilot_result['total_time_laps_raw'] = 0
        
        # Store round times with round numbers for sorting and formatting
        round_times = []  # List of (round_num, time_raw, time_formatted, laps)
        round_times_laps = []  # List of (round_num, time_raw, time_formatted, laps)

        timeFormat = rhapi.config.get_item('UI', 'timeFormat')
        
        # Track round number - use race number if available, otherwise use index
        # Use enumeration index to ensure each race gets a unique identifier
        for round_idx, race in enumerate(pilot_result, start=1):
            new_pilot_result['laps'] += race['laps']
            # Note: starts is already set to total_starts above, don't accumulate here
            new_pilot_result['total_time_raw'] += race['total_time_raw']
            new_pilot_result['total_time_laps_raw'] += race['total_time_laps_raw']
            
            # Use sequential round number (order this pilot ran the race)
            # This shows 1 for first race, 2 for second race, etc., regardless of heat/race numbers
            round_num = race.get('sequential_round')
            if round_num is None:
                # Fallback to index if sequential_round not available
                round_num = round_idx
            
            # Store individual race times with round numbers and laps
            # Each race's total_time_raw is the individual race time, not cumulative
            if race['total_time_raw'] and race['total_time_raw'] > 0:
                formatted_time = rhapi.utils.format_time_to_str(race['total_time_raw'], timeFormat)
                laps_count = race.get('laps', 0)
                round_times.append((round_num, race['total_time_raw'], formatted_time, laps_count))
            
            if race['total_time_laps_raw'] and race['total_time_laps_raw'] > 0:
                formatted_time_laps = rhapi.utils.format_time_to_str(race['total_time_laps_raw'], timeFormat)
                laps_count = race.get('laps', 0)
                round_times_laps.append((round_num, race['total_time_laps_raw'], formatted_time_laps, laps_count))

        # Sort by laps (more laps first), then by time (fastest first)
        # Tuple structure: (round_num, time_raw, formatted_time, laps_count)
        round_times.sort(key=lambda x: (-x[3], x[1]))  # Sort by laps descending, then time ascending
        round_times_laps.sort(key=lambda x: (-x[3], x[1]))  # Sort by laps descending, then time ascending
        
        # Format as line-separated strings using HTML line breaks
        # Format as "{round} > {time} ({laps})" for each individual race time
        # Wrap in div with styling for better column width control and right alignment with padding
        if round_times:
            times_content = '<br>'.join([f"{round_num} > {time} ({laps})" for round_num, _, time, laps in round_times])
            new_pilot_result['best_round_times'] = f'<div style="min-width: 200px; max-width: 300px; word-wrap: break-word; text-align: right; padding-right: 10px;">{times_content}</div>'
        else:
            new_pilot_result['best_round_times'] = ''
        
        if round_times_laps:
            times_content_laps = '<br>'.join([f"{round_num} > {time} ({laps})" for round_num, _, time, laps in round_times_laps])
            new_pilot_result['best_round_times_laps'] = f'<div style="min-width: 200px; max-width: 300px; word-wrap: break-word; text-align: right; padding-right: 10px;">{times_content_laps}</div>'
        else:
            new_pilot_result['best_round_times_laps'] = ''

        new_pilot_result['total_time'] = rhapi.utils.format_time_to_str(new_pilot_result['total_time_raw'], timeFormat)
        new_pilot_result['total_time_laps'] = rhapi.utils.format_time_to_str(new_pilot_result['total_time_laps_raw'], timeFormat)

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
                    # Determine time units: RotorHazard stores times in milliseconds
                    # Race times are typically 30-600 seconds = 30000-600000 milliseconds
                    # If leader_time > 1000, it's likely in milliseconds, otherwise seconds
                    if leader_time > 1000:
                        # Times are in milliseconds, convert to seconds
                        delta = delta_raw / 1000.0
                    else:
                        # Times are in seconds (unlikely but handle for safety)
                        delta = delta_raw
                    
                    # Format as +ss:mm (seconds:centiseconds)
                    # Ensure delta is positive and reasonable
                    if delta > 0:
                        seconds = int(delta)
                        fractional = delta - seconds
                        centiseconds = int(round(fractional * 100))
                        # Handle centiseconds overflow
                        if centiseconds >= 100:
                            seconds += centiseconds // 100
                            centiseconds = centiseconds % 100
                        elif centiseconds < 0:
                            # Shouldn't happen, but safety check
                            centiseconds = 0
                        delta_str = f"+{seconds}:{centiseconds:02d}"
                        row['total_time_laps'] = row['total_time_laps'] + '<br><span style="font-size: 0.85em;">' + delta_str + '</span>'

        meta = {
            'rank_fields': [{
                'name': 'laps',
                'label': "Laps",
                'class': 'text-center'
            },{
                'name': 'total_time_laps',
                'label': "Total",
                'class': 'text-center'
            },{
                'name': 'starts',
                'label': "Starts",
                'class': 'text-center'
            },{
                'name': 'best_round_times_laps',
                'label': "Best Round Times",
                'class': 'text-right',
                'style': 'min-width: 200px; max-width: 300px; padding-right: 10px;'
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
                    # Determine time units: RotorHazard stores times in milliseconds
                    # Race times are typically 30-600 seconds = 30000-600000 milliseconds
                    # If leader_time > 1000, it's likely in milliseconds, otherwise seconds
                    if leader_time > 1000:
                        # Times are in milliseconds, convert to seconds
                        delta = delta_raw / 1000.0
                    else:
                        # Times are in seconds (unlikely but handle for safety)
                        delta = delta_raw
                    
                    # Format as +ss:mm (seconds:centiseconds)
                    # Ensure delta is positive and reasonable
                    if delta > 0:
                        seconds = int(delta)
                        fractional = delta - seconds
                        centiseconds = int(round(fractional * 100))
                        # Handle centiseconds overflow
                        if centiseconds >= 100:
                            seconds += centiseconds // 100
                            centiseconds = centiseconds % 100
                        elif centiseconds < 0:
                            # Shouldn't happen, but safety check
                            centiseconds = 0
                        delta_str = f"+{seconds}:{centiseconds:02d}"
                        row['total_time'] = row['total_time'] + '<br><span style="font-size: 0.85em;">' + delta_str + '</span>'

        meta = {
            'rank_fields': [{
                'name': 'laps',
                'label': "Laps",
                'class': 'text-center'
            },{
                'name': 'total_time',
                'label': "Total",
                'class': 'text-center'
            },{
                'name': 'starts',
                'label': "Starts",
                'class': 'text-center'
            },{
                'name': 'best_round_times',
                'label': "Best Round Times",
                'class': 'text-right',
                'style': 'min-width: 200px; max-width: 300px; padding-right: 10px;'
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

