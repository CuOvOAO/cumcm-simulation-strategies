"""Q3 local physics sandbox, standard library only. Not the official server."""
import copy
import hashlib
import math
import time

VERSION = '1.0.0'

class Simulator:
    def __init__(self, case, max_actions=100000):
        self.case = copy.deepcopy(case)
        sources = self.case['sources']
        channels = [s['channel'] for s in sources]
        if not 10 <= len(sources) <= 16 or len(set(channels)) != len(channels):
            raise ValueError('Need 10..16 sources with unique channels')
        for s in sources:
            if type(s['channel']) is not int or not 1 <= s['channel'] <= 20:
                raise ValueError('Invalid source channel')
            if not all(math.isfinite(s[k]) for k in ('x', 'y', 'radius')):
                raise ValueError('Nonfinite source')
            if math.hypot(s['x'], s['y']) > 1800.000000001 or not 1000 <= s['radius'] <= 1500:
                raise ValueError('Source outside allowed bounds')
        self.sources = {s['channel']: s for s in sources}
        self.pos, self.channel, self.virtual = (0.0, 0.0), 1, 0.0
        self.cleared = set()
        self.active = False
        self.started = False
        self.start = None
        self.elapsed = 0.0
        self.log = []
        self.max_actions = max_actions
        self.distance = 0.0
        self.counts = dict(measure=0, switch=0, clear_success=0, clear_fail=0)

    def enter(self):
        if self.started:
            raise RuntimeError('Already entered')
        self.started = self.active = True
        self.start = time.perf_counter()
        return {'accepted': True, 'virtual_time_s': 0.0}

    def _prepare(self, position, channel):
        if not self.active:
            raise RuntimeError('Not active')
        if len(self.log) >= self.max_actions or self.virtual >= 360000:
            raise RuntimeError('Local action/virtual-time limit')
        if time.perf_counter() - self.start >= 1200:
            raise RuntimeError('Local 1200-second runtime limit')
        if type(channel) is not int or not 1 <= channel <= 20:
            raise ValueError('Channel must be integer 1..20')
        x, y = map(float, position)
        if not all(math.isfinite(v) and abs(v) <= 2000000 for v in (x, y)):
            raise ValueError('Invalid coordinates')
        distance = math.dist(self.pos, (x, y))
        self.distance += distance
        self.virtual += distance / 5
        self.pos = (x, y)

    def _error(self, channel):
        # Independent of action order and Python hash randomization.
        # Synthetic spatial error field: fixed within a 1-m cell per channel.
        cell = (math.floor(self.pos[0]), math.floor(self.pos[1]))
        key = '{}:{}:{}:{}'.format(self.case['error_seed'], channel, *cell)
        n = int.from_bytes(hashlib.sha256(key.encode('ascii')).digest()[:8], 'big')
        return 2 * (n / (2**64 - 1)) - 1

    def _record(self, action, channel, result):
        result = dict(result, accepted=True, virtual_time_s=self.virtual)
        self.log.append(dict(action=action, position=list(self.pos), channel=channel,
                             response=copy.deepcopy(result)))
        return result

    def measure(self, position, channel):
        self._prepare(position, channel)
        if channel != self.channel:
            self.virtual += 1
            self.counts['switch'] += 1
        self.channel = channel
        self.virtual += 5
        self.counts['measure'] += 1
        s = self.sources.get(channel)
        result = {'measure_result': 'no_signal'}
        if s and channel not in self.cleared:
            d = math.dist(self.pos, (s['x'], s['y']))
            if d <= s['radius']:
                if d <= 5:
                    result = {'measure_result': 'near'}
                else:
                    angle = math.degrees(math.atan2(s['y']-self.pos[1], s['x']-self.pos[0]))
                    result = {'measure_result': 'direction',
                              'svd_deg': round((angle + self._error(channel)) % 360, 2) % 360}
        return self._record('measure', channel, result)

    def clear(self, position, channel):
        self._prepare(position, channel)
        s = self.sources.get(channel)
        success = bool(s and channel not in self.cleared and
                       math.dist(self.pos, (s['x'], s['y'])) <= 20)
        self.virtual += 5 if success else 3
        self.counts['clear_success' if success else 'clear_fail'] += 1
        if success:
            self.cleared.add(channel)
        return self._record('clear', channel,
                            {'clear_result': 'success' if success else 'no_target_in_range'})

    def exit(self):
        if not self.active:
            raise RuntimeError('Not active')
        self.elapsed = time.perf_counter() - self.start
        self.active = False
        return {'accepted': True, 'virtual_time_s': self.virtual, 'exit_reason': 'user_exit'}

    def report(self):
        if self.active:
            raise RuntimeError('Report only after exit')
        n = len(self.cleared)
        return dict(total_sources=len(self.sources), cleared=n,
                    cleared_fraction=n/len(self.sources), virtual_time_s=self.virtual,
                    average_clear_time_s=self.virtual/n if n else None,
                    runtime_s=self.elapsed, distance_m=self.distance, **self.counts)

class RobotAPI:
    """Observation-only interface. Not a security boundary against introspection."""
    def __init__(self, simulator):
        self.__sim = simulator
    def measure(self, position, channel):
        return self.__sim.measure(position, channel)
    def clear(self, position, channel):
        return self.__sim.clear(position, channel)
