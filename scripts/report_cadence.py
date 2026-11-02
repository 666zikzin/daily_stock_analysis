"""US-session-based reporting calendar. No model calls or network requests.

Regular NYSE holidays; emergency exchange closures require an explicit update.
"""
from datetime import date, datetime, timedelta, timezone

SHANGHAI = timezone(timedelta(hours=8))

def _nth(year, month, weekday, n):
    first = date(year, month, 1)
    return first + timedelta(days=(weekday-first.weekday()) % 7 + 7*(n-1))

def _observed(day):
    return day + timedelta(days=-1 if day.weekday()==5 else 1 if day.weekday()==6 else 0)

def _easter(year):
    a=year%19; b=year//100; c=year%100; d=b//4; e=b%4
    f=(b+8)//25; g=(b-f+1)//3; h=(19*a+b-d-g+15)%30
    i=c//4; k=c%4; l=(32+2*e+2*i-h-k)%7; m=(a+11*h+22*l)//451
    return date(year,(h+l-7*m+114)//31,(h+l-7*m+114)%31+1)

def us_session(day):
    if day.weekday()>=5: return False
    y=day.year
    holidays={_nth(y,1,0,3),_nth(y,2,0,3),_easter(y)-timedelta(days=2),
              _nth(y,5,0,5) if _nth(y,5,0,5).month==5 else _nth(y,5,0,4),
              _observed(date(y,6,19)),_observed(date(y,7,4)),_nth(y,9,0,1),
              _nth(y,11,3,4),_observed(date(y,12,25))}
    # NYSE does not observe a Saturday New Year on the preceding Friday.
    new_year=date(y,1,1)
    if new_year.weekday()!=5: holidays.add(_observed(new_year))
    return day not in holidays

def expected_reports(now):
    local=now.astimezone(SHANGHAI)
    if local.weekday() not in (1,2,3,4,5): return ()
    reports=[]
    if us_session(local.date()-timedelta(days=1)): reports.append('dsa')
    last_session=local.date()-timedelta(days=1)
    if (local.weekday()==5 and us_session(last_session)) or (local.weekday()==4 and us_session(last_session) and not us_session(local.date())):
        reports.append('ta')
    return tuple(reports)

if __name__=='__main__':
    import sys
    expected=expected_reports(datetime.now(timezone.utc))
    print('run' if len(sys.argv)>1 and sys.argv[1] in expected else 'skip')
