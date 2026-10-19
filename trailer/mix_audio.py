"""Original deterministic instrumental score. No voice or speech assets are read."""
import wave
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
RATE = 44100
def mix(name, duration, segments):
    t = np.arange(duration*RATE)/RATE
    # D minor ambience, a soft bass pulse, sparse high notes and transition swells.
    audio = sum(.012*np.sin(2*np.pi*hz*t + .08*np.sin(t*.21)) for hz in [73.416,110,146.832,174.614,220])
    beat = (t % .8)
    audio += .035*np.sin(2*np.pi*(52*t + .8*np.exp(-beat*25)))*np.exp(-beat*9)
    for n,start in enumerate(np.arange(1,duration-3,2.4)):
        dt=t-start
        hz=[293.665,440,349.228,523.251][n%4]
        env=np.where(dt>=0,np.exp(-np.maximum(dt,0)*1.5)*(1-np.exp(-np.maximum(dt,0)*40)),0)
        audio += .013*env*np.sin(2*np.pi*hz*dt)
    # Tempo-synced bass, arpeggio and restrained transition swells.
    for start in np.arange(0,duration,.4):
        dt=t-start
        env=np.where(dt>=0,np.exp(-np.maximum(dt,0)*15),0)
        audio += .025*env*np.sin(2*np.pi*880*dt)
    rng=np.random.default_rng(42)
    for cut in segments:
        dt=t-cut
        env=np.maximum(0,1-np.abs(dt)/.45)**2
        audio += .012*env*rng.standard_normal(len(t))
    audio *= 3.0
    audio*=np.minimum(t/1.2,1)*np.minimum((duration-t)/1.3,1)
    stereo=np.column_stack([audio,audio])
    with wave.open(str(ROOT/'public'/name),'wb') as output:
        output.setnchannels(2);output.setsampwidth(2);output.setframerate(RATE)
        output.writeframes((np.clip(stereo,-.98,.98)*32767).astype('<i2').tobytes())
    print(name, duration, 'seconds; peak', round(float(np.abs(audio).max()),3))

mix('soundtrack.wav',75,[7,15,27,38,51,62,70])
mix('short-soundtrack.wav',30,[4,8,13,20,25])

# The current film is a tighter 60-second edit of the instrumental score.
with wave.open(str(ROOT/'public'/'soundtrack.wav')) as source:
    rate=source.getframerate()
    channels=source.getnchannels()
    film=np.frombuffer(source.readframes(rate*60),dtype='<i2').reshape(-1,channels).astype(float)
film[-2*rate:]*=np.linspace(1,0,2*rate)[:,None]
with wave.open(str(ROOT/'public'/'film-soundtrack.wav'),'wb') as output:
    output.setnchannels(channels)
    output.setsampwidth(2)
    output.setframerate(rate)
    output.writeframes(film.astype('<i2').tobytes())
