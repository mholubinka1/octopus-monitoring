from enum import Enum


class Duration(Enum):
    Year = (0,)
    Month = (1,)
    Week = (2,)
    Day = (3,)
    Hour = (4,)
    Minute = (5,)
    Second = (6,)


class Month(Enum):
    January = (1,)
    February = (2,)
    March = (3,)
    April = (4,)
    May = (5,)
    June = (6,)
    July = (7,)
    August = (8,)
    September = (9,)
    October = (10,)
    November = (11,)
    December = (12,)


class Weekday(Enum):
    Monday = (0,)
    Tuesday = (1,)
    Wednesday = (2,)
    Thursday = (3,)
    Friday = (4,)
    Saturday = (5,)
    Sunday = (6,)
