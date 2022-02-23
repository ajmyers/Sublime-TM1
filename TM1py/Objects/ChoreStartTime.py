# -*- coding: utf-8 -*-

import datetime


class ChoreStartTime:
    """ Utility class to handle time representation for Chore Start Time
        
    """

    def __init__(self, year: int, month: int, day: int, hour: int, minute: int, second: int, tz: str = None):
        """
        
        :param year: year 
        :param month: month
        :param day: day
        :param hour: hour or None
        :param minute: minute or None
        :param second: second or None
        """
        self._datetime = datetime.datetime.combine(datetime.date(year, month, day), datetime.time(hour, minute, second))
        self.tz = tz

    @classmethod
    def from_string(cls, start_time_string: str) -> 'ChoreStartTime':
        # extract optional tz info (e.g., +01:00) from string end
        if '+' in start_time_string:
            # case "2020-11-05T08:00:01+01:00",
            tz = "+" + start_time_string.split('+')[1]
        elif start_time_string.count('-') == 3:
            # case: "2020-11-05T08:00:01-01:00",
            tz = "-" + start_time_string.split('-')[-1]
        else:
            tz = None

        # f to handle strange timestamp 2016-09-25T20:25Z instead of common 2016-09-25T20:25:00Z
        f = lambda x: int(x) if x else 0
        return cls(year=f(start_time_string[0:4]),
                   month=f(start_time_string[5:7]),
                   day=f(start_time_string[8:10]),
                   hour=f(start_time_string[11:13]),
                   minute=f(start_time_string[14:16]),
                   second=f(start_time_string[17:19]),
                   tz=tz)

    @property
    def start_time_string(self) -> str:
        # produce timestamp 2016-09-25T20:25Z instead of common 2016-09-25T20:25:00Z
        if not self._datetime.second:
            start_time = self._datetime.strftime("%Y-%m-%dT%H:%M")
        else:
            start_time = self._datetime.strftime("%Y-%m-%dT%H:%M:%S")

        if self.tz:
            start_time += self.tz
        else:
            start_time += "Z"

        return start_time

    @property
    def datetime(self) -> datetime:
        return self._datetime

    def __str__(self):
        return self.start_time_string

    def set_time(self, year: int = None, month: int = None, day: int = None, hour: int = None, minute: int = None,
                 second: int = None):
        if year:
            self._datetime = self._datetime.replace(year=year)
        if month:
            self._datetime = self._datetime.replace(month=month)
        if day:
            self._datetime = self._datetime.replace(day=day)
        if hour:
            self._datetime = self._datetime.replace(hour=hour)
        if minute:
            self._datetime = self._datetime.replace(minute=minute)
        if second:
            self._datetime = self._datetime.replace(second=second)

    def add(self, days: int = 0, hours: int = 0, minutes: int = 0, seconds: int = 0):
        self._datetime = self._datetime + datetime.timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)

    def subtract(self, days: int = 0, hours: int = 0, minutes: int = 0, seconds: int = 0):
        self._datetime = self._datetime - datetime.timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
