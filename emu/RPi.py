""" Dummy implementation of Raspberry Pi GPIO functions.
    Allows for testing Python programs on a non-Raspberry computer """
from datetime import timedelta
import matplotlib.pyplot as plt

class GPIO():
    BCM = 0
    OUT = 1
    IN = 2
    PUD_UP = 3
    inputs = []
    outputs = []
    emulated = True
    @classmethod
    def setwarnings(cls, val):
        pass
    @classmethod
    def setmode(cls,val):
        pass
    @classmethod
    def setup(cls, pin, mode, pull_up_down=PUD_UP):
        if mode == GPIO.IN:
            cls.inputs.append(pin)
        elif mode == GPIO.OUT:
            cls.outputs.append(pin)
    @classmethod
    def input(cls, pin):
        assert pin in GPIO.inputs, "pin not defined as input"
        if pin==23: # NT
            return cls.getNT()
        if pin==7: # LF
            return cls.getLF()
        return 0
    @classmethod
    def getNT(cls):
        """ Simulate NT behavior as observed on Nov 18, 2024 """
        avondaan = cls.clock.replace(hour=19,minute=50)
        avonduit = cls.clock.replace(hour=21,minute=50)
        nachtaan = cls.clock.replace(hour=22,minute=50)
        nachtuit = cls.clock.replace(hour= 4,minute=50)
        if cls.clock < nachtuit or cls.clock >= nachtaan:
            return False
        if cls.clock > avondaan and cls.clock <= avonduit:
            return False
        return True

    @classmethod
    def getLF(cls):
        """ Simulate LF behavior as observed on Nov 18, 2024 """
        middagaan = cls.clock.replace(hour=12,minute=00)
        middaguit = cls.clock.replace(hour=16,minute=30)
        avondaan  = cls.clock.replace(hour=17,minute=20)
        avonduit  = cls.clock.replace(hour=21,minute=50)
        if not cls.getNT():
            return False
        if cls.clock > middagaan and cls.clock <= middaguit:
            return False
        if cls.clock > avondaan  and cls.clock <= avonduit:
            return False
        return True
    @classmethod
    def initclock(cls,now):
        cls.starttime = now
        cls.clock = now
    @classmethod
    def moveclock(cls,incr=60):
        cls.clock += timedelta(seconds=incr)
        if cls.clock > cls.starttime + timedelta(days=1):
            return None
        return cls.clock
    @classmethod
    def getclock(cls):
        return cls.clock

    class PWM():
        def __init__(self, pin, freq):
            assert pin in GPIO.outputs, "PWM pin not defined as output"
            self.freq = freq
            print(f"Using emulated GPIO output pin {pin} as PWM, running at frequency {freq} Hz")
            self.xsamples = []
            self.ysamples = []
            self.duty = None
            self.started = False
        def start(self, duty):
            self.duty=duty
            self.started = True
        def _soll(self, ed):
            """ Compute charge target from duty cycle ED """
            # 80% ED = niet laden, 0% ED = volladen. Daartussen lineair
            return 100 - ed * 100 / 80
        def ChangeDutyCycle(self, duty):
            assert self.started, "Must start PWM before changing duty cycle"
            self.xsamples.append(GPIO.getclock())
            self.ysamples.append(self._soll(duty))
            self.duty=duty
        def plotHistory(self, filename):
            plt.scatter(self.xsamples, self.ysamples)
            plt.gcf().autofmt_xdate()
            plt.title("Charge target as function of time")
            plt.xlabel("Time")
            plt.ylabel("Charge if below %")
            plt.savefig(filename)
