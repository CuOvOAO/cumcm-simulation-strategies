"""Isolated Q4 fixture; original simulator.py remains unchanged.

    This is a local model of the supplied rules, not the official simulator.
    Directional orientation is the source-to-receiver halfplane normal.
"""
import math
from simulator import Simulator


class Q4Simulator(Simulator):
    def __init__(self,case,**kwargs):
        super().__init__(case,**kwargs)
        for s in self.sources.values():
            if s.get('type','omni') not in ('omni','directional'):
                raise ValueError('invalid source type')
            if s.get('type')=='directional' and (isinstance(s.get('orientation'),bool)
                    or not isinstance(s.get('orientation'),(int,float)) or not math.isfinite(s['orientation'])):
                raise ValueError('finite directional orientation required')

    def _error(self,ch):
        mode=self.case.get('error_mode','hash')
        if mode=='positive': return 1.
        if mode=='negative': return -1.
        if mode=='checker': return 1. if (math.floor(self.pos[0]/23)+math.floor(self.pos[1]/23)+ch)%2 else -1.
        if mode=='smooth': return math.sin(self.pos[0]/127+self.pos[1]/211+ch)
        if mode!='hash': raise ValueError('unknown error fixture')
        return super()._error(ch)

    def measure(self,position,channel):
        self._prepare(position,channel)
        if channel != self.channel:
            self.virtual+=1
            self.counts['switch']+=1
        self.channel=channel
        self.virtual+=5
        self.counts['measure']+=1
        s=self.sources.get(channel)
        result={'measure_result':'no_signal'}
        if s and channel not in self.cleared:
            x,y=self.pos[0]-s['x'],self.pos[1]-s['y']
            t=math.radians(s.get('orientation',0.))
            visible=s.get('type','omni')=='omni' or x*math.cos(t)+y*math.sin(t)>=-1e-10
            if math.hypot(x,y)<=s['radius'] and visible:
                if math.hypot(x,y)<=5:
                    result={'measure_result':'near'}
                else:
                    b=math.degrees(math.atan2(-y,-x))
                    result={'measure_result':'direction','svd_deg':round((b+self._error(channel))%360,2)%360}
        return self._record('measure',channel,result)
