### Control program for electric night storage heating system (German: Nachtspeicherheizung)

Runs on a Raspberry Pi with Internet connection.
2 GPIOs are used as input to receive NT (night fare) and LF (charge permission) signals, respectively.
1 GPIO drives a solid state relay which generates the 230V AC PWM control signal.
For testing purposes, program runs also on a regular PC (not a Raspberry).
Only then, create a symbolic link to emu/RPi.py.

