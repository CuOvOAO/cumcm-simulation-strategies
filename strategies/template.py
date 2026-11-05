"""Copy to strategy_b.py and replace run(). No hidden truth access allowed."""
def run(api, seed=0):
    position = (0.0, 0.0)
    for channel in range(1, 21):
        response = api.measure(position, channel)
        if response['measure_result'] == 'near':
            api.clear(position, channel)
    # This template only scans the origin. It does NOT finish the task.
    # Maintain channel -> observations, conservative feasible region, cleared flag.
    # Update regions, generate candidate actions, compare predicted remaining time.
