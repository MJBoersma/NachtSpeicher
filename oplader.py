#!/usr/bin/env python3
""" Control program for Night Charger Heating System (Nachtspeicherheizung).
Runs on Raspberry Pi with Internet connection. Charging level is based on
weather forecast, not on current outside temperature. """
from time import sleep
import logging
import json
from datetime import datetime, timedelta
from pyowm import OWM
from pyowm.utils import timestamps
from RPi import GPIO
import mqtt

def readconfig():
    """ Reads configuration files (json), return parms in dict """
    with open('oplader.cfg', encoding="utf-8") as file:
        opladerparms = json.load(file)
    with open('owm.cfg', encoding="utf-8") as file:
        owmparms = json.load(file)
    return {**opladerparms, **owmparms} # Merge both dicts

def tempmorgen():
    """ Returns the expected average temperature for tomorrow, in Celsius """
    # API call. This contacts OWM and returns a detailed weather forecast, 1 sample per 3h
    fc = owmmgr.forecast_at_id(cfg['owmcityid'],'3h')
    # From forecast object, get temperature for tomorrow between 6:30 en 20:30
    tempsmorgen = []
    cloudsmorgen = []
    for uur in [6,9,12,15,18,21]:
        morgentijd = timestamps.tomorrow(uur,0)
        weermorgenuur = fc.get_weather_at(morgentijd)
        tempmorgenuur = weermorgenuur.temperature(unit='celsius')
        tempsmorgen.append(tempmorgenuur['temp'])
    tempavg = sum(tempsmorgen)/len(tempsmorgen)
    # Lot of sunshine? Then discount the temperature, linearly: cfg[ZK] degrees for 100% sun
    for uur in [12,15]:
        morgentijd = timestamps.tomorrow(uur,0)
        weermorgenuur = fc.get_weather_at(morgentijd)
        cloudsmorgenuur = weermorgenuur.clouds # % cloudiness.  0=no clouds  100=no sunshine
        cloudsmorgen.append(cloudsmorgenuur)
    sunavg = 100 - sum(cloudsmorgen)/len(cloudsmorgen)

    tempcorr = tempavg + (sunavg * cfg['ZK'] / 100)
    logging.info(f"Morgen tussen 6:00 en 21:00 wordt het gemiddeld {tempavg:.0f}"
                 f"°C, met tussen 12:00 en 15:00 {sunavg:.0f}% zonneschijn. "
                 f"Gecorrigeerde temperatuur = {tempcorr:.0f}°C.")
    return tempcorr

def duty(s):
    """ Return duty cycle ED from desired charging goal (both in %) """
     # 80% ED = do not charge, 0% ED = full charge. Linear
    return 80 - s * 80 / 100

def tempdoel(temp, urlaubfactor=1.0):
    """ Compute charging target % at end of the night, based on expected outside temperature """
    E1 = cfg['E1' ] # Full charge if outside temperature below E1 Celsius
    E2 = cfg['E2' ] # Do not charge if outside temperature above E2 Celsius
    E15= cfg['E15'] # At E2 boundary temperature, charge by E15 % (Sockel Ladebeginn)

    if temp<E1:
        target = 100.0
    elif temp>E2:
        target = 0.0
    else:
        target = (100*(E2-temp) + E15*(temp-E1)) / (E2-E1)
    logging.info(f"Laaddoel = {target:.0f}%.")
    if urlaubfactor<0.9:
        logging.info(f"Hierop wordt nog een vakantiefactor = {urlaubfactor:.2f} toegepast")
    return urlaubfactor * target

def soll(NT, frei, secNT, tijd):
    """ Compute moving target as function from final target and current time """
    if not frei: # If charging not allowed, do not even try.
        return 0
    if not NT:   # Day fare, but charging allowed? Don't. Charging too expensive.
        return 0
    # Are we in between 18:00 en 22:00 and night fare? Then decreasing linear target
    vandaag18u= tijd.replace(hour=18,minute=0,second=0,microsecond=0)
    vandaag22u= tijd.replace(hour=22,minute=0,second=0,microsecond=0)
    bijladen=0
    if vandaag18u < tijd < vandaag22u:
        tot22u = vandaag22u - tijd  # How long before reaching tonight 22:00?
        # 18:00: 100% of this morning's target. Linearly decrease to 0% at 22:00.
        vieruur = vandaag22u - vandaag18u
        bijladen = doel * tot22u.total_seconds() / vieruur.total_seconds()

    # Charging for tomorrow: Rückwärtssteuerung. Start as late a possible, linearly increasing
    # until reaching final target 10 minutes before end of night fare
    tijdover = 100-(100*(secNT+600)/cfg['nachtstroomduur']) # How much % of the night fare left?
    if tijdover>doel:
        voormorgen = 0
    elif tijdover<0:
        # In the last 10 minutes, cut target in half, to avoid shutting off relay under load
        voormorgen = doel / 2
    else:
        voormorgen = doel-tijdover # Linearly increase, reach target at end of night fare

    # Charging evening or in the night? Take max of both computations
    return max(bijladen,voormorgen)

def urlaub(wanneer):
    """ Read json and return True if we are in a vacation period """
    morgen = wanneer + timedelta(days=1)
    # No charging at all in summer season
    with open('sommer.json', encoding="utf-8") as jsonfile:
        sommerjson = json.load(jsonfile)
    for u in sommerjson:
        start=datetime.strptime(u['start'] + f"-{morgen.year}", '%d-%m-%Y')
        end  =datetime.strptime(u['end']   + f"-{morgen.year}", '%d-%m-%Y')
        if start < morgen < end:
            return 0.0
    # For specified vacation dates, reduce charging level to one third
    with open('urlaub.json', encoding="utf-8") as jsonfile:
        urlaubjson = json.load(jsonfile)
    for u in urlaubjson:
        start=datetime.strptime(u['start'], '%d-%m-%Y')
        end  =datetime.strptime(u['end']  , '%d-%m-%Y')
        if start < morgen < end:
            return 1.0/3.0
    return 1.0


