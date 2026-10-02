"""Cooperative cancellation and measured per-stage progress."""
import time


class Cancelled(Exception):
    """The user cancelled before output commit."""


class Job:
    def __init__(self,progress=None,cancel=None):
        self.progress=progress
        self.cancel=cancel
        self.last_percent=0.0
        self.last_time=0.0
        self.last_stage=None

    def check(self):
        if self.cancel and (self.cancel.is_set() if hasattr(self.cancel,'is_set') else self.cancel()):
            raise Cancelled('Conversion cancelled. Existing output files were kept.')

    def update(self,percent,stage,detail='',force=False):
        self.check()
        now=time.monotonic()
        percent=max(self.last_percent,min(100.0,float(percent)))
        if self.progress and (force or stage!=self.last_stage or now-self.last_time>=.08):
            self.progress(percent,stage,detail)
            self.last_time=now; self.last_stage=stage
        self.last_percent=percent

    def portion(self,start,end,index,total,stage,detail=''):
        self.update(start+(end-start)*(index/max(1,total)),stage,detail)