# Main program start
logging.basicConfig(filename="oplader.log",
      format = "%(asctime)-12s %(message)s",
      datefmt='%d %b %Y %H:%M',
      level=logging.INFO)

# Read heating parameters
cfg=readconfig()
soll_nieuw=0

# Setup OpenWeatherMap for weather forecast
owm=OWM(cfg['owmapikey'])
owmmgr=owm.weather_manager()

# Setup MQTT client (do not yet connect)
mqtt = mqtt.Client()

# Setup Raspberry GPIOs
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(cfg['pinCE'],       GPIO.OUT)
GPIO.setup(cfg['pinFreigabe'], GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(cfg['pinNacht'],    GPIO.IN, pull_up_down=GPIO.PUD_UP)
pwm=GPIO.PWM(cfg['pinCE'], 0.1) # frequency 0.1Hz, T=10s
pwm.start(duty(soll_nieuw))

nu=datetime.now()
vandaag1950=nu.replace(hour=19,minute=50,second=0,microsecond=0)

testmode = hasattr(GPIO, 'emulated')
if testmode:
    refreshinterval = 0
    GPIO.initclock(nu)
    print("Running in testmode, enabling testhooks")
else:
    refreshinterval = 60

# If program starts while night fare active, assume that night fare began 19:50
if nu > vandaag1950:
    nachtstroombegin=vandaag1950
else:
    nachtstroombegin=vandaag1950 - timedelta(days=1)
print('Neem aan dat nachtstroom begon op ' + str(nachtstroombegin))

# Assume that night fare ended 5:50am
nachtstroomeinde = nachtstroombegin - timedelta(hours=14)
nachttariefgat = timedelta(seconds=0)

freigabe=not GPIO.input(cfg['pinFreigabe'])
nachtstroom=not GPIO.input(cfg['pinNacht'])
tdnachtstroom = nu-nachtstroombegin

# Get a weather forecast when we start the program and compute charge target
try:
    weerberichtactueel = True
    doel=tempdoel(tempmorgen(), urlaub(nu))
except Exception as errmsg:
    logging.info(f"Fout bij weerbericht opvragen: {errmsg}, doel daarom op 0%.")
    weerberichtactueel = False
    doel=0

while True:
    nu = datetime.now()
    if testmode:
        nu = GPIO.moveclock(60)
        if nu is None: # Stop test program after 1 simulation day
            break

    cfg = readconfig() # Keep reading parameter files, to allow parameter changes while running

    nachtstroom_oud = nachtstroom
    nachtstroom=not GPIO.input(cfg['pinNacht'])
    if nachtstroom != nachtstroom_oud:
        if nachtstroom:
            if nu-nachtstroomeinde > timedelta(hours=6):
                logging.info('Nachttarief begint')
                nachtstroombegin=nu
                nachttariefgat = timedelta(seconds=0)
            else:
                # Less than 6 hour elapsed before night fare ended? Then we're resuming from break.
                logging.info('Nachttarief hervat')
                nachttariefgat = nu - nachtstroomeinde
        else:
            logging.info('Nachttarief voorbij')
            nachtstroomeinde = nu

    freigabe_oud = freigabe
    freigabe = not GPIO.input(cfg['pinFreigabe'])
    if freigabe != freigabe_oud:
        if freigabe:
            logging.info('Kachel laden nu mogelijk')
        else:
            logging.info('Kachel laden niet meer mogelijk')

    # Close to midnight, and no forecast for tomorrow yet? Get one and compute target
    if nu.hour >= 23 and nu.minute >= 3:  # Few minutes after, to avoid OWM server rush hour
        if not weerberichtactueel:
            try:
                weerberichtactueel = True
                doel=tempdoel(tempmorgen(),urlaub(nu))
            except Exception as errmsg:
                logging.info(f"Fout bij weerbericht opvragen: {errmsg},"
                             f"laaddoel onveranderd op {doel:0.f}%.")
    else: # Mark forecast as expired, need a fresh one before computing new target
        weerberichtactueel = False

    # How long did we benefit from night fare already? (do not include break)
    tdnachtstroom = nu-nachtstroombegin-nachttariefgat

    soll_oud = soll_nieuw
    soll_nieuw = soll(nachtstroom, freigabe, tdnachtstroom.total_seconds(), nu)
    pwm.ChangeDutyCycle(duty(soll_nieuw))

    # Publish NT + charge level on MQTT
    mqtt.publish("N" if nachtstroom else "T", soll_nieuw)
    # Print NT/LF on console
    printmsg = nu.strftime("%d-%m-%Y %H:%M   ")
    printmsg += 'NT ' if nachtstroom else '   '
    printmsg += 'LF ' if freigabe    else '   '
    printmsg += f" Soll = {soll_nieuw:3.0f}%"
    printmsg += f" Doel = {doel:3.0f}%"
    print(printmsg)
    if abs(soll_nieuw-soll_oud) > 1.0:  # Only big changes to logfile
        logging.info(f"Sollwert van {soll_oud:.0f}% naar {soll_nieuw:.0f}%")
    sleep(refreshinterval) # Stay on this charge target for a while. Program loop is slow

if testmode:
    pwm.plotHistory('chargegoal.png')
